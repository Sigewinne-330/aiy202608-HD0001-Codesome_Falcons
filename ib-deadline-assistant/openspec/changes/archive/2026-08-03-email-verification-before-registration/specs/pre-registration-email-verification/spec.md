## Purpose

This capability ensures that a new account can be created only after the prospective user proves control of the normalized email address through a short-lived, abuse-limited challenge.

## ADDED Requirements

### Requirement: Verification code request

The system SHALL accept a valid email address before registration, normalize it consistently, and respond without disclosing whether that address already belongs to an account.

#### Scenario: New email requests a code

- **GIVEN** a syntactically valid email that is not registered and is within request limits
- **WHEN** the prospective user requests a verification code
- **THEN** the system accepts the request and attempts to deliver one code to the normalized address

#### Scenario: Registered email requests a code

- **GIVEN** an email that already belongs to an account
- **WHEN** a client requests a verification code
- **THEN** the system returns the same generic accepted response used for an eligible address and sends no code

#### Scenario: Invalid email requests a code

- **GIVEN** a value that is not a valid email address
- **WHEN** a client requests a verification code
- **THEN** the system rejects the request as invalid without attempting delivery

### Requirement: Reliable code delivery

The system SHALL send codes through configured email delivery, SHALL never expose a code in an API response or application log, and SHALL leave no usable challenge when delivery fails or times out.

#### Scenario: Email delivery succeeds

- **GIVEN** an eligible request and an available email provider
- **WHEN** the provider accepts the verification message
- **THEN** the system marks the challenge deliverable and returns the generic accepted response

#### Scenario: Email delivery fails

- **GIVEN** an eligible request whose email provider fails or exceeds its configured timeout
- **WHEN** the system attempts delivery
- **THEN** the system invalidates the pending challenge, returns a recoverable service error, and allows a later retry subject to abuse limits

### Requirement: Current short-lived code

The system SHALL accept only the newest successfully delivered code for an email, SHALL reject expired codes, and SHALL prevent a code from succeeding more than once.

#### Scenario: Correct current code

- **GIVEN** the newest code for an email is correct, unexpired, and unused
- **WHEN** the prospective user submits that code with the same normalized email
- **THEN** the system verifies the challenge once and returns a short-lived registration proof

#### Scenario: Incorrect code

- **GIVEN** an active challenge
- **WHEN** the prospective user submits an incorrect code
- **THEN** the system returns a verification error, increments the failed-attempt count, and returns no registration proof

#### Scenario: Expired code

- **GIVEN** a code whose expiry time has passed
- **WHEN** the prospective user submits that code
- **THEN** the system rejects it and returns no registration proof

#### Scenario: Old code after resend

- **GIVEN** a newer code has been successfully requested for the same email
- **WHEN** the prospective user submits an older code
- **THEN** the system rejects the older code and returns no registration proof

#### Scenario: Code submitted after successful verification

- **GIVEN** a code has already produced a registration proof
- **WHEN** any client submits that code again
- **THEN** the system rejects it and returns no additional registration proof

### Requirement: Guessing protection

The system MUST bound verification attempts for each challenge and MUST lock the challenge after the configured failed-attempt budget is exhausted.

#### Scenario: Failed-attempt budget exhausted

- **GIVEN** a challenge has reached the maximum number of incorrect attempts
- **WHEN** any code is submitted for that challenge
- **THEN** the system rejects the attempt and requires a new code request

### Requirement: Verification request abuse limits

The system MUST enforce a resend cooldown plus rolling request limits by normalized email and source IP using persisted request history.

#### Scenario: Rapid resend for the same email

- **GIVEN** a code was recently requested for an email inside the resend cooldown
- **WHEN** another code is requested for that email
- **THEN** the system rejects the request with a retryable rate-limit response and does not send another message

#### Scenario: Email hourly limit exceeded

- **GIVEN** an email has reached its configured rolling request limit
- **WHEN** another code is requested within the same window
- **THEN** the system rejects the request with a rate-limit response and does not send another message

