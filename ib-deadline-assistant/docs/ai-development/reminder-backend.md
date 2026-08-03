# Reminder Backend and Future Frontend Handoff

## Runtime architecture

- FastAPI serves preferences, role-card discovery, delivery history, and protected administrator operations.
- `backend/reminder_worker.py` is the production scheduling process. Do not start an APScheduler job inside each Uvicorn worker.
- The worker evaluates users after local 09:00, creates durable occurrence/digest claims, calls the dedicated Reminder Agent, then fans out the immutable digest to chat and email.
- Email and chat retain independent status and retry audit. SMS and software connectors should implement the channel protocol rather than call scheduling or the LLM directly.

## Future frontend integration

No frontend code is part of this change. A later frontend can use:

- `GET /api/reminders/preferences` for resolved defaults.
- `PUT /api/reminders/preferences` for `enabled`, `language`, `timezone`, the fixed `cadence_offsets`, `email_enabled`, `chat_enabled`, and `role_card_id`.
- `GET /api/reminder-role-cards` and `GET /api/reminder-role-cards/{id}` for card selection/details.
- `GET /api/reminders/history?limit=20&offset=0` for digest and sanitized per-channel outcomes.

The backend accepts IANA timezone names and BCP 47 language tags. MVP cadence must contain exactly `[2, 1, 0, -1, -3, -7]`. Current defaults are `Asia/Shanghai`, `zh-CN`, enabled email/chat, and `friendly-warm-guy`.

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

Reports store only timestamps, non-secret provider/model labels, status, and sanitized errors. Never store account credentials, authorization codes, complete private prompts, full digest bodies, or inbox content in repository evidence.
