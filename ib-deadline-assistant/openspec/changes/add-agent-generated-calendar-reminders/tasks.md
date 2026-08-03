## 1. Persistence and authorization foundation

- [x] 1.1 Add authoritative SQLAlchemy models and MySQL bootstrap/migration changes for administrator status, preferences, compact role cards, occurrences, digests, deliveries, usage records, and optional chat metadata.
  - **Dependencies:** accepted OpenSpec artifacts.
  - **Priority:** P0.
  - **Verification:** model metadata creates the expected schema in isolated tests; actual MySQL bootstrap succeeds; existing user/auth tables and constraints remain usable.

- [x] 1.2 Implement idempotent seeds for `friendly-warm-guy`, `tech-geek`, and `sweet-high-school-girl`, including the accepted safe style boundaries and Friendly Warm Guy default.
  - **Dependencies:** 1.1.
  - **Priority:** P0.
  - **Verification:** fresh and repeated seed tests produce exactly three stable built-in slugs without duplicate or destructive overwrite.

- [x] 1.3 Add reminder preference and card repositories with read-through defaults, concurrent first-write safety, IANA timezone validation, BCP 47 normalization, active-card fallback, and authoritative user ownership.
  - **Dependencies:** 1.1, 1.2.
  - **Priority:** P0.
  - **Verification:** focused repository tests cover defaults, invalid inputs, concurrent creation, inactive cards, and cross-user denial.

- [x] 1.4 Add server-authoritative administrator authorization that defaults false and cannot be changed through ordinary profile/auth request bodies.
  - **Dependencies:** 1.1.
  - **Priority:** P0.
  - **Verification:** admin dependency tests permit controlled admin fixtures and return 403 for ordinary users without mutating state.

## 2. Scheduling and idempotent orchestration

- [x] 2.1 Implement one authoritative candidate query for unfinished top-level todo tasks, process children, and deadlines, excluding process parents, complete records, and missing due dates without a fixed result truncation.
  - **Dependencies:** 1.1.
  - **Priority:** P0.
  - **Verification:** candidate tests cover every task/deadline status and type, ownership, more than 50 records, and duplicate-looking records.

- [x] 2.2 Implement timezone-local 09:00 evaluation and D-2/D-1/D0/D+1/D+3/D+7 cadence calculation with same-local-day catch-up and no historical-day backfill.
  - **Dependencies:** 1.3, 2.1.
  - **Priority:** P0.
  - **Verification:** clock-controlled tests pass for `Asia/Shanghai`, one daylight-saving timezone, date boundaries, restarts, and items created inside the window.

- [x] 2.3 Implement transactional occurrence and daily-digest claims using durable unique keys and safe handling of database uniqueness races.
  - **Dependencies:** 1.1, 2.2.
  - **Priority:** P0.
  - **Verification:** repeated, concurrent, restarted, and manually triggered scans create one occurrence per identity and one digest per user/local date.

- [x] 2.4 Implement final authoritative state re-check, cancellation, reschedule handling, and immutable item snapshots before any channel side effect.
  - **Dependencies:** 2.3.
  - **Priority:** P0.
  - **Verification:** tests complete, delete, and reschedule items between selection/generation/delivery and prove obsolete items are not sent.

## 3. Dedicated Reminder Agent and usage accounting

- [x] 3.1 Add a shared LLM usage recorder and unlimited-by-default quota-policy interface; record provider-reported prompt/completion/total usage for reminder calls and migrate current interactive chat calls where usage is available.
  - **Dependencies:** 1.1.
  - **Priority:** P0.
  - **Verification:** fake provider tests attribute usage to the correct user and purpose, preserve unknown counts as null, aggregate configured quotas, and never fabricate token values.

- [x] 3.2 Expose a provider-failover completion boundary that accepts an explicit system prompt, output limits, usage callback, and dedicated tool allowlist without loading the main `SYSTEM_PROMPT` or main-chat history.
  - **Dependencies:** 3.1.
  - **Priority:** P0.
  - **Verification:** spies prove reminder calls use only the dedicated prompt/history and existing chat behavior still uses its original agent path.