#### Scenario: IP hourly limit exceeded

- **GIVEN** a source IP has reached its configured rolling request limit across addresses
- **WHEN** another code is requested from that IP within the same window
- **THEN** the system rejects the request with a rate-limit response and does not send another message

### Requirement: Verified registration only

The system MUST create an account only when the registration request includes an unexpired, unconsumed registration proof issued for the same normalized email, and MUST atomically consume the proof with account creation.

#### Scenario: Registration with valid proof

- **GIVEN** a verified email and a valid one-time registration proof for it
- **WHEN** the prospective user submits valid username and password data with that proof
- **THEN** the system creates exactly one account, consumes the proof, and returns an authenticated session

#### Scenario: Registration without verification

- **GIVEN** no registration proof is supplied
- **WHEN** a client attempts to register
- **THEN** the system rejects the request and creates no account

#### Scenario: Proof belongs to another email

- **GIVEN** a registration proof was issued for one normalized email
- **WHEN** a client attempts to register a different email with that proof
- **THEN** the system rejects the request and creates no account

#### Scenario: Expired registration proof

- **GIVEN** a registration proof has expired
- **WHEN** a client attempts to register with it
- **THEN** the system rejects the request and creates no account

#### Scenario: Registration proof reused

- **GIVEN** a registration proof has already been consumed by successful registration
- **WHEN** any client attempts to register with it again
- **THEN** the system rejects the request and creates no second account

#### Scenario: Email becomes registered before completion

- **GIVEN** the verified email already belongs to an account when final registration is submitted
- **WHEN** a client submits the otherwise valid registration request
- **THEN** the system rejects registration without consuming credentials into a new user record

### Requirement: Registration user experience

The registration page SHALL guide a user through code request, code entry, and account creation while preventing stale verification state when the email changes.

#### Scenario: User completes the browser flow

- **GIVEN** valid account details and access to the supplied email inbox
- **WHEN** the user requests a code and submits the correct code
- **THEN** the page verifies the email, completes registration, stores the returned session, and routes to the authenticated application

#### Scenario: User changes email after requesting a code

- **GIVEN** the page has an active code-entry state
- **WHEN** the user changes the email address
- **THEN** the page discards the prior code/proof state and requires verification of the new address

#### Scenario: Request or verification fails

- **GIVEN** the user is in the registration flow
- **WHEN** a network, delivery, validation, expiry, or rate-limit error occurs
- **THEN** the page stops loading, preserves safe user-entered account data, displays an actionable error, and allows an appropriate retry

## Acceptance Criteria

- [ ] A user cannot create an account without first verifying the same email.
- [ ] A correct current code permits registration to continue.
- [ ] An incorrect code returns an error and consumes an attempt.
- [ ] An expired code cannot be used.
- [ ] A code and its registration proof can each succeed only once.
- [ ] A newer request makes old codes unusable.
- [ ] Rapid and excessive requests from the same email or IP are limited.
- [ ] Exhaustive wrong-code attempts lock the challenge.
- [ ] An already registered email receives no code and cannot create a duplicate account.
- [ ] Email provider failure or network timeout leaves no usable challenge and returns a recoverable error.
- [ ] Verification codes are absent from API responses, persistent plaintext fields, and logs.
- [ ] The browser flow exposes loading, resend, success, and recoverable error states.

## Edge Cases

- Concurrent requests for the same email; only the latest committed challenge remains valid.
- A previous code arrives after a resend and is submitted before the newer email arrives.
- Mixed-case or surrounding-whitespace variants of the same email.
- Correct code submitted on the final allowed attempt.
- Code expires between request validation and submission.
- Proof expires between code verification and final registration.
- Username or email becomes unavailable after code verification.
- Client retries final registration after a lost successful response.
- Email provider rejects credentials, recipient, TLS negotiation, or times out.
- Missing client IP information is grouped into a stable unknown-source bucket rather than bypassing limits.
- Malicious clients bypass frontend validation and call APIs directly.

