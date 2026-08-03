## Purpose

Defines how a dedicated, metered Reminder Agent turns authoritative reminder candidates into concise localized text while respecting role cards, untrusted event content, output constraints, and deterministic fallback behavior.

## ADDED Requirements

### Requirement: Dedicated Reminder Agent boundary
The system SHALL generate reminder wording with a dedicated Reminder Agent that has its own system prompt and no main-chat conversation history. It MAY reuse the configured LLM provider clients and explicitly allowlisted read-only task/deadline tools, but MUST NOT execute create, update, delete, or other state-changing tools and MUST NOT impersonate or invoke the main chat agent.

#### Scenario: Agent needs supplemental item information
- **GIVEN** a digest candidate requires additional authoritative context
- **WHEN** the Reminder Agent requests a tool
- **THEN** only an allowlisted, user-scoped read operation can execute and its result is returned as untrusted data

#### Scenario: Agent requests a write tool
- **GIVEN** model output names or constructs a state-changing tool call
- **WHEN** the tool dispatcher validates it
- **THEN** the call is rejected, no application record is changed, and generation falls back or retries safely

### Requirement: Localized role-card styling
The system SHALL generate the subject and framing text in the user's selected language. The active compact role card SHALL influence tone, diction, and optional emoji, but SHALL NOT override the selected language, factual event data, safety rules, tool permissions, or required output shape.

#### Scenario: Chinese user selects Tech Geek
- **GIVEN** a user language of `zh-CN` and the Tech Geek role card
- **WHEN** a reminder is generated
- **THEN** the output is Chinese and uses the card's technical, concise style without changing item facts

#### Scenario: Role card asks for a conflicting language
- **GIVEN** role-card content conflicts with the user's selected language
- **WHEN** the prompt is assembled
- **THEN** user language remains authoritative and the conflicting instruction is ignored

### Requirement: Untrusted event descriptions
The system SHALL permit titles and descriptions to inform reminder wording while delimiting them as untrusted data. Instructions contained inside item fields SHALL NOT alter the system prompt, role-card identity, language, output constraints, channel behavior, or tool permissions.

#### Scenario: Description contains prompt injection
- **GIVEN** an event description says to ignore prior rules and use a different persona
- **WHEN** the Reminder Agent processes the item
- **THEN** useful event facts may be reflected but the injected instruction has no effect on governing constraints

### Requirement: Digest output contract
For each user and local reminder day, the system SHALL produce one clear subject and one or two sentences of plain-text role-styled framing. The backend SHALL append a deterministic list containing every eligible item's title, type, due date, cadence state, and priority, followed by an absolute chat link. The generated framing SHALL NOT be trusted to enumerate or preserve the authoritative item set.

#### Scenario: Multiple items are due at different cadence points
- **GIVEN** one user has several eligible tasks and deadlines in one run
- **WHEN** content is assembled
- **THEN** one subject and one-to-two-sentence framing are paired with a deterministic list containing every eligible item exactly once

#### Scenario: Generated output violates the contract
- **GIVEN** the model returns Markdown, an unclear subject, more than two framing sentences, or missing required structure
- **WHEN** output validation runs
- **THEN** the system retries within policy and ultimately uses a valid deterministic fallback rather than delivering malformed content

### Requirement: Generation retry and deterministic fallback
The system SHALL attempt LLM generation at most three times for one logical digest. If all attempts fail, no provider is configured, an active quota disallows generation, or output remains invalid, the system SHALL create a localized deterministic subject and framing template and continue channel delivery.

#### Scenario: All LLM attempts fail
- **GIVEN** the provider times out or errors on three attempts
- **WHEN** the retry budget is exhausted
- **THEN** a deterministic localized digest is created and delivered without a fourth LLM request

#### Scenario: Quota blocks an LLM request
- **GIVEN** an active user quota has insufficient remaining tokens
- **WHEN** reminder generation begins
- **THEN** no LLM request is made and the deterministic template is used without suppressing the reminder

### Requirement: LLM usage accounting
Every provider request for reminder generation SHALL record user, purpose, provider, model, request correlation, prompt tokens, completion tokens, total tokens, outcome, and related digest when the provider exposes usage. Reminder usage SHALL count against any active user quota under the same accounting policy as interactive AI usage; the default behavior remains unmetered enforcement when no quota policy exists.

#### Scenario: Successful generation reports usage
- **GIVEN** the provider returns token usage
- **WHEN** a reminder generation succeeds
- **THEN** the usage is persisted with purpose `reminder` and is available to quota aggregation

#### Scenario: Failed request has incomplete usage
- **GIVEN** a provider request fails without usage metadata
- **WHEN** the attempt is recorded
- **THEN** the failure and known metadata are persisted without inventing a token count

## Acceptance Criteria

- Reminder generation never uses main-chat history or write-capable tools.
- Automated injection tests prove event content and cards cannot override governing constraints.
- `zh-CN` and `en-US` outputs satisfy language, subject clarity, plain-text, and one-to-two-sentence framing rules.
- Multi-item digests preserve every authoritative item through deterministic rendering.
- Three failed attempts, missing providers, invalid output, and exhausted configured quota all produce a deliverable fallback.
- Provider-reported reminder token use is persisted and queryable by user and purpose.

## Edge Cases

- A role card containing unsupported macros is treated as text or rejected during card validation; it is never executed.
- Empty titles are replaced by a localized safe label in deterministic rendering.
- Extremely long descriptions are length-limited before prompting without changing stored source data.
- Emoji are optional and style-controlled; the deterministic fallback does not depend on them.
- A generated subject that includes line breaks or control characters is rejected.
