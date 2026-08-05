# Adaptive scheduling implementation traceability

| OpenSpec area | Runtime implementation | Verification |
|---|---|---|
| Consent and data control | `schedule_consent`, `schedule_personalization_governance`, `schedule_data_controls` | consent, ownership, reset, deletion, export tests |
| Typed observation/outcome plane | `schedule_observations`, `schedule_work_events`, `schedule_labels` | idempotency, transition, censoring, failure-isolation tests |
| Effort/risk models | `schedule_features`, `schedule_effort_model`, `schedule_risk_model`, `schedule_drift` | numerical, leakage, cold-start, drift, calibration tests |
| Safe serving | `schedule_adaptive_ranking`, `schedule_personalization_serving`, `schedule_adaptive_integration` | randomized invariants, state matrix, timeout, no-auto-apply tests |
| Memory/LLM boundary | `schedule_memory`, `schedule_reflections`, `schedule_llm_memory`, `schedule_task_extraction` | bounded projection, injection, evidence, deletion tests |
| Evaluation/governance | `schedule_model_evaluation`, `schedule_promotion_gates`, `schedule_personalization_monitoring`, `schedule_personalization_operations` | future-only metrics, lexicographic gates, alert/recovery tests |
| Aggregate priors | `schedule_aggregate_priors`, recomputation job handler | opt-in, small-cell, withdrawal/version tests |
| Frontend controls | `PersonalizationSettingsPanel`, `WorkSessionControls`, `SchedulingMemoryCenter`, `RecommendationExplanationCard`, `PersonalizationDashboard` | Node state tests, Vite build, authenticated browser acceptance |

The OpenSpec task checklist is the authoritative implementation status. The final gate remains explicit user approval before archive or any expansion to learned auto-apply/deep learning.
