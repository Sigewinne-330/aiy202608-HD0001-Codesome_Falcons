# Verification Report and Requirement-to-Test Matrix

Date: 2026-08-03  
Change: `add-agent-generated-calendar-reminders`

## Gate summary

| Gate | Status | Evidence |
|---|---|---|
| Automated backend suite | PASS | `cd backend && .venv/bin/python -m unittest discover -s tests -v`: 70 discovered, 69 passed, 1 explicit MySQL-gate skip |
| Actual MySQL gate | PASS | `RUN_MYSQL_REMINDER_TESTS=1 .venv/bin/python -m unittest tests.test_reminder_mysql_integration -v`: 1 passed |
| Frontend production regression build | PASS | `cd frontend && npm run build`: 350 modules transformed; only the pre-existing non-critical chunk-size advisory |
| OpenSpec strict validation | PASS (final sign-off pending) | `openspec validate add-agent-generated-calendar-reminders --strict`; task 6.7 remains open until both real-provider gates finish |
| Real LLM/card-quality gate | NOT RUN | Task 6.5; no user-authorized LLM key is installed in the current runtime environment |
| Real QQ Mail submission and inbox gate | NOT RUN | Task 6.6; SMTP values are not installed in the current process environment, and no credential is copied from conversation text into commands or files |

## Secret-scan evidence

- `git diff --check`: PASS.
- Named SMTP/LLM credential assignment scan across source, fixtures, OpenSpec, docs, and reports: PASS after classifying only documented placeholders and intentionally synthetic sanitization fixtures; no runtime credential value was found.
- Common API-token prefixes and PEM private-key header scan: PASS with zero matches.
- Gmail/QQ address-domain scan: PASS; only redacted/documented example placeholders were present.
- `backend/.env`: absent, therefore neither read nor tracked. Runtime secrets remain outside the repository.
- Generated `.log` artifact scan: zero files.
- Readiness output is sanitized and reports database/link/worker PASS, while real LLM and SMTP are explicitly NOT READY.

Test names below omit the repeated `backend/tests/` prefix. “Provider gate” is deliberately not equivalent to a pass.

## Calendar reminder scheduling

| Spec scenario or edge case | Status | Evidence |
|---|---|---|
| All supported unfinished types are selected | PASS | `test_reminder_scheduler.py::test_candidate_query_includes_three_categories_without_limit` |
| Completed and undated records are excluded | PASS | `test_reminder_scheduler.py::test_candidate_query_includes_three_categories_without_limit` |
| Different valid timezones reach local 09:00 at their own UTC instants | PASS | `test_reminder_scheduler.py::test_timezone_0900_and_dst_boundaries` |
| Restart/catch-up after 09:00 sends once in the same local day | PASS | `test_reminder_scheduler.py::test_claim_is_idempotent_and_final_snapshot_rechecks_state`; `test_reminder_orchestrator.py::test_full_fake_delivery_and_rerun_are_idempotent` |
| D-2, D-1, D0, D+1, D+3, D+7 only | PASS | `test_reminder_scheduler.py::test_six_cadence_points_only` |
| Item created inside the window has no historical backfill | PASS | `test_reminder_scheduler.py::test_six_cadence_points_only` (selection is based only on the evaluated local date) |
| Completion before delivery cancels the item | PASS | `test_reminder_orchestrator.py::test_final_recheck_cancels_item_completed_during_generation` |
| Deletion and rescheduling suppress the old occurrence; new due date can qualify | PASS | `test_reminder_scheduler.py::test_claim_is_idempotent_and_final_snapshot_rechecks_state` |
| Repeated same-window scans do not redeliver | PASS | `test_reminder_orchestrator.py::test_full_fake_delivery_and_rerun_are_idempotent` |
| Two workers race without duplicate digest/occurrence/chat/email side effects | PASS (MySQL) | `test_reminder_mysql_integration.py::test_schema_seed_timezone_and_two_worker_idempotency` |
| Standalone worker is independent of web worker count | PASS | `test_reminder_operations.py::test_worker_once_injects_clock_and_session`; `::test_daemon_registers_single_job_and_graceful_signals` |
| Invalid timezone is rejected; normal missing preferences use Shanghai default | PASS | `test_reminder_foundation.py::test_preference_validation_and_inactive_card_fallback`; `::test_read_through_defaults_and_persist_once` |
| Outage spanning a local day does not backfill missed historical days | PASS | `test_reminder_scheduler.py::test_six_cadence_points_only` |
| `overdue` remains unfinished and receives configured overdue occurrences | PASS | `test_reminder_scheduler.py::test_six_cadence_points_only` |
| Deleted item during final recheck is cancellation, not worker failure | PASS | `test_reminder_scheduler.py::test_claim_is_idempotent_and_final_snapshot_rechecks_state` |
| More than 50 eligible items aggregate without truncation | PASS | `test_reminder_scheduler.py::test_candidate_query_includes_three_categories_without_limit`; deterministic aggregation in `test_reminder_agent.py::test_dedicated_prompt_valid_output_usage_and_complete_rendering` |

