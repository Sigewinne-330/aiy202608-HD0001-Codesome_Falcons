# Reminder Backend and Future Frontend Handoff

## Runtime architecture

- FastAPI serves preferences, role-card discovery, delivery history, and protected administrator operations.
- `backend/reminder_worker.py` is the production scheduling process. Do not start an APScheduler job inside each Uvicorn worker.
- The worker evaluates each user after that user's local `daily_dispatch_time` (default `09:00`), creates durable occurrence/digest claims, calls the dedicated Reminder Agent for daily digest text, then fans out the immutable digest to chat and email.
- Ordinary tasks with a concrete DateTime deadline additionally use `default_task_reminder_offsets_minutes` (default `[5, 1440]`). A task's `reminder_offsets_minutes` of `null` inherits the user setting and `[]` opts out. These immediate notifications have independent identity and delivery tables; date-only Deadline records remain daily-digest-only.
- `backend/run_timed_reminder_acceptance.py --user-id <id>` is the controlled automatic-worker gate. It uses the production `run_once` tick path, waits for the near-term daily dispatch, then creates the 5-minute and 1-day relative tasks. It restores the selected user's preference and deletes only its synthetic tasks. The command emits sanitized channel statuses and never calls the manual admin-run endpoint.
- Email and chat retain independent status and retry audit. SMS and software connectors should implement the channel protocol rather than call scheduling or the LLM directly.
- The selected `role_card_id` is shared by reminders and the interactive main Agent. Main chat resolves it once at request start and applies a bounded style-only projection to synchronous, streaming, tool and image paths. It does not add a second LLM call or change the static tool registry.

## Future frontend integration

No frontend code is part of this change. A later frontend can use:

- `GET /api/reminders/preferences` for resolved defaults.
  - `PUT /api/reminders/preferences` for `enabled`, `language`, `timezone`, `daily_dispatch_time` (`HH:MM`), `default_task_reminder_offsets_minutes`, the fixed `cadence_offsets`, `email_enabled`, `chat_enabled`, and `role_card_id`.
- `GET /api/reminder-role-cards` and `GET /api/reminder-role-cards/{id}` for card selection/details.
- `GET /api/reminders/history?limit=20&offset=0` for digest and sanitized per-channel outcomes.

The backend accepts IANA timezone names and BCP 47 language tags. `daily_dispatch_time` accepts only zero-padded `00:00` through `23:59`. Current defaults are `Asia/Shanghai`, `zh-CN`, `09:00`, task offsets `[5, 1440]`, enabled email/chat, and `friendly-warm-guy`.

Changing `role_card_id` affects the next main-chat request in every conversation and future reminders; it does not rewrite messages already stored. Main-Agent role-card application can be rolled back with `MAIN_AGENT_ROLE_CARDS_ENABLED=false`. The default is enabled. An invalid flag value is treated as disabled.

Reminder chat messages are normal `assistant` messages. `/api/chat/history` additionally returns optional `metadata` with:

```json
{
  "source": "reminder",
  "digest_id": 123,
  "role_card_id": 1,
  "items": [
    {"item_type": "task", "item_id": 99, "due_date": "2026-08-05"}
  ]
}
```

Existing clients may ignore this field. A future UI may render a “查看详情” action that routes to `/chat`; it must not trust metadata from another user or attempt to resolve records client-side without authenticated backend ownership checks.

Interactive main-Agent assistant messages may also expose optional provenance:

```json
{
  "source": "main_agent",
  "role_card": {
    "id": 2,
    "slug": "tech-geek",
    "version": "1.0",
    "status": "selected"
  }
}
```

`status` can be `selected`, `default`, `neutral`, or `disabled`. Full card prompts and the final system prompt are never persisted in chat metadata.

## Role cards

Built-in global cards are `friendly-warm-guy`, `tech-geek`, and `sweet-high-school-girl`. Ordinary users can query/select active global cards. Only a database-authorized administrator can create/update/deactivate global cards. User-created/private cards and SillyTavern JSON/PNG import are future work; reserved ownership/extension fields must not be exposed as a create API prematurely. Future private cards must use `scope=private` plus an authoritative owner. Discovery currently exposes only active `scope=global` cards, so a malformed null owner cannot make a private-scope card public.

## Provider and retry behavior

- Reminder generation has a total budget of three provider calls. Invalid output, provider failure, missing provider, or configured quota denial falls back to a localized deterministic template.
- Email transient failures use bounded backoff and stop after the third attempt. Permanent auth/config/content failures stop earlier.
- An interrupted SMTP attempt with unknown provider outcome is not blindly resent, preventing accidental duplicate mail.
- Chat remains independent when SMTP fails.

## Acceptance layers

1. Fake LLM/channel automated tests: no network or secrets.
2. Existing backend regressions and frontend production build.
3. Actual MySQL schema/idempotency/concurrency gate.
4. Real LLM role-card and token-accounting smoke gate.
5. Real QQ Mail SMTP submission and observed inbox-receipt gate.

The real five-minute gate must run only against a configured local environment. A PASS requires persisted email provider submission and chat delivery; SMTP failure is reported separately and is not converted into a PASS.

`backend/run_main_agent_role_card_gate.py` is the sanitized main-Agent provider gate. It gives each built-in card the same synthetic read-only `list_tasks` result, requires the task facts to survive, and reports only provider/model labels, token totals, statuses, and content fingerprints. Missing or rejected provider credentials produce `BLOCKED`, never a fake PASS.

Reports store only timestamps, non-secret provider/model labels, status, and sanitized errors. Never store account credentials, authorization codes, complete private prompts, full digest bodies, or inbox content in repository evidence.
