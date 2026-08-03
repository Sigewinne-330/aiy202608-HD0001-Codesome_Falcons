## Purpose

Defines when unfinished calendar-backed work becomes eligible for reminders and guarantees timezone-correct, durable, duplicate-free processing across retries, restarts, and concurrent workers.

## ADDED Requirements

### Requirement: Eligible calendar item types
The system SHALL evaluate unfinished top-level todo tasks, unfinished children of process tasks, and unfinished deadline records as reminder candidates. It SHALL exclude process parent containers, records without a due date, and records whose authoritative status is complete.

#### Scenario: All supported unfinished types are selected
- **GIVEN** a user has an unfinished top-level todo, an unfinished process child, and an unfinished deadline with eligible due dates
- **WHEN** the reminder worker evaluates that user
- **THEN** all three records are candidates and the process parent itself is not a candidate

#### Scenario: Completed and undated records are excluded
- **GIVEN** a calendar record is complete or has no due date
- **WHEN** the worker evaluates reminder candidates
- **THEN** no reminder occurrence is created for that record

### Requirement: Timezone-aware 09:00 schedule
The system SHALL evaluate and schedule reminders according to the user's valid IANA timezone at 09:00 local time. Existing users without a persisted preference SHALL use `Asia/Shanghai`, and invalid timezone input SHALL be rejected rather than silently interpreted.

#### Scenario: Users in different timezones receive local-time processing
- **GIVEN** two users have different valid timezones
- **WHEN** each user's local clock reaches 09:00
- **THEN** each user's eligible reminders are processed at the corresponding UTC instant

#### Scenario: Worker restarts near the schedule
- **GIVEN** the worker is unavailable at exactly 09:00 and resumes within the same local day
- **WHEN** it performs its next catch-up scan
- **THEN** it processes the unsent local-day digest once without shifting the user's configured schedule

### Requirement: Reminder cadence
For each unchanged item due date, the system SHALL create at most one occurrence at D-2, D-1, D0, D+1, D+3, and D+7, where D0 is the due date in the user's timezone. It SHALL not generate further overdue occurrences after D+7 under this change.

#### Scenario: Item remains unfinished through D+7
- **GIVEN** an eligible item remains unfinished and keeps the same due date
- **WHEN** the worker runs on every configured cadence date
- **THEN** the item is included once at each of D-2, D-1, D0, D+1, D+3, and D+7 and on no other date

#### Scenario: Item is created inside the reminder window
- **GIVEN** an unfinished item is created after one or more cadence dates have passed
- **WHEN** the next configured 09:00 occurrence date is evaluated
- **THEN** the item is included for that current cadence and missed historical occurrences are not backfilled

### Requirement: Completion, deletion, and rescheduling
The system SHALL re-check authoritative item state before generation and again before external delivery. It SHALL cancel pending work for completed or deleted items. A due-date change SHALL start a new cadence identity while preserving old occurrences as audit history and preventing obsolete occurrences from delivery.

#### Scenario: Item completes before delivery
- **GIVEN** an occurrence was selected and the item becomes complete before delivery
- **WHEN** the worker performs its final eligibility check
- **THEN** the occurrence is cancelled and omitted from the outgoing digest

#### Scenario: Due date changes
- **GIVEN** an item already has occurrence history for one due date
- **WHEN** the due date is changed and the new date reaches a cadence point
- **THEN** the new date can produce its own occurrence and the old date cannot cause another delivery

### Requirement: Durable idempotency and concurrency safety
The system MUST enforce a durable uniqueness boundary for user, item type, item identifier, due date, and cadence offset. Repeated scans, process restarts, retries, manual execution, and concurrent workers SHALL not create duplicate occurrences or duplicate channel deliveries.

#### Scenario: Same window is scanned repeatedly
- **GIVEN** one eligible item and an already-created occurrence for the current cadence
- **WHEN** the scan runs again
- **THEN** it reuses or skips the existing occurrence and does not deliver that occurrence twice through any channel

#### Scenario: Two workers race
- **GIVEN** two workers evaluate the same user and cadence concurrently
- **WHEN** both attempt to claim the same work
- **THEN** database-backed uniqueness or leasing permits only one logical digest and one delivery per enabled channel

### Requirement: Standalone worker operation
Production reminder processing SHALL run through a standalone worker or one-shot scheduled command, independent of FastAPI web process count. A development-only in-process scheduler MAY invoke the same orchestration service but SHALL be disabled by default.

#### Scenario: Multiple web workers are deployed
- **GIVEN** the API runs in more than one process
- **WHEN** reminder processing is enabled through the production worker
- **THEN** web process count does not multiply reminder execution

## Acceptance Criteria

- All three supported calendar record categories are selected with correct unfinished-state filtering.
- D-2, D-1, D0, D+1, D+3, and D+7 boundaries pass in at least two timezones and across a daylight-saving transition timezone.
- Completion, deletion, and due-date changes suppress obsolete deliveries.
- Repeated and concurrent runs produce no duplicate occurrence, digest, chat message, or email delivery.
- Production startup documentation uses the standalone worker path.

## Edge Cases

- An invalid or removed timezone is rejected on write; legacy missing data falls back to `Asia/Shanghai`.
- A worker outage that spans an entire local day does not send historical cadence occurrences on later days.
- A task marked `overdue` remains unfinished and can receive configured overdue occurrences.
- An item deleted between selection and final re-check is cancelled without treating the run as a worker failure.
- More than one eligible item for a user on the same day is aggregated by the delivery capability rather than scheduled as separate daily messages.
