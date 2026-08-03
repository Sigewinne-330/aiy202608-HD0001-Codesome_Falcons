## 1. Persistence and Configuration

- [x] 1.1 Add the `EmailVerification` SQLAlchemy model, indexes, model export, and matching non-destructive `init_db.sql` table definition.
  - Dependencies: none
  - Priority: P0
  - Verification method: import all models, create metadata in isolated SQLite, and inspect that expected columns/indexes exist.

- [x] 1.2 Add a committed `.env.example` and environment-backed verification/SMTP policy with safe defaults, validation, and a finite network timeout.
  - Dependencies: none
  - Priority: P0
  - Verification method: load policy with defaults and overridden test environment values without reading or exposing secrets.

## 2. Backend Verification Flow

- [x] 2.1 Add server-authoritative request/response schemas for normalized email, six-digit code, registration proof, username, and password constraints.
  - Dependencies: none
  - Priority: P0
  - Verification method: API/schema tests reject invalid email, malformed code/token, and invalid account fields.

- [x] 2.2 Implement the SMTP email sender abstraction with code-free logging, TLS/auth support, dependency injection, and graceful delivery failure/timeout errors.
  - Dependencies: 1.2
  - Priority: P0
  - Verification method: fake-sender tests capture delivery without network; failure and timeout fakes map to unusable challenge plus HTTP 503.

- [x] 2.3 Implement verification request creation, HMAC code storage, latest-code invalidation, generic existing-email handling, resend cooldown, and rolling email/IP limits.
  - Dependencies: 1.1, 1.2, 2.1, 2.2
  - Priority: P0
  - Verification method: focused API tests cover success, existing email, old code after resend, cooldown, hourly email limit, and IP limit.

- [x] 2.4 Implement code verification with expiry, constant-time digest comparison, failed-attempt budget, one-time success, and high-entropy hashed registration proof issuance.
  - Dependencies: 2.3
  - Priority: P0
  - Verification method: focused API tests cover correct, wrong, expired, exhausted, old, and reused codes.

- [x] 2.5 Require and atomically consume a same-email, unexpired registration proof while creating the user; preserve the existing successful JWT response and use generic failure handling.
  - Dependencies: 2.4
  - Priority: P0
  - Verification method: tests cover successful registration, no proof, mismatched/expired/reused proof, existing email, and unique-conflict rollback.

## 3. Frontend Registration Experience

- [x] 3.1 Extend the auth API store with request-code and verify-code calls and pass the registration proof to final registration.
  - Dependencies: 2.3, 2.4, 2.5
  - Priority: P0
  - Verification method: frontend production build succeeds and request bodies match the documented API contract.

- [x] 3.2 Convert the registration view to account-details/code-entry states with resend countdown, email reset, focused loading states, and recoverable errors.
  - Dependencies: 3.1
  - Priority: P0
  - Verification method: production build succeeds; manual flow verifies email-change reset, resend state, success redirect, and error recovery.

## 4. Automated Verification

- [x] 4.1 Add an isolated standard-library backend test harness using FastAPI TestClient, SQLite, DB dependency override, deterministic policy, and fake email sender.
  - Dependencies: 1.1, 2.2
  - Priority: P0
  - Verification method: test database and fake sender run without MySQL or SMTP access.

- [x] 4.2 Add required functional tests for successful verification, wrong code, expired code, multiple requests, registration without verification, existing account, and delivery failure.
  - Dependencies: 2.3, 2.4, 2.5, 4.1
  - Priority: P0
  - Verification method: all named tests pass with `python -m unittest discover`.

- [x] 4.3 Add security/edge tests for old and reused codes, exhausted guesses, mismatched/expired/reused proofs, IP/email limits, normalized email, and timeout recovery.
  - Dependencies: 4.2
  - Priority: P1
  - Verification method: all security/edge tests pass and no plaintext code/proof field exists in persisted rows or API request-code responses.

## 5. Documentation and Completion

- [x] 5.1 Update README API/configuration/setup documentation and synchronize any implementation decisions back into the active OpenSpec artifacts.
  - Dependencies: 2.5, 3.2
  - Priority: P1
  - Verification method: documented endpoint bodies, status behavior, environment variables, and startup sequence match implementation.

- [x] 5.2 Run backend compile checks, the complete backend test suite, frontend production build, OpenSpec strict validation, and OpenSpec verification; resolve every critical finding.
  - Dependencies: 4.3, 5.1
  - Priority: P0
  - Verification method: all commands exit zero, tasks are checked off, and the verification report has no critical issue.
