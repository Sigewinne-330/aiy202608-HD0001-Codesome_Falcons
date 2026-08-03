## Context

See `proposal.md` for motivation and the four delta specs for observable behavior. The authoritative user model is `models.user.User`/`users`; current calendar data comes from `tasks` and `deadlines`; current AI chat persistence is `chat_history`. A second legacy user/conversation/chat model exists but is not part of current auth or chat and must not be used.

The browser currently derives a seven-day popover from `/api/tasks` and `/api/deadlines/upcoming`, while `SettingsDialog.vue` stores language and connection values only in local storage. The backend has provider-failover LLM clients and six task CRUD tools, but no reminder-specific prompt, no deadline list tool, no active token/quota ledger, and no safe read-only tool registry. SMTP transport exists behind a verification-code-specific sender interface. APScheduler is installed but no job is registered.

## Goals / Non-Goals

**Goals:**

- Put selection, generation, channel fan-out, retries, and audit behind one testable backend orchestration boundary.
- Keep the Reminder Agent separate from the main agent while safely reusing provider clients and selected read-only data access.
- Make duplicate external sends impossible under normal retry, restart, and multi-instance races.
- Keep automated acceptance independent of external providers while requiring separate real LLM and QQ Mail smoke evidence before the change is called fully accepted.
- Preserve a clean extension point for later channels, UI settings, private cards, and quota plans.

**Non-Goals:**

- No frontend implementation in this change; existing frontend behavior is not rewritten.
- No main-agent redesign, no mutable Reminder Agent tools, and no full SillyTavern runtime/importer.
- No distributed task queue dependency for the MVP; the database remains the durable coordination mechanism.
- No hard-coded paid-plan token amount. Usage is recorded through a shared interface and enforcement is unlimited until a real quota policy is configured.

## Architecture

```text
standalone worker / protected dry-run API
                 |
                 v
       ReminderOrchestrator
       |         |          |
       |         |          +--> final eligibility check
       |         +--> occurrence/digest claim (DB unique keys)
       +--> calendar candidate query (tasks + children + deadlines)
                 |
                 v
          ReminderTextAgent
      dedicated prompt + read-only tools
      role card + language + usage ledger
                 |
       validated or fallback envelope
                 |
                 v
          ChannelRegistry
        /                  \
ChatReminderChannel   EmailReminderChannel   ...future adapters
        |                  |
  chat_history       generic SMTP transport
        \                  /
         per-channel delivery audit
```

The worker calls a pure orchestration service with an explicit `now_utc`, making boundary tests deterministic. A daemon wrapper may use APScheduler to tick every minute; a `--once` command supports cron, containers, and tests. Production starts this worker separately from Uvicorn. The orchestrator processes users whose local time has crossed 09:00 and whose local-day digest has not been finalized; same-day catch-up is allowed, prior-day backfill is not.

## Data Model

### `reminder_role_cards`

- `id`, stable unique `slug`, localized `name`
- `description`, `personality`, `speaking_style`, `system_prompt`
- JSON `example_messages` and JSON `extensions`
- nullable `owner_user_id` reserved for future private cards; MVP rows are global
- `creator`, `version`, `is_active`, `is_builtin`, timestamps
- optional `created_by_user_id` for administrator audit

Seed by stable slug, idempotently:

1. `friendly-warm-guy` / 友好暖男 — default, warm, respectful, concise, encouraging without pressure.
2. `tech-geek` / 技术宅 — precise, technical metaphors, compact status-oriented wording.
3. `sweet-high-school-girl` / 高中甜美少女 — cheerful, sweet, school-peer-like, non-romantic and non-sexualized.

The internal format intentionally maps conceptually to Character Card V2 fields such as name, description, personality, system prompt, and examples, but does not parse PNGs, execute macros, or import lorebooks.

### `reminder_preferences`

- unique `user_id` FK to `users`
- `enabled`, `language`, `timezone`
- JSON `cadence_offsets` with default `[2, 1, 0, -1, -3, -7]`; positive means days before due date
- `email_enabled`, `chat_enabled`
- nullable selected `role_card_id`
- timestamps and optimistic update/version field if needed

Read-through defaults avoid a mandatory backfill, while first update or first successful reminder materializes a row safely. Validate timezone against the runtime IANA database and normalize language as BCP 47; explicitly acceptance-test `zh-CN` and `en-US`.

### `reminder_occurrences`

- `id`, `user_id`, polymorphic `item_type` (`task` or `deadline`), `item_id`
- immutable `due_date`, `cadence_offset`, `local_scheduled_date`
- `state` (`claimed`, `included`, `cancelled`), cancellation reason, timestamps
- unique `(user_id, item_type, item_id, due_date, cadence_offset)`

No polymorphic database FK is possible; ownership and existence are revalidated through authoritative models. Rescheduling creates a new due-date identity and marks obsolete pending rows cancelled without deleting history.

### `reminder_digests`