- [x] 3.3 Implement separately registered, user-scoped read-only `list_tasks`, `list_subtasks`, and `list_deadlines` tools for the Reminder Agent; reject every unregistered or mutable tool call.
  - **Dependencies:** 2.1, 3.2.
  - **Priority:** P0.
  - **Verification:** allowlist, result-bound, cross-user, forged-tool, and write-tool rejection tests pass without changing application data.

- [x] 3.4 Implement prompt assembly for language, compact role card, structured calendar facts, and truncated/delimited untrusted descriptions with explicit priority over prompt injection.
  - **Dependencies:** 1.2, 3.2, 3.3.
  - **Priority:** P0.
  - **Verification:** injection fixtures in descriptions/cards/tools cannot change language, persona boundary, permissions, output shape, destination, or source item facts.

- [x] 3.5 Implement generated subject/framing validation, deterministic complete item-list rendering, absolute `/chat` link construction, three-attempt generation policy, and localized template fallback for provider, output, or quota failure.
  - **Dependencies:** 2.4, 3.4.
  - **Priority:** P0.
  - **Verification:** `zh-CN` and `en-US` tests enforce clear single-line subject, plain-text one-to-two-sentence framing, complete multi-item list, valid link, and fallback after exactly three failed attempts.

## 4. Channel delivery and chat continuity

- [x] 4.1 Implement immutable digest envelopes, channel registry/protocol, normalized channel outcomes, and independent persisted delivery states.
  - **Dependencies:** 1.1, 3.5.
  - **Priority:** P0.
  - **Verification:** fake channel tests prove independent delivered/failed/retryable/skipped states and show a future adapter can register without scheduler changes.

- [x] 4.2 Implement chat delivery to authoritative `chat_history` as one assistant message with optional source/digest/item/card metadata and backward-compatible history responses.
  - **Dependencies:** 4.1.
  - **Priority:** P0.
  - **Verification:** chat/history tests show one visible digest, user-scoped context resolution, current response fields preserved, and clear-history behavior that retains delivery audit.

- [x] 4.3 Generalize SMTP into a generic email transport while retaining the existing verification-code sender interface and tests through a compatibility adapter.
  - **Dependencies:** 4.1.
  - **Priority:** P0.
  - **Verification:** verification regression tests pass unchanged in behavior; generic plain-text messages render headers/body safely; missing/conflicting SMTP settings fail without exposing values.

- [x] 4.4 Implement email delivery to the account email with clear generated subject, deterministic body, chat link, at most three bounded retries, sanitized errors, and immutable-content reuse.
  - **Dependencies:** 4.3.
  - **Priority:** P0.
  - **Verification:** fake SMTP tests cover success, timeout, permanent auth failure, three-attempt exhaustion, no fourth attempt, and chat success during email failure.

## 5. APIs, worker, and operations

- [x] 5.1 Add authenticated preference, active-card discovery/detail, and reminder-history APIs with Pydantic validation, pagination, and strict current-user scoping.
  - **Dependencies:** 1.3, 4.1.
  - **Priority:** P1.
  - **Verification:** API tests cover defaults, updates, invalid language/timezone/card/cadence, pagination, and cross-user access denial.

- [x] 5.2 Add administrator-only global role-card create/update/deactivate and manual reminder-run APIs, with dry run as the default and explicit idempotent delivery opt-in.
  - **Dependencies:** 1.4, 2.4, 3.5, 4.4.
  - **Priority:** P1.
  - **Verification:** admin API tests cover valid lifecycle, immutable built-in slugs, unsafe card rejection, dry run with no side effects, actual idempotent execution, and ordinary-user 403 responses.

