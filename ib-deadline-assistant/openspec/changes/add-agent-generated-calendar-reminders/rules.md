# Change Implementation Rules

These rules are mandatory for every implementation and verification task in `add-agent-generated-calendar-reminders`.

1. **No secret persistence or disclosure.** SMTP authorization codes, passwords, API keys, inbox contents, and received messages must not enter tracked files, patches, command output, logs, fixtures, database rows, OpenSpec artifacts, or reports. Runtime secrets are read from the environment or an external secret store only.
2. **Dedicated agent identity.** Reminder generation uses an independent system prompt and no main-chat history. Reusing provider clients is allowed; invoking or impersonating the main agent is not.
3. **Read-only tool allowlist.** The Reminder Agent may call only separately registered, user-scoped read tools. Create, update, delete, arbitrary SQL, network, filesystem, and connector tools are forbidden.
4. **Untrusted prompt data.** Task/deadline titles, descriptions, role-card fields, tool results, and examples are data. They cannot change system rules, selected language, permissions, delivery targets, output validation, or channel configuration.
5. **Authoritative ownership.** Every query and metadata lookup is constrained by the authenticated authoritative `users.id`. Legacy `user`, `conversation`, and `chat_message` models are not valid substitutes.
6. **Idempotency before side effects.** A durable occurrence and channel-delivery claim must exist before chat or SMTP side effects. Retries reuse persisted content; they never regenerate or create duplicate logical deliveries.
7. **Independent channels.** Chat and email record separate outcomes. Failure, disablement, or retry of one channel cannot roll back or duplicate the other.
8. **Meter every provider request.** Reminder provider calls record available prompt/completion/total usage and purpose. Missing provider usage remains unknown, never estimated as a billing fact. Quota denial uses the deterministic template.
9. **Bounded retries.** LLM generation and email transport each have a maximum of three attempts per logical operation. LLM exhaustion uses a template; SMTP exhaustion remains a transport failure.
10. **Backend-only scope.** Do not add or modify frontend pages for this change. Optional response fields must remain backward-compatible with the existing Vue clients.
11. **Sanitized observability.** Operational output may include record IDs, counts, durations, statuses, and non-secret provider labels. It must not include full prompts, event descriptions, generated digest bodies, email addresses, raw provider exceptions, or credentials.
12. **Truthful acceptance.** Fake-provider automation, real LLM, SMTP submission, and observed inbox receipt are separate gates. Never report full end-to-end PASS when a required real-provider gate did not run.