- `id`, `user_id`, `local_date`, `timezone`, `language`, nullable `role_card_id`
- generated/fallback `subject`, one-to-two-sentence `framing_text`
- JSON immutable `item_snapshot`, deterministic `body_text`, `chat_url`
- `generation_mode` (`llm` or `template`), generation attempts, state, timestamps
- unique `(user_id, local_date)`

The item snapshot is the delivery source of truth after the final eligibility check. It contains only fields needed for audit and rendering, not credentials or arbitrary provider payloads.

### `reminder_deliveries`

- `id`, `digest_id`, `channel`, `status` (`pending`, `delivered`, `retryable`, `failed`, `skipped`)
- `attempt_count`, `next_attempt_at`, `last_error_code`, `delivered_at`, timestamps
- optional provider message identifier when safe
- unique `(digest_id, channel)`

Raw exception strings are not exposed through user APIs. Retry workers claim due delivery rows safely and reuse the immutable digest. Delivery additionally uses an internal `attempting` state with an opaque database lease token and start time committed before an external side effect. A fresh lease permits only its holder to execute the channel. If a worker later finds an abandoned email attempt whose provider outcome is unknowable, it records `delivery_outcome_unknown` and does not automatically resend; stale chat attempts can be recovered idempotently inside the database.

### `llm_usage_records`

- `id`, `user_id`, `purpose` (`chat`, `reminder`, or future purpose)
- provider, model, correlation identifier, related digest/message identifier
- nullable prompt, completion, and total token counts
- outcome and timestamp

Introduce a shared usage recorder at the LLM client boundary so reminder calls are not hidden from future quota aggregation. Existing interactive calls should migrate to the same recorder where provider usage is available. `LLMQuotaPolicy` defaults to unlimited because the repository has no authoritative subscription limits; if a configured policy denies a reminder request, delivery uses a template.

### `chat_history` extension

Add nullable JSON `metadata` with source, digest ID, role-card ID, and compact item references. Existing role/content/time response fields remain unchanged; history responses may add optional metadata that current Vue clients safely ignore. Clearing chat deletes messages but not reminder audit tables.

### Administrator identity

Add a server-authoritative `is_admin` boolean to the `users` table, default false and omitted from public mutation APIs. Administrative test fixtures can override authorization dependencies; production promotion is an explicit database/operator action, never inferred from email domain or request data.

## API Changes

All routes use the current JWT user dependency and Pydantic validation.

- `GET /api/reminders/preferences` — resolved current-user defaults.
- `PUT /api/reminders/preferences` — update enabled state, language, timezone, cadence, channels, and selected card; only supported cadence offsets are accepted in this MVP.
- `GET /api/reminders/history` — paginated current-user digest and sanitized delivery summaries.
- `GET /api/reminder-role-cards` — active cards visible to the current user.
- `GET /api/reminder-role-cards/{id}` — compact card details.
- `POST /api/admin/reminder-role-cards` — create a global card.
- `PATCH /api/admin/reminder-role-cards/{id}` — edit or activate/deactivate a card while protecting built-in slug identity.
- `POST /api/admin/reminders/run` — explicit-time dry run by default; actual delivery requires `deliver=true`, remains idempotent, and is disabled for ordinary users.

No SMTP readiness fields or secrets are exposed publicly. A local/operator readiness command validates configuration presence and TLS-mode consistency without printing values.

## Component Changes

- **Models/bootstrap:** export new authoritative models, update manual MySQL bootstrap, and keep startup schema synchronization compatible with tests.
- **Candidate repository:** centralize the exact three-category query rather than relying on the current `list_tasks` behavior, whose default filtering/limit is unsuitable for scheduling.
- **Read-only tools:** derive a separate Reminder Agent tool schema and dispatcher for `list_tasks`, `list_subtasks`, and `list_deadlines`; wrappers enforce `user_id`, hard result limits, and no mutation.
- **LLM service:** expose a low-level completion entry that accepts an explicit system prompt, allowed tools, output limit, usage callback, and provider failover. The main `SYSTEM_PROMPT` and main tool loop are not used by reminder generation.
- **Renderer/validator:** validate generated subject/framing, then append the deterministic item list and configured `/chat` URL. Descriptions are delimited, truncated prompt data and are not copied wholesale into deterministic output.
- **Email:** introduce a generic message envelope/SMTP transport. Keep the existing verification sender API through an adapter so email verification behavior does not regress.
- **Channels:** adapters return normalized outcomes and never own scheduling or generation.
- **Worker:** standalone module supports `--once`; daemon mode uses the already-present APScheduler dependency and graceful shutdown.
- **Tests:** unit/service tests use SQLite-compatible constraints where possible and concurrency/integration tests cover the authoritative MySQL behavior where uniqueness semantics differ.

## Technical Decisions

### One deterministic digest plus LLM framing

The model writes only a clear subject and one or two framing sentences; backend rendering owns the item list. This preserves the user's brevity request without risking omissions when many items qualify. Alternative rejected: ask the LLM to fit every item into two sentences, because output completeness and idempotent retry content become unreliable.

