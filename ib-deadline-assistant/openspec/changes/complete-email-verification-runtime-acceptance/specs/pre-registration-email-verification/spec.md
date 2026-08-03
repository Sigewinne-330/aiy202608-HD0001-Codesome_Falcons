## MODIFIED Requirements

### Requirement: Reliable code delivery

The system SHALL send codes only through configured email delivery, SHALL never expose a code or provider credential in an API response or application log, and SHALL leave no usable challenge when configuration, delivery, or timeout prevents the message from being accepted by the provider.

#### Scenario: Email delivery succeeds

- **GIVEN** an eligible request and a correctly configured, available email provider
- **WHEN** the provider accepts the verification message
- **THEN** the system marks the challenge deliverable and returns the generic accepted response

#### Scenario: Email delivery fails

- **GIVEN** an eligible request whose configured email provider rejects delivery or exceeds its configured timeout
- **WHEN** the system attempts delivery
- **THEN** the system invalidates the pending challenge, returns a recoverable service error, and allows a later retry subject to abuse limits

#### Scenario: Email delivery is not configured

- **GIVEN** the backend is reachable but required email-delivery configuration is absent or invalid
- **WHEN** an eligible user requests a verification code
- **THEN** the system returns a recoverable service-unavailable response, creates no usable challenge, and exposes no credential or sensitive provider detail

### Requirement: Registration user experience

The registration page SHALL guide a user through code request, code entry, and account creation, SHALL show code entry only after the request-code API accepts the request, and SHALL preserve safe account details while providing actionable recovery for transport and delivery failures.

#### Scenario: Accepted request reveals code entry

- **GIVEN** valid account details and a reachable backend with available email delivery
- **WHEN** the request-code API returns its accepted response
- **THEN** the page replaces the account-details step with a six-digit code field, identifies the target email, and exposes verify, resend, and edit-email controls

#### Scenario: User completes the browser flow

- **GIVEN** valid account details and access to the supplied email inbox
- **WHEN** the user requests a code and submits the correct code received in that inbox
- **THEN** the page verifies the email, completes registration, stores the returned session, and routes to the authenticated application

#### Scenario: User changes email after requesting a code

- **GIVEN** the page has an active code-entry state
- **WHEN** the user changes the email address
- **THEN** the page discards the prior code/proof state and requires verification of the new address

#### Scenario: Backend is unreachable

- **GIVEN** valid account details but no HTTP response can be obtained from the backend through the configured frontend route
- **WHEN** the user requests a verification code
- **THEN** the page stops loading, remains on account details, preserves safe entered values, and displays localized guidance to start or check the backend before retrying

#### Scenario: Email service is unavailable

- **GIVEN** the backend is reachable but returns a service-unavailable response for code delivery
- **WHEN** the user requests a verification code
- **THEN** the page stops loading, remains on account details, preserves safe entered values, and displays localized guidance to check email-service configuration or retry later

#### Scenario: Validation, expiry, or rate limit fails

- **GIVEN** the user is in the registration flow
- **WHEN** a validation, expiry, guessing-limit, or request-rate-limit error occurs
- **THEN** the page stops loading, preserves safe user-entered account data, displays an actionable error, and allows an appropriate retry or reset

## ADDED Requirements

### Requirement: Registration runtime readiness

The project SHALL provide a reproducible, non-secret readiness procedure that distinguishes frontend availability, frontend-to-backend proxy connectivity, backend health, required database schema availability, and email-delivery configuration presence before a registration demonstration.

#### Scenario: Runtime is ready for real verification

- **GIVEN** dependencies are installed, MySQL and the backend are running, the frontend proxy reaches the backend, the verification table exists, and required email settings are present
- **WHEN** an operator runs the documented readiness procedure
- **THEN** every check reports success without printing credentials, verification codes, or other secrets

#### Scenario: Runtime prerequisite is missing

- **GIVEN** at least one required service, route, schema object, or email setting is unavailable
- **WHEN** an operator runs the documented readiness procedure
- **THEN** the failed prerequisite is identified separately with an actionable recovery step and the runtime is not reported ready

### Requirement: Truthful end-to-end acceptance

Verification evidence MUST distinguish deterministic fake-provider tests, browser tests with intercepted APIs, and real-provider end-to-end execution, and the capability MUST NOT be reported as end-to-end accepted until a controlled real inbox receives a code that completes proof-backed registration.

#### Scenario: Automated and intercepted checks pass without real delivery

- **GIVEN** backend tests, the frontend build, and an intercepted-API browser flow all pass
- **WHEN** no controlled real inbox delivery and registration has completed
- **THEN** automated and UI gates are reported passed while the real-provider end-to-end gate remains blocked or not run

#### Scenario: Real-provider registration succeeds

- **GIVEN** readiness checks pass and a controlled unregistered recipient inbox is available
- **WHEN** a code is requested, received from the configured provider, entered in the browser, and used to complete registration
- **THEN** the real-provider end-to-end gate is reported passed with non-secret evidence of the run

#### Scenario: Real-provider registration fails

- **GIVEN** a real-provider acceptance attempt is made
- **WHEN** delivery, code entry, verification, registration, session persistence, or redirect fails
- **THEN** the end-to-end gate is reported failed or blocked at the observed stage and no broader all-passed claim is made

## Acceptance Criteria

- [ ] A raw browser `Failed to fetch` message is never shown to the registration user.
- [ ] Code entry is absent before request acceptance and visible after HTTP 202 acceptance.
- [ ] Backend-unreachable and email-service-unavailable states remain retryable and have distinct actionable guidance.
- [ ] Account details remain safe and available after request failure.
- [ ] The readiness procedure checks each runtime layer independently and emits no secrets.
- [ ] Existing 23 backend verification tests and the frontend production build still pass.
- [ ] Intercepted browser verification is labeled as UI-only evidence.
- [ ] End-to-end acceptance remains blocked until a real inbox-backed registration succeeds.

## Edge Cases

- The frontend is reachable while the backend is stopped.
- The backend is reachable directly while the frontend proxy target is wrong.
- SMTP settings are present but invalid, rejected by the provider, or incompatible with the selected TLS mode.
- The provider accepts the SMTP transaction but delivery to the inbox is delayed or filtered as spam.
- A request succeeds but the browser loses the response before changing steps.
- Readiness checks run in an environment where secrets are injected without a local `.env` file.
- The controlled acceptance email is already registered and therefore receives the generic suppressed response.
- Automated gates pass while real-provider evidence is missing, stale, or from a different build.
