## Why

The email-verification feature passes isolated tests but is not operationally ready in the current local environment: the frontend can be started without a reachable backend, SMTP can be absent, and the UI exposes the browser-native `Failed to fetch` message while never reaching code entry. The previous verification report also treated an intercepted-API browser check as broadly successful even though a real inbox delivery and registration path remained unverified.

## Goal

Make pre-registration email verification reliably runnable, diagnosable, and truthfully acceptable end to end, so a developer or evaluator can distinguish backend connectivity, SMTP delivery, UI-state, and functional failures and can complete registration using a code received in a real inbox.

## Background

The current Vue page shows code entry only after `POST /api/auth/verification-codes` returns HTTP 202. This state machine is correct, but a missing backend causes `fetch` to reject before any HTTP response and the page displays an unhelpful English error. When the backend is available but SMTP settings are missing, the endpoint correctly returns HTTP 503, yet there is no explicit readiness check or completed real-provider smoke-test evidence. Existing automated tests use SQLite and a fake sender, and the archived browser verification intercepted auth endpoints by design.

## User Story

As a prospective user or evaluator, I want the registration page to tell me why a verification code cannot be requested and what I can do next, and I want a successful acceptance result to mean that a real code was delivered, entered, and used to create an account.

## Requirements

- Preserve the two-step registration flow: code entry appears only after the request-code API accepts the request.
- Replace raw browser transport errors with actionable, localized guidance while preserving entered account details and allowing retry.
- Distinguish an unreachable backend from a reachable backend whose email provider is unavailable, without exposing credentials or sensitive provider details.
- Provide a reproducible readiness/startup procedure covering Python dependencies, MySQL, backend health, frontend proxying, required schema, and SMTP configuration presence.
- Keep fake-sender tests and intercepted browser tests as deterministic automated gates, but label them accurately.
- Require a controlled real-SMTP smoke test and successful inbox-backed registration before declaring end-to-end acceptance complete; secrets and received codes must never be committed or logged.

## Scope

- Registration-page error handling and explicit code-entry transition behavior.
- Backend/frontend connectivity and email-delivery readiness checks suitable for local/demo operation.
- Startup and SMTP setup documentation that matches the repository's actual `.venv`, ports, proxy, and environment loading behavior.
- Automated regression coverage for transport/delivery UI states and the existing backend verification suite.
- A manual real-provider acceptance checklist with evidence fields and an honest pass/blocked result.
- Correction of verification documentation so mocked and real-provider evidence are reported separately.

## Non-goals

- Changing the code/proof cryptography, expiry, one-time-use, rate-limit, or database model semantics already covered by the existing capability.
- Committing SMTP credentials, inbox contents, verification codes, or other secrets.
- Selecting or purchasing a particular email provider for the user.
- Adding an asynchronous queue, Redis, CAPTCHA, SMS verification, password reset, or unrelated authentication refactors.
- Making all application features unavailable merely because SMTP is not configured; the failure remains scoped to registration-code delivery.

## What Changes

- Add actionable registration errors for backend transport failure and email-service unavailability.
- Make the details-to-code state transition and retry behavior explicit and regression-tested.
- Add a reproducible registration-readiness check and align startup documentation with the actual project environment.
- Split acceptance reporting into automated/fake-provider, UI-with-interception, and real-SMTP end-to-end gates.
- Require real inbox delivery and successful proof-backed registration before the end-to-end gate can pass.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pre-registration-email-verification`: Strengthen runtime failure/recovery behavior, code-entry visibility rules, operational readiness, and the evidence required to claim end-to-end acceptance.

## Impact

- **Frontend:** `frontend/src/stores/auth.js`, `frontend/src/views/RegisterView.vue`, and focused UI regression coverage.
- **Backend/operations:** existing health/configuration surfaces and a minimal readiness check; no verification data-model migration is expected.
- **Documentation:** `README.md`, AI-development verification records, and a real-SMTP acceptance checklist/report.
- **External system:** a user-configured SMTP provider and controlled recipient inbox are required only for the final real-provider gate.
- **Compatibility:** API success payloads and verified-registration security semantics remain unchanged; error presentation and operational checks become more explicit.
