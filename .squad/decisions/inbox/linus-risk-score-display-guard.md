# Decision: Defensive guard for Avg Risk Score tile (#119)

**Status:** ✅ Implemented
**Date:** 2026-05-13
**Author:** Linus (Frontend)
**Branch/Commit:** squad/p2-wave-3

## Context
Admin dashboard "Avg Risk Score" tile was rendering `1,778,591,506.40` —
~`time.time()` in seconds for 2026, i.e., a Unix timestamp leaking into a
field that should be a 0.0–1.0 probability.

## Investigation
- Frontend (`AdminPage.tsx`) just calls `stats.avgRiskScore.toFixed(2)`
  on the value returned by `GET /api/admin/stats`. UI is innocent.
- Backend (`src/ai-service/app/routes/api.py:152`) computes
  `avg = sum(score for _, score in scores) / len(scores)` over the Redis
  sorted set `scored-transactions`, where `score` is the sorted-set score.
- Producer side (`anomaly_service.py:617`) writes `assessment.riskScore`
  (clamped 0.0–1.0 at `anomaly_service.py:195`) as the sorted-set score.
- Conclusion: current code path is sane. The 1.78×10⁹ value is
  **poisoned historical data** — pre-Foundry-fix (#118) entries where
  the sorted-set score was a timestamp (or some other field) instead of
  a probability. New entries written after #118's fix should be 0–1.

## Decision
Frontend remains the renderer of whatever the backend returns, but adds
a defensive `formatRiskScore()` helper:
- 0 ≤ value ≤ 1 → render `value.toFixed(2)` (existing behavior)
- otherwise (NaN, ±∞, negative, > 1) → render `—`

This stops the dashboard from advertising obviously-broken numbers while
the underlying data is cleaned up.

## What is NOT fixed here (out of frontend scope)
- Redis cleanup of the `scored-transactions` sorted set to purge legacy
  entries whose score is a timestamp. Recommended: `DEL scored-transactions`
  on the deployed Redis (transactions will re-score on next ingest), or
  rebuild from the per-transaction JSON keys.
- Verifying that all post-#118 transactions land with `score ∈ [0, 1]`.

**Flagged for Brian / Basher / Turk** — see comment on #119.
