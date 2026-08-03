## Why

### Goal

Reliably remind each user about unfinished calendar work before, on, and after its due date through one localized, role-styled daily digest that is delivered to email and preserved in the in-app AI chat.

### Background

The current application calculates a seven-day reminder popover only in the browser. It has no persisted reminder preferences, timezone-aware scheduler, delivery audit, LLM usage accounting, role-card model, generic notification channel, or server-side chat synchronization. As a result, reminders disappear when the browser is closed and cannot be extended safely to email, SMS, or software connectors.

### User Story

As a student managing tasks, process subtasks, and deadlines, I want a concise reminder at 09:00 in my chosen timezone, written in my chosen language and preferred character style, so I can act before work becomes overdue and continue the discussion in the AI chat when I need details.

## What Changes

### Requirements

- Add a dedicated reminder worker that evaluates unfinished top-level todo tasks, process-task children, and deadline records at each user's local 09:00.
- Schedule one reminder occurrence at D-2, D-1, D0, D+1, D+3, and D+7 for each unchanged due date, with durable idempotency and cancellation when an item is completed, deleted, or rescheduled.
- Generate one daily per-user digest with a dedicated Reminder Agent, an independent system prompt, an allowlist of read-only task/deadline tools, localized 1–2 sentence framing, a clear generated subject, and a deterministic item list.
- Treat event descriptions as untrusted data that may inform the message but cannot override system, language, role-card, safety, or output constraints.
- Seed three compact global role cards: Friendly Warm Guy, Tech Geek, and Sweet High-School Girl; allow a user to select one default card while preserving user-language authority.
- Persist reminder preferences, occurrence/delivery state, chat linkage, role-card provenance, and LLM prompt/completion/total-token usage.
- Deliver the same digest independently through chat and email, retry transient LLM and email failures up to three times, use a deterministic text template after generation failure or unavailable quota, and retain auditable final outcomes.
- Add authenticated backend APIs for user preferences, card discovery/selection, and delivery history; add administrator-only card management and manual worker execution APIs.
- Include an absolute `${APP_BASE_URL}/chat` link so a recipient can continue in the existing AI chat.

### Scope

- Backend models, services, worker entry point, APIs, migrations/bootstrap SQL, tests, configuration documentation, and acceptance evidence.
- Email as the first external channel and existing `chat_history` as the in-app channel.
- Real LLM and QQ Mail SMTP smoke tests as final provider-backed acceptance gates, with all automated behavior also covered by fakes.
- Token usage recording for reminder generations; this change does not invent paid plan limits where none currently exist.

### Non-goals

- A new or modified frontend settings page, role-card editor, notification center, or calendar UI.
- SMS, WeChat, Slack, or other connector implementation; only the channel interface and persisted outcome model are prepared for them.
- User-created/private cards, event-specific card selection, SillyTavern PNG parsing, lorebooks, alternate greetings, or complete Character Card V2 import.
- Minute-level event times, quiet hours, arbitrary reminder schedules, or replacement of the existing main chat agent.
- Storing SMTP credentials, authorization codes, inbox contents, or other secrets in source control, OpenSpec artifacts, database rows, logs, or API responses.

## Capabilities

### New Capabilities

- `calendar-reminder-scheduling`: Timezone-aware eligibility, occurrence cadence, cancellation, idempotency, concurrency, and worker behavior for all calendar-backed item types.
- `reminder-content-generation`: Dedicated Reminder Agent behavior, role-card styling, localization, prompt-injection boundaries, deterministic item lists and fallbacks, and LLM usage accounting.
- `reminder-delivery`: Extensible per-channel delivery, daily digest fan-out, email and chat behavior, retry/audit semantics, deep-link metadata, and provider-backed acceptance.
- `reminder-preferences-and-role-cards`: Persisted user defaults, authenticated APIs, administrator card lifecycle, initial compact role cards, and future compatibility boundaries.

### Modified Capabilities

- None. Existing email verification and browser reminder behavior remain unchanged by this backend-only change.

## Impact

- **Backend models and schema:** new reminder preference, role-card, reminder occurrence/digest, channel delivery, and LLM usage records; optional reminder metadata on authoritative `chat_history`.
- **Services:** dedicated reminder selection/orchestration, agent, renderer, usage recorder, channel registry, generic SMTP transport, and worker lock/idempotency services.
- **APIs:** new authenticated reminder/card endpoints plus protected administrator/test operations; existing chat history remains backward-compatible.
- **Runtime:** a standalone reminder worker or scheduled command is the production path; any in-process scheduler is development-only and disabled by default.
- **Configuration:** application base URL, administrator policy, worker timing/lease settings, LLM quota integration, and provider-neutral SMTP environment variables.
- **External systems:** configured LLM provider and QQ Mail SMTP are required for final real-provider smoke tests, but not for deterministic automated tests.
- **Security:** user ownership is enforced on all item/tool queries; descriptions are untrusted; tool calls are read-only; secrets and message bodies are excluded from operational logs.
