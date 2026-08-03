## Context

See `proposal.md` for motivation and the delta Spec for the revised behavior contract. The security-sensitive code/proof lifecycle already has 23 passing isolated tests. The remaining failure is cross-layer: the browser depends on Vite's `/api` proxy, the proxy depends on FastAPI at port 8000, startup depends on Python/MySQL, and eligible code requests depend on external SMTP configuration and delivery.

The current browser API helper lets a rejected `fetch` escape as the browser-native English `TypeError`. The registration component changes from `details` to `code` only after an accepted request, which is correct and must remain unchanged. Existing browser evidence used intercepted endpoints and therefore proves UI behavior but not SMTP or inbox delivery.

## Goals / Non-Goals

**Goals:**

- Make transport, HTTP, delivery, and validation failures distinguishable without leaking operational secrets.
- Preserve the existing two-state registration model and backend security contract.
- Provide one reproducible readiness path before a demo or real-provider test.
- Define layered evidence so a pass statement accurately identifies what was exercised.
- Finish with a controlled real-inbox registration using user-supplied SMTP credentials outside version control.

**Non-Goals:**

- Replace SMTP, introduce a queue, or redesign challenge persistence.
- Change request-code, verify-code, register success payloads, or JWT/session behavior.
- Store provider credentials or acceptance codes in repository artifacts.
- Fail unrelated application startup solely because email delivery is unavailable.

## Architecture

The runtime and acceptance flow is layered so each failure has one owner:

```text
Registration page
      │
      ▼
Vite /api proxy ──transport failure──▶ localized backend guidance
      │
      ▼
FastAPI route ────HTTP 503────────────▶ localized email-service guidance
      │
      ▼
SMTP provider ────reject/timeout──────▶ invalidated challenge + retry
      │
      ▼
Controlled inbox ─received code───────▶ code entry → proof → registration
```

Verification remains split into four gates:

1. Backend unit/API tests with SQLite and a fake sender.
2. Frontend production build plus focused error/state regression tests.
3. Browser UI flow with intercepted APIs, explicitly labeled UI-only.
4. Real SMTP/inbox end-to-end flow, required for the end-to-end pass.

## Data Model

No schema change is planned. The readiness procedure checks that `email_verifications` exists and is accessible but does not read or print challenge digests, tokens, codes, credentials, or user passwords. Existing invalidation and delivery-status behavior remains authoritative.

## API Changes

No successful API contract changes are planned.

- `POST /api/auth/verification-codes` keeps HTTP 202, 422, 429, and 503 semantics.
- The frontend classifies a rejected `fetch` separately from an HTTP response.
- HTTP 503 continues to use the backend's non-sensitive recoverable detail.
- `/api/health` remains the backend liveness probe; readiness tooling combines it with proxy, schema, and local configuration checks instead of exposing SMTP configuration publicly.

## Component Changes

### Frontend API helper

Wrap the network call so a rejected `fetch` becomes a stable application error category rather than raw browser text. Preserve status and safe server detail for HTTP errors. The registration view maps transport failure and HTTP 503 to separate localized messages; other validated server details keep their existing behavior.

### Registration view

Keep `step = details` until request-code resolves successfully. On any failure, clear loading, retain username/email/password/confirmation in memory, and leave code/proof state empty. After HTTP 202, set the normalized target email, enter `code`, show the six-digit field, and start the resend countdown.

### Readiness check

Add a dependency-light, read-only project command that reports independent checks for:

- expected Python environment/imports;
- backend health at the configured URL;
- frontend `/api/health` proxy reachability;
- database connectivity and `email_verifications` table presence;
- required SMTP setting presence and valid TLS-mode combination.

The command reports setting names and pass/fail only, never values. It does not send mail or create verification rows. Documentation provides exact backend/frontend startup commands and explains that environment-injected secrets are valid even when `backend/.env` is absent.

### Acceptance report

Create a fresh report for this change with separate rows for fake-provider automation, intercepted browser UI, readiness, and real-provider end to end. Real-provider evidence records only timestamp, non-secret environment/provider label, recipient domain if appropriate, observed stages, and result. It never records credentials, the received code, token, or full inbox content.

## Technical Decisions

### Decision: Keep code entry conditional on HTTP 202

Showing the field before a challenge is accepted would let users enter a code that cannot exist and would hide runtime failure. The correct fix is actionable first-step failure handling, not an always-visible code field.

Alternative considered: always render account and code fields together. Rejected because it weakens state clarity and complicates stale-email handling.

### Decision: Classify errors at the shared API boundary

The API helper is where transport failure can be distinguished reliably from HTTP 503/422/429. The view remains responsible for user-facing registration guidance.

Alternative considered: match the string `Failed to fetch` inside the component. Rejected because browser text varies by engine and locale.

### Decision: Use a local read-only readiness command, not public credential readiness data

A local command can validate environment and database prerequisites without publishing configuration state through an unauthenticated endpoint. `/api/health` remains simple liveness.

Alternative considered: add SMTP readiness fields to `/api/health`. Rejected because public configuration metadata adds exposure and still cannot prove provider delivery.

### Decision: Separate real-provider acceptance from deterministic automation

Fake senders are necessary for repeatable edge/security tests, while intercepted APIs are useful for UI states. Neither proves provider authentication, TLS, delivery, inbox receipt, or the complete live registration transaction. The report therefore has independent gates and no aggregate pass while the real gate is missing.

## Security

- Keep `.env`, credentials, app passwords, codes, proofs, and inbox contents out of Git and reports.
- Readiness output exposes only setting names and boolean status.
- Real-provider testing uses a controlled test account and an unregistered recipient.
- Existing generic anti-enumeration responses remain unchanged.
- Do not add logging around code contents or SMTP credentials while diagnosing failures.

## Compatibility

Existing API clients continue to receive the same statuses and payloads. Registration still requires a proof for the same normalized email. The only user-visible compatibility change is replacing browser-native transport text with localized guidance. Existing accounts and database rows require no migration.

## Migration Plan

1. Add error classification and regression coverage.
2. Add the read-only readiness command and align startup/SMTP documentation.
3. Run existing backend tests, frontend build, and intercepted browser checks.
4. Configure SMTP outside Git, run readiness, then complete one controlled real-inbox registration.
5. Record layered results and synchronize the living Spec only after every required gate is honestly classified.

Rollback removes the new frontend messaging/tests/readiness command and restores documentation. No database rollback is needed.

## Risks / Trade-offs

- **Provider accepts SMTP but inbox delivery is delayed or filtered** → record the gate as blocked/failed at inbox receipt; inspect spam/provider logs without exposing message secrets.
- **Readiness passes but provider credentials are rejected on first send** → readiness proves configuration presence, not authentication; the real-provider gate remains required.
- **A generic 503 cannot reveal exact provider cause to the user** → keep UI guidance safe and put detailed diagnostics in server-side code-free logs.
- **Manual real-inbox testing is not fully deterministic** → isolate it as a release/demo gate rather than weakening deterministic automated tests.
- **User-supplied SMTP credentials are unavailable** → complete all other tasks but leave end-to-end acceptance explicitly blocked; do not claim completion.
