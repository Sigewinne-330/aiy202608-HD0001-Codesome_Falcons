## Purpose

Defines reliable, auditable fan-out of a daily reminder digest to in-app chat and email through independent channels that can later be extended to SMS and software connectors.

## ADDED Requirements

### Requirement: One daily digest per user
The system SHALL aggregate all of a user's eligible occurrences for one local date into one logical digest and SHALL attempt each enabled channel once for that digest, subject to its retry policy. Channel retries SHALL reuse the persisted content and SHALL NOT regenerate wording or create another logical digest.

#### Scenario: User has multiple eligible items
- **GIVEN** several tasks and deadlines are eligible for one user on the same local date
- **WHEN** delivery orchestration runs
- **THEN** one logical digest containing all items is offered once to each enabled channel

#### Scenario: Email retry occurs
- **GIVEN** a persisted digest whose first email attempt failed transiently
- **WHEN** the email retry runs
- **THEN** it sends the same subject and body without another LLM generation or duplicate chat message

### Requirement: Independent channel outcomes
Chat and email delivery SHALL have independent enabled states, attempts, statuses, timestamps, and sanitized error codes. Failure or disablement of one channel SHALL NOT prevent another enabled channel from completing.

#### Scenario: SMTP is unavailable
- **GIVEN** chat and email are enabled and SMTP is unavailable
- **WHEN** the digest is delivered
- **THEN** the chat message is persisted, email follows its retry policy, and the digest records the outcomes independently

#### Scenario: Email is disabled
- **GIVEN** chat is enabled and email is disabled in user preferences
- **WHEN** a digest is ready
- **THEN** chat delivery proceeds and email is recorded as skipped without contacting SMTP

### Requirement: In-app chat synchronization
Chat delivery SHALL append one `assistant` message to the authoritative current-user chat history. The message SHALL contain the digest and chat link and SHALL retain machine-readable reminder source, digest identifier, item references, and role-card identifier so later chat requests can recover originating context without exposing another user's data.

#### Scenario: User opens chat after receiving a reminder
- **GIVEN** chat delivery succeeded
- **WHEN** the user loads existing chat history
- **THEN** the digest appears as an assistant message without requiring a new frontend page

#### Scenario: User asks for details
- **GIVEN** the latest reminder message links to one or more source items
- **WHEN** the authenticated user asks the main chat agent for more detail
- **THEN** the system can resolve only that user's referenced items and use them as context

#### Scenario: User clears chat history
- **GIVEN** reminder messages and durable delivery audit records exist
- **WHEN** the user clears chat history
- **THEN** visible reminder messages are deleted with other chat messages while occurrence and delivery audit records remain and do not cause redelivery

### Requirement: Email delivery
Email delivery SHALL send one clear subject and plain-text digest body to the authenticated account email through provider-neutral SMTP configuration. The body SHALL include the absolute `${APP_BASE_URL}/chat` link. SMTP credentials SHALL be supplied only through runtime secret configuration and SHALL never appear in source, artifacts, database rows, logs, or API responses.

#### Scenario: SMTP accepts the digest
- **GIVEN** valid SMTP runtime configuration and an eligible recipient
- **WHEN** email delivery executes
- **THEN** one message is submitted and the delivery record stores success metadata without storing credentials

#### Scenario: SMTP configuration is missing
- **GIVEN** no valid SMTP configuration
- **WHEN** email delivery executes
- **THEN** email records a recoverable configuration failure, chat remains independent, and no secret-like value is logged

### Requirement: Delivery retry policy
Each transient email delivery SHALL be attempted no more than three times with bounded backoff. Permanent configuration, address, or authentication failures MAY stop earlier. After exhaustion, the delivery SHALL remain failed and visible in audit history; replacing content with a deterministic template SHALL NOT be treated as a remedy for transport failure.

#### Scenario: Third email attempt fails
- **GIVEN** the same email delivery has failed transiently three times
- **WHEN** retry evaluation runs again
- **THEN** no fourth automatic SMTP attempt occurs and the final failed state remains auditable

#### Scenario: SMTP authentication is rejected
- **GIVEN** the provider rejects authentication
- **WHEN** the email attempt fails
- **THEN** the error is sanitized, no authorization credential is persisted or returned, and chat delivery remains unaffected

### Requirement: Extensible channel contract
Every channel SHALL consume the same immutable digest envelope and return a normalized delivered, failed, retryable, or skipped outcome. Adding a future channel SHALL not require changing scheduling, generation, occurrence identity, or existing channel semantics.

#### Scenario: Future connector is registered
- **GIVEN** a new channel adapter follows the channel contract
- **WHEN** it is enabled for a user
- **THEN** it receives the existing digest envelope and records an independent delivery outcome

### Requirement: Protected execution and delivery history
Users SHALL be able to read only their own reminder delivery history. Manual worker execution and global/card administration SHALL require server-authoritative administrator authorization; an ordinary authenticated user SHALL receive a forbidden response.

#### Scenario: Ordinary user manually triggers delivery
- **GIVEN** a non-administrator is authenticated
- **WHEN** the user calls the manual worker endpoint
- **THEN** the system returns a forbidden response and creates no occurrence or delivery

#### Scenario: Administrator performs a dry run
- **GIVEN** an administrator requests a non-delivering preview for a specified evaluation time
- **WHEN** the operation executes
- **THEN** candidate counts and sanitized outcomes are returned without contacting external channels or bypassing user ownership

### Requirement: Layered acceptance evidence
Automated tests SHALL use fake LLM and fake channel implementations. Final provider-backed acceptance SHALL separately prove one real LLM generation and one authorized QQ Mail SMTP inbox delivery without recording credentials, full message contents, or private inbox data in the repository.

#### Scenario: Automated suite passes without external providers
- **GIVEN** deterministic fake providers
- **WHEN** the backend suite runs
- **THEN** scheduling, content, retry, idempotency, chat, and channel behavior are verified without network access

#### Scenario: Real SMTP gate lacks runtime credentials
- **GIVEN** all automated tests pass but authorized SMTP runtime secrets are absent
- **WHEN** final acceptance is assessed
- **THEN** automated gates may pass but real-provider end-to-end status remains explicitly blocked or not run

## Acceptance Criteria

- Multi-item days create one digest, one chat message, and at most one successful email per user.
- Channel failure isolation and three-attempt email exhaustion are covered by automated tests.
- Chat history remains backward-compatible and reminder source metadata remains user-scoped.
- No SMTP or LLM credential appears in tracked files, database fixtures, logs, test output, or acceptance reports.
- Fake-provider gates and real-provider gates are reported separately and truthfully.

## Edge Cases

- An email provider may accept SMTP while the message is delayed or filtered; submission and observed inbox receipt are separate acceptance observations.
- An invalid application base URL blocks or falls back to a safe configured link before external delivery rather than emitting an unsafe URL.
- A digest with no remaining eligible items after the final state check is cancelled and not delivered.
- A fresh channel-attempt lease is left to its current worker; an interrupted SMTP attempt whose lease becomes stale and whose provider outcome is unknowable is not automatically resent, but is surfaced as `delivery_outcome_unknown` to avoid duplicate email.
- Chat persistence failure does not erase a successful email outcome, but remains independently retryable where safe.
- Delivery history exposes sanitized codes and timestamps, not provider credentials or raw exception traces.
