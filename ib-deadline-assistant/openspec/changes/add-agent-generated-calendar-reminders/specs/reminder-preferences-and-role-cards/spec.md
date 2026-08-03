## Purpose

Defines persistent backend preferences and compact character-style cards so reminder language, timezone, cadence, channels, and tone remain consistent without requiring a frontend settings implementation.

## ADDED Requirements

### Requirement: Persisted reminder preferences
The system SHALL maintain one reminder preference record per authoritative user with enabled state, valid IANA timezone, BCP 47 language, configured cadence offsets, email enabled state, chat enabled state, and selected active role card. Missing preferences SHALL resolve to enabled reminders, `Asia/Shanghai`, `zh-CN`, D-2/D-1/D0/D+1/D+3/D+7, enabled chat, and enabled email.

#### Scenario: Existing user has no preference row
- **GIVEN** an existing user without reminder preferences
- **WHEN** preferences are read or reminder scheduling evaluates the user
- **THEN** the documented defaults are applied consistently and can be persisted without duplicate rows

#### Scenario: User submits invalid timezone or language
- **GIVEN** an authenticated user supplies an invalid timezone or malformed language identifier
- **WHEN** preferences are updated
- **THEN** validation rejects the request and keeps the previous settings

### Requirement: User preference APIs
An authenticated user SHALL be able to read and update only their own reminder preferences, choose an active global role card, and read their own delivery history. Ordinary users SHALL NOT create, modify, activate, or deactivate global role cards.

#### Scenario: User selects an active card
- **GIVEN** an authenticated user and an active global role card
- **WHEN** the user updates their selected card
- **THEN** subsequent digests use that card and earlier audit records retain their original card provenance

#### Scenario: User selects an inactive or missing card
- **GIVEN** a role-card identifier that is inactive, missing, or inaccessible
- **WHEN** a user attempts selection
- **THEN** the request is rejected and the previous card remains selected

### Requirement: Compact role-card format
Each role card SHALL support a stable slug, localized display name, description, personality, speaking style, system instructions, example messages, creator, version, active state, built-in state, and extensible metadata. Card fields SHALL be length-limited and validated as prompt data. Full SillyTavern V2 JSON or PNG import SHALL NOT be required in this change.

#### Scenario: Administrator creates a valid compact card
- **GIVEN** an administrator submits valid compact-card fields
- **WHEN** the card is created
- **THEN** it becomes discoverable according to its active state and can be selected without code changes

#### Scenario: Card contains unsupported executable content
- **GIVEN** card metadata includes executable markup, an oversized prompt, or an attempt to grant tool permissions
- **WHEN** validation runs
- **THEN** the unsafe or invalid card is rejected and no permissions are changed

### Requirement: Built-in role cards
The system SHALL idempotently seed exactly three initial global compact cards: `friendly-warm-guy` (友好暖男), `tech-geek` (技术宅), and `sweet-high-school-girl` (高中甜美少女). The first SHALL be the default. The Sweet High-School Girl card SHALL be cheerful, sweet, school-peer-like, non-romantic, and non-sexualized.

#### Scenario: Fresh database is initialized
- **GIVEN** no role-card records exist
- **WHEN** database initialization or seed synchronization runs
- **THEN** the three stable cards are created once and Friendly Warm Guy is available as the default

#### Scenario: Initialization runs repeatedly
- **GIVEN** the built-in cards already exist
- **WHEN** seed synchronization runs again
- **THEN** it does not duplicate cards or overwrite administrator-controlled active state unexpectedly

### Requirement: Administrator role-card lifecycle
Only a server-authorized administrator SHALL create, update, or deactivate global role cards. Built-in cards SHALL retain stable slugs and audit provenance. Deactivating a selected card SHALL cause future generation to use the default active card while preserving the user's selection reference for recovery or migration.

#### Scenario: Non-administrator attempts card administration
- **GIVEN** an ordinary authenticated user
- **WHEN** the user calls a global role-card administration operation
- **THEN** the system returns a forbidden response and no card changes

#### Scenario: Selected card is deactivated
- **GIVEN** users have selected a card that an administrator deactivates
- **WHEN** future reminders are generated
- **THEN** the active default card is used and the fallback is visible in audit metadata

### Requirement: Future private-card compatibility
The persisted model SHALL reserve ownership and visibility semantics that can support user-created private cards later, but all user create/import operations SHALL remain unavailable in this change.

#### Scenario: User attempts to create a private card
- **GIVEN** the current backend release
- **WHEN** an ordinary user attempts an unimplemented private-card creation operation
- **THEN** no private card is created and the supported API surface does not advertise the operation

## Acceptance Criteria

- Preference defaults and updates are persisted and user-isolated.
- IANA timezone and BCP 47 language validation have positive and negative tests.
- The three required cards seed idempotently with Friendly Warm Guy as default.
- Card selection changes future style while language remains authoritative.
- Administrator authorization protects global card mutations and manual worker controls.
- No frontend page or complete SillyTavern importer is introduced.

## Edge Cases

- If every card is inactive due to administrative error, deterministic neutral fallback instructions are used and delivery continues.
- Concurrent first access creates at most one preference row per user.
- Deleting users cascades or anonymizes reminder preference and usage data according to existing account-deletion behavior.
- Updating card text does not rewrite historical digest snapshots.
- Future user-owned cards must not become globally visible merely because the ownership field is null or malformed.
