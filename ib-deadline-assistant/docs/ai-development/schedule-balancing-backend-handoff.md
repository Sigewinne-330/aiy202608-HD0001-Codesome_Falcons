# Schedule balancing backend handoff

This document describes the backend contract for the future frontend. This
change intentionally does not add Vue pages.

## Runtime flag

Set `SCHEDULING_BALANCER_ENABLED=true` to expose the scheduling API and enable
the Agent dated-create guard. It defaults to `false`; existing task, calendar,
reminder, chat, and legacy `/api/tasks/plan` clients remain usable when it is
off.

## Core flow

1. For a dated Agent create, call `POST /api/scheduling/interventions/preflight`.
2. A result with `kind=create` may be submitted through the ordinary create
   path. A result with `kind=overload_intervention` must display the complete
   same-day workload, recommendation, alternatives, load ratio, recommended
   effort, `increase_effort`, reasons, and counterfactual.
3. Resolve with `POST /api/scheduling/interventions/{id}/resolve` and one of
   `keep_original`, `accept_recommendation`, or `choose_date`. The backend
   rechecks the current data and keeps an explicit original-date override
   auditable.
4. For larger rebalancing, create a preview with `POST /api/scheduling/plans`,
   show the item changes and daily load curve, then apply with the returned
   revision and a fresh idempotency key. Apply is atomic; undo and replan have
   separate endpoints.

## Settings and history

- `GET/PUT /api/scheduling/preferences` stores the default capacity, reserve,
  chunk policy, timezone, controlled-variety limits, and auto-scheduling flag.
- `GET/PUT/DELETE /api/scheduling/capacity-overrides[/{date}]` controls a
  single date. A zero capacity explicitly blocks scheduling; missing dates
  inherit the user's default. Weekends and public holidays are not inferred.
- `GET /api/scheduling/analyze` is side-effect-free and returns the date-level
  load curve.
- `GET /api/scheduling/history` returns sanitized, user-scoped audit events.

## Display rules

All schedule assignments are ISO calendar dates (`YYYY-MM-DD`). The frontend
must not turn them into local midnight events or display `00:00`. Hard
Deadlines, locked items, completed items, zero-capacity dates, dependency
violations, and stale versions are not soft warnings; they are rejected by
the backend.

Role cards may style the explanation but cannot change the selected date,
weights, permissions, constraints, confirmation, or persisted result.

## Learning and token accounting

The MVP scorer is deterministic and does not consume LLM tokens. Optional LLM
effort clarification or wording uses the existing provider/accounting boundary
and falls back to deterministic localized text. A future learned reranker
requires separate consent and shadow evaluation and can only rerank dates that
already passed deterministic hard constraints.

### Deferred learned-reranker contract

There is no learned scorer, embedding call, training job, or model dependency
in the MVP runtime. A future OpenSpec change may add one adapter between the
deterministic safe-candidate list and final presentation, subject to all of the
following gates:

1. **Separate consent and retention policy:** training/evaluation is disabled
   until the user explicitly opts in. Pre-consent operational audit rows do not
   become training permission, and raw descriptions, role-card content, hidden
   prompts, credentials, email addresses, or chat text are never features.
2. **Minimum evidence:** do not fit a personal model with fewer than 100
   consented eligible choices and outcomes. Keep a chronological holdout of at
   least 20% and document the cohort/fallback policy in that future change.
3. **Safe input/output interface:** input contains only candidate IDs, bounded
   numeric scheduling features, deterministic scores/ranks, and model version.
   Output is a permutation of the supplied safe candidate IDs; it cannot create
   a date, allocation, effort amount, permission, or mutation.
4. **Bounded influence:** initially rerank only the deterministic top five and
   move a candidate by at most two rank positions. Re-run the hard-constraint
   validator after reranking and discard the model output on any mismatch.
5. **Shadow first:** run without affecting users for at least 30 days and compare
   acceptance, overrides, deadline misses, capacity violations, and deterministic
   regret against the baseline. Promotion requires no hard-constraint regression.
6. **Fallback and audit:** timeout, unavailable model, malformed output, unknown
   candidate, drift alarm, missing consent, or version mismatch immediately uses
   deterministic order. Audit only the model version, bounded feature snapshot,
   deterministic/learned ranks, fallback reason, and aggregate outcome.
7. **Monitoring:** measure feature/rank drift, subgroup rank displacement,
   override rate, deadline/capacity violations, and regret. Any safety or fairness
   threshold breach disables learned ranking without disabling scheduling.

Pairwise learning-to-rank is the preferred first experiment because the stored
signal is an ordered choice among safe dates. A contextual bandit is a later
option only after counterfactual evaluation is credible. Neither approach may
relax deterministic ownership, date, capacity, lock, dependency, deadline,
version, confirmation, idempotency, apply, or undo rules.
