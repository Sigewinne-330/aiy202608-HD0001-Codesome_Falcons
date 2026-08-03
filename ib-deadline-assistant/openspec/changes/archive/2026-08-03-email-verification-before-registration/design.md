## Context

See `proposal.md` for motivation and scope. Current registration is a synchronous FastAPI route that writes `models.user.User` and immediately issues a JWT. The app uses SQLAlchemy/MySQL, manual SQL bootstrap plus metadata auto-creation, a Vue/Vuetify registration view, and no existing mail service, cache, queue, migration framework, or automated test harness.

The security boundary must live on the backend because browser validation is bypassable. The implementation should remain demo-ready without adding Redis, a worker, or a third-party email SDK.

## Goals / Non-Goals

**Goals:**

- Prove control of the exact normalized email before user creation.
- Make codes and registration proofs short-lived, single-use, and non-recoverable from stored data.
- Bound resend and guessing abuse across process restarts.
- Make email delivery configurable, timeout-bounded, and mockable in tests.
- Preserve the current JWT/session response and existing auth architecture after registration succeeds.

**Non-Goals:**

- Exactly-once email delivery, a distributed queue, or distributed-rate-limit precision under extreme concurrency.
- CAPTCHA, SMS, password reset, email-change verification, or account recovery.
- Refactoring legacy user tables, CORS, or unrelated auth code.

## Architecture

The browser registration flow becomes:

1. Collect username, email, password, and confirmation locally.
2. Call `POST /api/auth/verification-codes` with email only.
3. Show code entry and a resend countdown.
4. Call `POST /api/auth/verification-codes/verify` with email and code.
5. Receive an opaque short-lived registration token.
6. Call the existing `POST /api/auth/register` with account data plus that token.
7. Store the unchanged JWT/user response and route to `/calendar`.

Backend responsibilities are separated into:

- Auth router: HTTP validation/status mapping and final registration transaction.
- Verification service: normalization, code/proof generation and hashing, challenge lifecycle, limits, and atomic validation helpers.
- Email service: construct and send one verification message using configured SMTP with a finite timeout.
- Persistence model: durable challenge/request history used for state and rate limits.

No code or token is returned by the request-code API. Codes are passed to the email adapter only and are never logged.

## Data Model

Add table `email_verifications`:

| Column | Type | Purpose |
|---|---|---|
| `id` | integer PK | Challenge identity |
| `email` | varchar(100), indexed | Normalized target address |
| `code_salt` | varchar(64) | Random salt for the low-entropy code digest |
| `code_digest` | varchar(64) | HMAC-SHA256 digest; no plaintext code |
| `registration_token_digest` | varchar(64), nullable, indexed/unique | SHA-256 digest of the high-entropy proof |
| `request_ip` | varchar(45), indexed | IPv4/IPv6 source or stable `unknown` value |
| `delivery_status` | varchar(20) | `pending`, `sent`, `failed`, or `suppressed` |
| `failed_attempts` | integer | Wrong-code budget consumed |
| `expires_at` | datetime | Code expiry in UTC |
| `proof_expires_at` | datetime, nullable | Registration-proof expiry in UTC |
| `verified_at` | datetime, nullable | Time the code first succeeded |
| `consumed_at` | datetime, nullable | Time account creation consumed the proof |
| `invalidated_at` | datetime, nullable | Superseded, failed, or locked challenge |
| `created_at` | timestamp | Request/rate-limit history timestamp |

Indexes support newest-email challenge lookup, rolling email counts, and rolling IP counts. Rows are retained for rate-limit history; cleanup of old rows is a deferred maintenance task because it does not affect MVP correctness.

Default policy values, configurable by environment:

- Code length: 6 numeric digits.
- Code lifetime: 10 minutes.
- Registration-proof lifetime: 15 minutes after successful code verification.
- Failed attempts per challenge: 5.
- Resend cooldown: 60 seconds per normalized email after a successful send.
- Rolling accepted-request limit: 5 per email per hour; sent and enumeration-suppressed requests both count, while failed delivery remains immediately retryable.
- Rolling accepted-request limit: 20 per IP per hour.
- SMTP network timeout: 10 seconds.

## API Changes

### `POST /api/auth/verification-codes`

Request:

```json
{"email": "student@example.com"}
```

Success for both eligible and already-registered addresses: HTTP 202 with a generic message and `retry_after_seconds`. Validation errors return 422. Rate limits return 429 and a `Retry-After` header. Provider failure/timeout for an eligible address returns 503 after marking the challenge unusable.

The server derives source IP from the connected client. It does not trust forwarded headers until a trusted proxy configuration exists.

### `POST /api/auth/verification-codes/verify`

Request:

```json
{"email": "student@example.com", "code": "123456"}
```

Success: HTTP 200 with `verification_token` and `expires_in_seconds`. Invalid, stale, expired, used, or locked challenges return a generic 400 verification error; validation errors return 422.

### `POST /api/auth/register`

Adds required `verification_token` to the existing username/email/password body. Missing tokens fail schema validation. Invalid, mismatched, expired, consumed proofs and uniqueness races return a generic registration failure without creating a user. Success response remains the current JWT and user payload.

## Component Changes

### Backend