## Reminder content generation

| Spec scenario or edge case | Status | Evidence |
|---|---|---|
| Supplemental context uses only allowlisted user-scoped reads | PASS | `test_reminder_agent.py::test_read_tools_are_user_scoped_and_bounded` |
| Write/forged tools are rejected without mutation | PASS | `test_reminder_agent.py::test_read_tool_is_allowed_but_write_tool_is_rejected` |
| Chinese + Tech Geek style boundary | AUTOMATED PASS; REAL QUALITY NOT RUN | Prompt/language authority: `test_reminder_agent.py::test_role_card_and_items_are_delimited_data`; live stylistic observation belongs to provider gate 6.5 |
| Role-card language conflict cannot override user language | PASS | `test_reminder_agent.py::test_role_card_and_items_are_delimited_data` |
| Description prompt injection is delimited and non-governing | PASS | `test_reminder_agent.py::test_dedicated_prompt_valid_output_usage_and_complete_rendering` |
| Multi-item output has one subject, 1–2 sentence framing, complete deterministic list | PASS | `test_reminder_agent.py::test_dedicated_prompt_valid_output_usage_and_complete_rendering` |
| Markdown, line-break subject, extra sentence, or malformed JSON retries/falls back | PASS | `test_reminder_agent.py::test_output_contract_rejects_markdown_and_extra_sentences`; `::test_three_invalid_or_failed_attempts_use_template` |
| Three provider failures cause fallback and no fourth call | PASS | `test_reminder_agent.py::test_three_invalid_or_failed_attempts_use_template` |
| Quota denial makes no LLM call and still creates template content | PASS | `test_reminder_agent.py::test_missing_provider_and_quota_denial_skip_llm` |
| Successful provider usage is recorded for purpose `reminder` | PASS | `test_reminder_agent.py::test_dedicated_prompt_valid_output_usage_and_complete_rendering` |
| Failed usage leaves unknown token counts null | PASS | `test_reminder_agent.py::test_three_invalid_or_failed_attempts_use_template` |
| Unsupported role-card macro/tool instruction is data or rejected | PASS | `test_reminder_api.py::test_admin_card_lifecycle_validation_and_dry_run_default`; `test_reminder_agent.py::test_role_card_and_items_are_delimited_data` |
| Empty title gets localized safe label | PASS | `test_reminder_agent.py::test_neutral_localized_rendering_truncation_and_safe_chat_url` |
| Long description is truncated only in prompt payload | PASS | `test_reminder_agent.py::test_neutral_localized_rendering_truncation_and_safe_chat_url` |
| Emoji remains optional and fallback does not depend on it | PASS | `test_reminder_agent.py::test_missing_provider_and_quota_denial_skip_llm` |
| Subject control characters are rejected | PASS | `test_reminder_agent.py::test_output_contract_rejects_markdown_and_extra_sentences` |

## Reminder delivery

| Spec scenario or edge case | Status | Evidence |
|---|---|---|
| Multiple eligible items form one daily digest offered once per channel | PASS | `test_reminder_scheduler.py::test_candidate_query_includes_three_categories_without_limit`; `test_reminder_orchestrator.py::test_full_fake_delivery_and_rerun_are_idempotent` |
| Email retry reuses immutable content without LLM/chat duplication | PASS | `test_reminder_orchestrator.py::test_due_delivery_retry_runs_without_regeneration` |
| SMTP outage leaves chat successful and email independently retryable | PASS | `test_reminder_delivery.py::test_email_retries_three_times_while_chat_succeeds` |
| Disabled email is skipped without SMTP contact | PASS | `test_reminder_delivery.py::test_permanent_failure_and_disabled_channel_do_not_retry` |
| Reminder appears as backward-compatible assistant chat history with metadata | PASS | `test_reminder_delivery.py::test_channels_succeed_independently_and_are_idempotent` |
| Follow-up context is user-scoped | PASS | Reminder metadata test above plus `test_reminder_agent.py::test_read_tools_are_user_scoped_and_bounded` |
| Clearing visible chat retains audit and does not redeliver | PASS | `test_reminder_delivery.py::test_clearing_visible_chat_keeps_delivery_audit_and_prevents_redelivery` |
| SMTP accepts one digest | FAKE PASS; REAL SUBMISSION NOT RUN | Fake transport: `test_reminder_delivery.py::test_channels_succeed_independently_and_are_idempotent`; real provider gate 6.6 |
| Missing/malformed SMTP config is sanitized and channel-independent | PASS | `test_registration_readiness.py::test_smtp_check_reports_missing_and_conflicting_settings`; `::test_rendered_output_contains_no_secret_values` |
| Third transient email failure is final; no fourth attempt | PASS | `test_reminder_delivery.py::test_email_retries_three_times_while_chat_succeeds` |
| SMTP authentication rejection is sanitized and does not retry | PASS | `test_reminder_delivery.py::test_permanent_failure_and_disabled_channel_do_not_retry` |
| Future connector registers through existing channel contract | PASS | `test_reminder_delivery.py::test_channel_failure_is_isolated_and_connector_is_extensible` |
| Ordinary user cannot run worker or administer global cards | PASS | `test_reminder_api.py::test_ordinary_user_cannot_administer_or_run` |
| Administrator dry run has no delivery side effects | PASS | `test_reminder_api.py::test_admin_card_lifecycle_validation_and_dry_run_default`; `test_reminder_orchestrator.py::test_dry_run_has_no_persistent_or_external_side_effects` |
| Automated suite uses fake providers | PASS | Backend suite gate above; provider implementations are injected fakes in agent, delivery, and orchestrator tests |
| Missing real SMTP runtime config is reported as NOT RUN, never PASS | PASS (reporting rule) | Gate summary above and task 6.6 state |
| SMTP submission versus inbox receipt are separate observations | NOT RUN provider gate | Task 6.6 requires both observations |
| Unsafe application base URL is rejected before delivery | PASS | `test_reminder_agent.py::test_neutral_localized_rendering_truncation_and_safe_chat_url`; `test_reminder_operations.py::test_readiness_checks_are_isolated_and_sanitized` |
| Digest with no final eligible items is cancelled without delivery | PASS | `test_reminder_orchestrator.py::test_final_recheck_cancels_item_completed_during_generation` |
| Fresh attempt lease is not stolen; stale unknown SMTP outcome is not resent | PASS | `test_reminder_delivery.py::test_fresh_attempt_leases_are_not_executed_by_another_worker`; `::test_abandoned_smtp_attempt_is_not_resent` |
| Chat persistence failure does not suppress successful email | PASS | `test_reminder_delivery.py::test_channel_failure_is_isolated_and_connector_is_extensible` |
| History exposes sanitized codes/status, not raw exceptions or credentials | PASS | `test_reminder_api.py::test_history_is_current_user_only_and_paginated`; readiness sanitization tests |