- [x] 5.3 Add a standalone reminder worker with `--once` and daemon modes, graceful shutdown, explicit injected clock, periodic due-delivery retries, and development-only in-process scheduling disabled by default.
  - **Dependencies:** 2.4, 4.4.
  - **Priority:** P0.
  - **Verification:** process/service tests cover startup, tick, shutdown, restart, two competing workers, and independence from Uvicorn process count.

- [x] 5.4 Add non-secret configuration examples and a read-only readiness command for application base URL, worker settings, LLM availability, schema, and provider-neutral SMTP presence/TLS consistency.
  - **Dependencies:** 5.3.
  - **Priority:** P1.
  - **Verification:** readiness tests isolate each missing/malformed prerequisite using placeholders only and never print an address, key, password, authorization code, or raw environment.

- [x] 5.5 Document local/production worker startup, preferences/card APIs for future frontend developers, channel extension contract, QQ Mail runtime configuration procedure, secret rotation guidance, and layered acceptance reporting.
  - **Dependencies:** 5.1, 5.2, 5.4.
  - **Priority:** P1.
  - **Verification:** commands match the repository environment; examples contain placeholders; documentation explicitly separates fake, real LLM, SMTP submission, and inbox-receipt gates.

## 6. Verification and handoff

- [x] 6.1 Run all focused fake-provider reminder tests and produce a requirement-to-test matrix covering every scenario and edge case in the four delta specs.
  - **Dependencies:** 1.1–5.5.
  - **Priority:** P0.
  - **Verification:** every matrix row links to a passing test or an explicitly separate provider gate; no scenario is marked passed without evidence.

- [x] 6.2 Run existing backend auth, email-verification, task, deadline, calendar, and chat regressions plus the frontend production build despite the backend-only scope.
  - **Dependencies:** 6.1.
  - **Priority:** P0.
  - **Verification:** all relevant backend tests and `npm run build` pass with no new critical warning or behavior regression.

- [x] 6.3 Run actual-MySQL schema, seed, timezone, uniqueness, and concurrent-worker checks against the supported runtime stack.
  - **Dependencies:** 6.1.
  - **Priority:** P0.
  - **Verification:** bootstrap/migration is repeatable and concurrent scans produce no duplicate occurrences, digests, chat messages, or delivery rows.

- [x] 6.4 Run a tracked-files, patch, fixture, log, and report secret scan before any provider-backed test; rotate any credential that was accidentally persisted or exposed outside the approved runtime channel.
  - **Dependencies:** 5.4, 5.5.
  - **Priority:** P0.
  - **Verification:** scan finds no SMTP authorization code, password, API key, private inbox content, or full private prompt in repository artifacts or generated evidence.

- [ ] 6.5 With user-authorized LLM configuration supplied outside Git, generate one controlled localized reminder for each built-in role card and verify output contract, read-only tools, token accounting, and deterministic fallback separately.
  - **Dependencies:** 6.1, 6.4.
  - **Priority:** P1 provider gate.
  - **Verification:** sanitized report records timestamp, provider/model, language/card, tool names, contract result, usage-record result, and fallback result without private task text or keys.

- [ ] 6.6 With user-authorized QQ Mail SMTP configuration supplied outside Git, send one controlled reminder, observe provider submission and inbox receipt, verify chat synchronization, and record only sanitized evidence.
  - **Dependencies:** 6.2, 6.3, 6.4.
  - **Priority:** P0 final provider gate.
  - **Verification:** one idempotent email is observed in the controlled inbox, one matching chat message exists, and the report contains no credential, full address, full body, or inbox content.

- [ ] 6.7 Reconcile implementation with proposal/specs/design/rules, update any accepted deviation, run `openspec validate add-agent-generated-calendar-reminders --strict`, and present final gate status without archiving until all required evidence passes.
  - **Dependencies:** 6.1–6.6.
  - **Priority:** P0.
  - **Verification:** strict validation passes, task statuses match evidence, unresolved provider gates remain BLOCKED/NOT RUN rather than being reported as PASS, and user approval is requested before archive.
