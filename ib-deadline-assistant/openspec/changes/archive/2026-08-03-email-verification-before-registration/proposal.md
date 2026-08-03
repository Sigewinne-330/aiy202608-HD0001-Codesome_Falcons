## Why

Public registration currently creates an authenticated account immediately after receiving an email string, so automated clients can create accounts in bulk without proving email ownership. Requiring a short-lived, abuse-limited email challenge before account creation protects the demo and future deployments while keeping registration understandable for legitimate users.

## Goal

Prevent automated account creation and reduce registration abuse by requiring users to verify ownership of their email address before an account can be created.

## Background

The existing Vue form posts username, email, and password directly to FastAPI. The backend checks uniqueness, inserts the user, and returns a JWT in one request. There is no mail transport, verification state, expiry, one-time proof, failed-attempt limit, resend cooldown, or server-side request throttling.

## User Story

As a new user, I want to receive and enter a verification code for my email so that I can securely create my account and know that other people cannot register using my address.

## Requirements

- Let a prospective user request a verification code for a valid email address.
- Send a short-lived code through a configurable email service and handle delivery failure without leaving usable verification state.
- Verify only the latest code, reject wrong/expired/exhausted codes, and allow each code to succeed once.
- Return a high-entropy, one-time registration proof after successful code verification.
- Require and atomically consume that proof when creating the account.
- Limit rapid requests by normalized email and source IP, limit guessing attempts, and avoid revealing whether an email is already registered from the request-code endpoint.
- Provide a focused frontend flow with code entry, resend feedback, loading states, and recoverable errors.

## Scope

- New pre-registration request-code and verify-code APIs.
- A persisted email-verification model/table and SQL bootstrap change.
- SMTP-backed email delivery behind a small testable service abstraction.
- Backend validation, expiry, one-time use, failed-attempt budget, and database-backed email/IP request limits.
- Registration API and Vue registration-flow updates.
- Automated backend tests for required success, rejection, abuse-control, and delivery-failure scenarios.
- Configuration example and user/developer documentation updates.

## Non-goals

- CAPTCHA, device fingerprinting, SMS, social login, or third-party identity verification.
- Password reset or post-registration email-change verification.
- A distributed Redis rate limiter or asynchronous job queue for the MVP.
- Refactoring the duplicate legacy `AppUser` model or unrelated authentication architecture.
- Production hardening of pre-existing CORS and default JWT-secret behavior.

## What Changes

- Introduce an email-verification lifecycle before registration.
- Add configurable SMTP delivery and verification policy settings.
- Add persistent hashed challenge/proof state and abuse-control counters.
- Change `POST /api/auth/register` to require a verified one-time registration proof.
- Change the registration UI from a single submit action to email challenge, code verification, and final account creation.
- Add an isolated backend test harness and feature tests.

## Capabilities

### New Capabilities

- `pre-registration-email-verification`: Requesting, delivering, validating, expiring, rate-limiting, and consuming email verification before account creation.

### Modified Capabilities

None. This repository has no existing durable OpenSpec capabilities to modify.

## Impact

- **Backend:** `routers/auth.py`, user schemas, startup metadata, a new verification model/service, and email/configuration integration.
- **API:** two new pre-registration endpoints; registration request gains a required verification proof and therefore intentionally rejects legacy unverified requests.
- **Database:** one new `email_verifications` table; no destructive changes to `users`.
- **Frontend:** auth store and registration view state/interaction changes.
- **Dependencies:** no runtime dependency is required for SMTP because Python's standard library is sufficient; pytest/TestClient support is added for development tests.
- **Operations:** SMTP credentials and sender settings must be configured outside tests; rate limits are process-independent because history is persisted in the database.