- Add `models/email_verification.py` and export it from `models/__init__.py` so startup metadata creates the table.
- Extend `init_db.sql` with equivalent non-destructive table creation.
- Add verification request/response schemas and strengthen username/email/password validation.
- Add `services/email_verification.py` for lifecycle/security logic.
- Add `services/email_service.py` using `EmailMessage` and `smtplib`, with environment-backed SMTP settings and a dependency provider that tests can override.
- Extend `routers/auth.py` with request/verify endpoints and guarded registration.
- Add a committed `.env.example` and README settings/API documentation.

### Frontend

- Extend `stores/auth.js` with request-code and verify-code methods; final `register` accepts the proof token.
- Convert `RegisterView.vue` to account-details and code-entry states, with resend countdown, email reset behavior, loading, and errors. If final registration loses its response after the proof was issued, attempt normal login with the submitted credentials to recover an account that was already committed.

### Tests

- Build an isolated FastAPI test app with SQLite, dependency-overridden DB sessions, and a fake email sender.
- Cover successful verification, wrong/expired/old/used codes, resend limits, unverified registration, existing email, send failure, timeout behavior, and frontend production build.

## Technical Decisions

### Decision: Persist pre-registration challenges in MySQL

Database persistence fits the current architecture and keeps expiry, one-time use, and rolling limits stable across process restarts. An in-memory dictionary would be simpler but would reset on restart and diverge across workers; Redis would add deployment overhead beyond the MVP.

### Decision: Separate code verification from final registration with an opaque proof

The verify endpoint consumes the low-entropy code once and returns a high-entropy token. Final registration can then be retried without resubmitting a guessable code, while the token remains bound to the email and single-use. Passing the code directly to `/register` would be smaller but conflates challenge validation with account data submission and weakens the explicit verification flow.

### Decision: HMAC low-entropy codes; hash high-entropy proofs

Six-digit codes are vulnerable to offline enumeration if stored with plain SHA-256. HMAC-SHA256 with the application secret plus a per-row random salt prevents practical offline recovery after a database-only leak. The 256-bit opaque proof has enough entropy for ordinary SHA-256 storage.

### Decision: Persist every accepted request outcome

`sent`, `failed`, and suppressed existing-email requests leave rate-limit history. Sent and suppressed requests share the same email cooldown/hourly limit so an already-registered address cannot be used for unlimited database writes. Failed sends are immediately invalidated and do not trigger the email limit, but still count toward the IP abuse window. This supports graceful user retry without allowing provider-failure loops to bypass IP controls.

### Decision: Generic enumeration-resistant responses

The request-code endpoint uses the same accepted payload for new and existing email addresses and sends no code to existing users. Final registration also uses a generic failure for invalid proof/uniqueness conflicts. This trades some error specificity for a smaller enumeration surface.

### Decision: Standard-library SMTP behind dependency injection

Python's `smtplib` and `EmailMessage` avoid a runtime SDK dependency. A small sender interface allows deterministic fake delivery and failure/timeout tests. A hosted provider SDK or background queue can replace the adapter later without changing the behavior contract.

### Decision: Database transaction consumes proof with user creation

Final registration selects the proof row for update, re-checks all validity conditions, inserts the user, marks the proof consumed, and commits once. Unique-constraint races roll back and return a generic failure. This prevents two successful account creations from one proof within the guarantees of the existing MySQL deployment.

## Security

- Normalize emails with trim plus lowercase before lookup, storage, digesting, and comparison.
- Generate codes and proof tokens with `secrets`; compare digests with constant-time comparison where values are computed in application code.
- Never store or log plaintext codes/proofs, SMTP passwords, or user passwords.
- Cap code attempts and request rates on the backend regardless of frontend behavior.
- Do not trust `X-Forwarded-For` without an explicit trusted-proxy setup.
- Preserve generic responses at enumeration-sensitive boundaries.
- Validate email, username, password, token, and code shapes server-side.

## Compatibility

The registration endpoint intentionally becomes incompatible with clients that omit `verification_token`; they receive 422 and cannot bypass verification. Login, `/me`, JWT shape, user response shape, and authenticated product APIs remain unchanged. Existing accounts require no migration.

## Migration Plan

1. Deploy the new table through `init_db.sql` for fresh environments and SQLAlchemy `create_all` for existing environments.
2. Configure SMTP sender credentials and verification policy environment variables.
3. Deploy backend endpoints before or together with the frontend because old registration clients will be rejected after the backend change.
4. Run focused tests and a real-provider smoke test in the target environment.

Rollback removes the frontend verification UI and restores the previous registration schema/handler. The new table can remain unused; rollback does not require destructive database changes.

## Risks / Trade-offs

- **SMTP is synchronous and can consume a request worker for up to the timeout** → keep a strict timeout and defer queueing until scale requires it.
- **Database counting is less efficient than Redis at high volume** → use indexed time-window queries; the expected competition load is low.
- **Concurrent requests can both send before the latest record wins** → delivery completion compares monotonic record IDs; a late-finishing older request invalidates itself when a newer sent challenge already exists.
- **Generic errors reduce user-specific guidance** → frontend copy explains common recovery actions without revealing account state.
- **Ignored local `config.py` is not a reproducible configuration source** → email service reads documented environment settings directly and `.env.example` is committed.
- **Old verification rows accumulate** → retain for the MVP and add scheduled cleanup as a documented follow-up.