### Scanner selects authoritative items before the agent

The worker queries all three categories directly; read tools are supplemental only. Alternative rejected: letting `list_tasks` drive scheduling, because it excludes deadlines, has a default limit, and model tool choice cannot define reliable delivery eligibility.

### Database uniqueness instead of an external queue

Occurrence/digest/delivery unique keys plus transactional claims provide sufficient MVP durability and multi-instance safety. Alternative deferred: Celery/Redis or a managed queue, which adds operational dependencies before throughput requires them.

### Dedicated worker instead of FastAPI startup job

Separating the process prevents Uvicorn worker count or development reload from multiplying schedules. The same service remains callable from a development scheduler and protected dry-run API.

### Compact internal cards with future mapping

Store only reminder-relevant fields and extension metadata. Alternative deferred: full Character Card V2/PNG import, whose embedded content, macros, lorebooks, file parsing, and trust model are disproportionate to a two-sentence reminder.

### Template after generation/quota failure, failure after transport exhaustion

Content fallback preserves reminder reliability when AI is unavailable. It is not used to mask SMTP failure because changing text cannot repair transport. Chat and email states remain independent.

## Security and Privacy Rules

- SMTP authorization codes, passwords, API keys, and received inbox contents are runtime secrets only. They must never be placed in `.env.example` values, tracked `.env` files, OpenSpec, fixtures, commands that echo environments, logs, reports, or API payloads.
- Every candidate query, supplemental tool, metadata resolution, history read, and administrator operation enforces the authoritative `users.id` boundary.
- Event fields and role cards are prompt data, not instructions. System constraints and tool allowlists are assembled outside those delimiters.
- Tool execution uses a name allowlist and separate dispatcher; sharing the mutable main-agent registry is prohibited.
- Logs use IDs, counts, status codes, provider labels, and timings. They do not log full prompts, descriptions, generated bodies, email addresses, exception secrets, or authorization headers.
- External URLs come from validated `APP_BASE_URL`; no event field can provide a delivery link.
- Administrator status is server-controlled and defaults false.

## Compatibility and Rollout

- New columns are nullable/defaulted so existing users and chat clients continue to work.
- Existing local-storage settings remain untouched until a future frontend change explicitly migrates them.
- Existing browser popover continues its current seven-day behavior; it is not evidence that backend reminders were delivered.
- Existing verification email endpoint retains its interface and tests while SMTP transport is generalized internally.
- The active email-verification acceptance change remains separate; this change does not claim that gate complete.

## External Provider Configuration and Acceptance

QQ Mail is configured through the existing provider-neutral SMTP variables with `smtp.qq.com`, the chosen supported TLS port/mode, account username/from address, and a runtime authorization code. Configuration values are supplied outside Git. Automated tests use a fake transport. Final acceptance performs one controlled send and observes inbox receipt, recording only timestamp, provider label, recipient domain if appropriate, stages, and result.

The real LLM gate similarly records provider/model labels, language/card scenario, output-contract result, and usage-record result without committing prompts that contain private task data.

## Risks / Trade-offs

- **[Database JSON and enum differences between SQLite and MySQL]** → keep portable serialization and run an actual-MySQL migration/idempotency gate.
- **[Worker outage misses a whole local day]** → same-day catch-up only and visible audit/health metrics; do not surprise users with stale historical emails.
- **[Large digest exceeds prompt or email size]** → query all eligible items, cap description context per item, paginate internal reads, and always render the complete deterministic compact list.
- **[Provider returns no token usage]** → record the attempt with nullable counts and never fabricate billing data.
- **[Generated character style becomes inappropriate]** → constrained seed text, output validation, safe neutral fallback, and administrator deactivation.
- **[QQ Mail accepts SMTP but inbox delivery is delayed/filtered]** → report provider submission separately from observed receipt and inspect provider/spam state without exposing inbox content.
- **[Real secret was shared outside the runtime secret store]** → rotate the authorization code before production use; repository history and artifacts remain secret-free.

## Migration Plan

1. Add schema/model changes with defaults and idempotent built-in role-card seeding.
2. Add preference/card APIs and authorization, then candidate/occurrence orchestration.
3. Add dedicated agent, usage recorder, deterministic renderer, and fake-provider tests.
4. Add chat/email channels, retry worker, standalone command, readiness checks, and documentation.
5. Run focused backend tests, existing email/auth/chat regressions, MySQL concurrency checks, frontend production build, and strict OpenSpec validation.
6. Configure LLM and QQ Mail secrets only in the local runtime, perform separate real-provider smoke gates, and record sanitized evidence.
7. Enable one production worker. Rollback by stopping the worker and disabling reminder preferences; additive tables/columns remain for audit and do not affect existing routes.

## Open Questions

None that change the accepted requirements or implementation approach. A future frontend change will decide settings UX, private-card creation, and visible quota-plan presentation.
