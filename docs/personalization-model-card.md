# Adaptive scheduling personalization model/data card

## Objective hierarchy

1. Preserve hard feasibility, ownership, deadlines, dependencies, locks, and transactional revision safety.
2. Preserve deadline reliability and calibrated uncertainty.
3. Reduce overload and unnecessary movement.
4. Improve useful effort estimates and safe recommendation ordering.
5. Measure autonomy burden, trust, disparity, latency, and deletion correctness.

Raw completion rate, acceptance, engagement, and task count cannot trade through this hierarchy or authorize promotion.

## Evidence and labels

Evidence is owner-scoped and typed: active-timer measurements, direct user reports, lifecycle signals, decision events, and bounded structured feature snapshots. Outcomes distinguish completion, reasonable abandonment, confirmed miss, deletion, unknown outcome, and right-censoring. Open or offline-unknown work is not silently treated as success. Every derived artifact carries a schema/algorithm/feature/label/calibration lineage and eligibility watermark.

## Models and priors

The effort model is an interpretable empirical-Bayes log-duration distribution with versioned general and IB priors. It returns P10/P50/P90, maturity, freshness, correction-gate state, personal influence, and hierarchy provenance. Personal evidence shrinks toward product priors and is decayed under staleness or sustained drift. Completion risk is a date-level, censoring-aware, prior-centered model evaluated only on future observations. Ranking is a bounded adapter over deterministic-safe candidates; it cannot create or mutate candidates.

LLM use is limited to bounded extraction, clarification, reflection, and explanation projections. LLM output is untrusted, schema-validated, evidence-linked, and never a confirmed coefficient or preference by itself. Model artifacts are data-only JSON; executable objects, unsafe keys, non-finite values, deep payloads, and oversized artifacts are rejected.

## Thresholds and calibration

The default effort correction gate is five effective observations; the ranking decision gate is twenty eligible decisions. Maturity and calibration scale influence. P90 coverage, risk Brier/ECE, deadline-risk recall, future-only leakage checks, operational latency/fallback, autonomy burden, and required subject/archetype slices are required evaluation signals. Calibration is hidden in the dashboard until 20 evaluation records are available.

## Privacy and cross-user boundary

Private defaults apply to minors and general users. Cross-user learning requires separate opt-in, current consent, matching watermark, non-invalidated features, exact schema lineage, and minimum contributor cells. Aggregates contain sufficient statistics only, never raw text or direct identifiers. Withdrawal and deletion recompute aggregate versions and cause broad-prior fallback when a cell is too small.

## Known limitations and causal claims

Observed completion is selected and censored: it is not a clean measure of ability or motivation. Scheduling interventions alter future observations, so policy feedback is monitored and promotion is lexicographic. The system makes predictive/operational recommendations, not causal claims. Sparse users and subjects remain on versioned priors. Short temporary changes should not rewrite long-term facts. A model can be useful without being correct about why a user struggled; the UI therefore exposes evidence categories and uncertainty rather than psychological labels.
