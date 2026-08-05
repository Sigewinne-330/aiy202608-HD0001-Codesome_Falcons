# Adaptive scheduling personalization: operations guide

## Runtime policy

All switches are private-by-default (`false`) unless explicitly configured:

| Area | Environment flag | Default | Effect |
|---|---|---:|---|
| Master | `SCHEDULING_PERSONALIZATION_ENABLED` | off | Enables the learning plane only; deterministic scheduling remains available. |
| Capture | `SCHEDULING_OBSERVATION_CAPTURE_ENABLED` | off | Allows typed decision/work/outcome evidence. |
| Personal model | `SCHEDULING_PERSONAL_MODELING_ENABLED` | off | Allows candidate model inference. |
| Shadow / suggestion | `SCHEDULING_PERSONALIZATION_SHADOW_ENABLED`, `SCHEDULING_PERSONALIZATION_SUGGESTION_ENABLED` | off | Shadow annotations or bounded suggestion display. Learned auto-apply is never enabled. |
| Reflection | `SCHEDULING_MEMORY_REFLECTION_ENABLED` | off | Allows evidence-backed LLM reflection candidates. |
| Cross-user | `SCHEDULING_CROSS_USER_AGGREGATION_ENABLED` | off | Allows only structured, consented aggregate sufficient statistics. |
| Exploration | `SCHEDULING_NEAR_TIE_EXPLORATION_ENABLED` | off | Display-order experiment among safe near ties. |
| Global kill | `SCHEDULING_PERSONALIZATION_KILL_SWITCH` | off | Forces zero learned influence. Persisted incident kill has equal authority. |

The server additionally requires the user’s separate consent settings. A user can withdraw operational personalization, work capture, LLM memory, cross-user learning, or exploration independently. The current consent version and eligibility watermark are returned by `/api/scheduling/personalization/settings`.

## Data meaning and retention

The system stores typed observations, not surveillance. Active timers, explicit outcomes, lifecycle state, decision context hashes, bounded structured features, and evidence-linked memory are distinct records. Task text is not copied into aggregate priors. Raw event retention defaults to 365 days and is user-configurable from 30 to 3650 days. Withdrawal/reset/delete increments an eligibility watermark immediately; asynchronous cleanup may follow, but serving queries exclude old evidence before physical cleanup.

## Serving states and limitations

`disabled`, `replay`, `shadow`, `suggestion`, and `killed` are explicit states. The deterministic scheduler remains the feasibility and apply authority in every state. Learned influence is bounded by maturity, calibration, sample gate, safety budget, score adjustment, near-tie, and rank-displacement rules. P50/P90 are uncertainty ranges, not promises. The model does not infer energy, motivation, intelligence, personality, disability, or mental health.

## Worker cadence and recovery

The existing leased-job runner handles labels, features, model candidates, evaluation, reflections, retention, deletion propagation, drift, and aggregate recomputation. Jobs are idempotent, leased, bounded in retries, and savepoint-isolated. Monitoring windows must include safety, deadline, calibration, coverage, autonomy, latency, update, drift, disparity, and deletion signals.

Critical safety/privacy alerts automatically persist an incident snapshot and activate the learned-influence global kill. A healthy later window is recorded as `recovered` but never silently clears the kill; an authorized operator must review the runbook, replay the affected window, and use the audited recovery control. Deterministic scheduling remains available during the incident.

## User troubleshooting

- If the panel says `disabled`, check both the user consent and the environment policy; neither one alone can enable serving.
- If a save returns `409`, reload because another tab changed the consent version.
- If the dashboard has no calibration value, this is intentional until the configured minimum sample threshold is met.
- If memory deletion shows `pending`, serving already excludes the invalidated watermark; wait for the deletion propagation job and inspect `/api/scheduling/personalization/deletion-status`.
- If serving is `killed` or `fallback`, keep the deterministic recommendation and inspect readiness/model history before recovery.