## Reminder preferences and role cards

| Spec scenario or edge case | Status | Evidence |
|---|---|---|
| Existing user gets documented defaults and one persisted row | PASS | `test_reminder_foundation.py::test_read_through_defaults_and_persist_once` |
| Invalid timezone/language keeps previous settings | PASS | `test_reminder_api.py::test_preferences_defaults_updates_and_validation` |
| Active global card can be selected | PASS | `test_reminder_api.py::test_preferences_defaults_updates_and_validation` |
| Inactive/missing/inaccessible card is rejected without replacing selection | PASS | `test_reminder_api.py::test_preferences_defaults_updates_and_validation` |
| Administrator creates valid compact card without code changes | PASS | `test_reminder_api.py::test_admin_card_lifecycle_validation_and_dry_run_default` |
| Executable markup, oversized aggregate content, macros, and tool grants are rejected | PASS | `test_reminder_api.py::test_admin_card_lifecycle_validation_and_dry_run_default`; Pydantic field/aggregate limits |
| Fresh initialization creates exactly three stable built-ins and default | PASS | `test_reminder_foundation.py::test_builtin_cards_seed_exactly_once`; `::test_read_through_defaults_and_persist_once` |
| Repeated seed does not duplicate or overwrite admin active state | PASS | `test_reminder_foundation.py::test_builtin_cards_seed_exactly_once` |
| Non-admin global-card mutation is forbidden | PASS | `test_reminder_api.py::test_ordinary_user_cannot_administer_or_run` |
| Deactivated selected card falls back to active default | PASS | `test_reminder_foundation.py::test_preference_validation_and_inactive_card_fallback`; API preference test |
| Current release does not advertise ordinary-user private-card creation | PASS | `test_reminder_api.py::test_admin_card_lifecycle_validation_and_dry_run_default` (unsupported POST returns method-not-allowed) |
| Every card inactive yields neutral deterministic instructions | PASS | `test_reminder_agent.py::test_neutral_localized_rendering_truncation_and_safe_chat_url` |
| Concurrent first access creates one preference row | PASS (MySQL) | `test_reminder_mysql_integration.py::test_schema_seed_timezone_and_two_worker_idempotency` |
| User deletion cascades reminder preferences/digests/deliveries | PASS (MySQL) | `test_reminder_mysql_integration.py::test_schema_seed_timezone_and_two_worker_idempotency` |
| Card text updates do not rewrite historical digest fields/snapshots | PASS | `test_reminder_foundation.py::test_role_card_edits_do_not_rewrite_historical_digest_snapshot`; immutable retry in `test_reminder_orchestrator.py::test_due_delivery_retry_runs_without_regeneration` |
| Future private-scope card cannot become global merely from a null owner | PASS | Explicit `scope` boundary; `test_reminder_api.py::test_card_discovery_hides_inactive_cards` inserts a private-scope/null-owner fixture and proves it is hidden |

## Remaining provider evidence

Task 6.5 must record only sanitized provider/model, language/card, allowed tool names, output-contract result, usage-record result, and fallback result for all three built-in cards. Task 6.6 must record SMTP submission and observed inbox receipt separately, plus one matching chat message and idempotent rerun. Neither report may contain a key, password, authorization code, full private address, private task text, full body, or inbox content.
