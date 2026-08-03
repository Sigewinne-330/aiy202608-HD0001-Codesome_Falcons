## 1. Registration Failure Experience

- [x] 1.1 Add stable transport-versus-HTTP error classification at the shared frontend auth API boundary without matching browser-specific error text.
  - Dependencies: none
  - Priority: P0
  - Verification method: with the backend unavailable, a request produces the transport category; HTTP 422/429/503 responses retain status and safe server detail.

- [x] 1.2 Map backend-unreachable and email-service-unavailable failures to distinct localized registration guidance while preserving account details and keeping the page in the details step.
  - Dependencies: 1.1
  - Priority: P0
  - Verification method: browser checks confirm no raw `Failed to fetch`, no code field on failure, stopped loading, preserved values, and a successful retry path.

- [x] 1.3 Lock the details-to-code transition to an accepted request response and verify the six-digit input, target email, resend countdown, verify action, and edit-email reset behavior.
  - Dependencies: 1.2
  - Priority: P0
  - Verification method: intercepted-API browser checks cover transport failure, HTTP 503, HTTP 202 transition, resend, and edit-email reset and are labeled UI-only.

## 2. Runtime Readiness

- [x] 2.1 Add a dependency-light, read-only readiness command that independently checks Python runtime/imports, backend health, frontend proxy health, database connectivity, the `email_verifications` table, required SMTP setting presence, and valid TLS-mode selection.
  - Dependencies: none
  - Priority: P0
  - Verification method: the command exits non-zero with named actionable failures in the current incomplete environment and exits zero only when every required layer is available.

- [x] 2.2 Ensure readiness output never prints environment values, credentials, codes, proofs, database contents, or full connection strings, and support both `backend/.env` and externally injected environment settings.
  - Dependencies: 2.1
  - Priority: P0
  - Verification method: focused standard-library tests exercise missing/present settings and assert output contains only check names, status, and safe guidance.

- [x] 2.3 Add focused tests for readiness failure isolation so stopped backend, broken frontend proxy, missing table, missing SMTP settings, and conflicting TLS modes are reported as separate causes.
  - Dependencies: 2.1, 2.2
  - Priority: P1
  - Verification method: all readiness tests pass without MySQL, SMTP, or network access by using controlled fakes/mocks.

## 3. Reproducible Setup and Acceptance Documentation

- [x] 3.1 Align README startup commands with the actual project virtual environment, MySQL prerequisite, backend port 8000, frontend port/proxy behavior, `.env` loading, and provider-neutral SMTP configuration requirements.
  - Dependencies: 2.1
  - Priority: P0
  - Verification method: a clean-terminal walkthrough can start both services and the documented readiness command names the expected state without revealing secrets.

- [x] 3.2 Document provider-specific values only as examples, require app passwords where applicable, and explain HTTP 503, inbox delay/spam, already-registered recipient suppression, and safe retry behavior.
  - Dependencies: 3.1
  - Priority: P1
  - Verification method: documentation review confirms every current environment variable and recovery path matches implementation and no credential is committed.

- [x] 3.3 Add a layered acceptance report/checklist that separates backend fake-sender tests, frontend build, intercepted browser UI checks, readiness, and real SMTP/inbox registration.
  - Dependencies: 1.3, 2.3
  - Priority: P0
  - Verification method: the report cannot display an aggregate end-to-end pass while the real-provider row is not run, blocked, or failed.

## 4. Automated and UI Verification

- [x] 4.1 Run backend compilation, all 23 existing verification tests, new readiness tests, the frontend production build, OpenSpec strict validation, and whitespace checks; resolve every introduced failure.
  - Dependencies: 1.3, 2.3, 3.3
  - Priority: P0
  - Verification method: every command exits zero; the existing Vite chunk-size warning may be reported but is not treated as an email-verification failure.

- [x] 4.2 Run browser verification with controlled intercepted responses for transport failure, HTTP 503, HTTP 202 code-entry transition, wrong-code recovery, resend, edit-email reset, successful registration request shape, session persistence, and redirect.
  - Dependencies: 4.1
  - Priority: P0
  - Verification method: each scenario has observed non-secret evidence and the result is recorded explicitly as intercepted/UI-only.

- [ ] 4.3 Start the actual MySQL, FastAPI, and Vite stack and run the readiness command before any external email attempt.
  - Dependencies: 4.1, 3.2
  - Priority: P0
  - Verification method: direct backend health, frontend proxy health, schema, and SMTP configuration-presence checks all pass in the target environment.

## 5. Real Provider Gate and Completion

- [ ] 5.1 With user-authorized SMTP credentials supplied outside Git and a controlled unregistered recipient, request a real code, confirm inbox receipt, enter it in the browser, complete proof-backed registration, verify session persistence and authenticated redirect, and record only non-secret evidence.
  - Dependencies: 4.2, 4.3
  - Priority: P0
  - Verification method: one real provider/inbox flow succeeds end to end; if credentials, inbox access, delivery, or any later stage is unavailable, mark this task blocked/failed and do not claim overall completion.

- [ ] 5.2 Re-run all automated gates after the real-provider attempt, produce the final layered verification report, and synchronize the accepted delta into the living Spec only when results match the report.
  - Dependencies: 5.1
  - Priority: P0
  - Verification method: automated gates remain green, the report accurately classifies every layer, `openspec validate --all --strict` passes, and no secret or verification code appears in tracked changes.

- [ ] 5.3 Archive the change only after every required task is complete and the real-provider end-to-end gate is passed; otherwise leave the change active with the exact blocker documented.
  - Dependencies: 5.2
  - Priority: P0
  - Verification method: archive guidance reports no critical issue and the living Spec, task state, and verification report agree.
