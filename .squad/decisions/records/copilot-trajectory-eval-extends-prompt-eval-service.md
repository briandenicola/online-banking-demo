---
date: 2026-09-15
author: Copilot (Orchestrator)
status: decided
component: prompt-eval-service
issue: 376
---

# Trajectory scoring lives in `prompt-eval-service`, not a new service

#376 asked for a spike before choosing between extending `prompt-eval-service` and standing up a
new `trajectory-eval-service`. Decided directly, because the cost side of this tradeoff is already
well understood from the existing service and doesn't need a prototype to evaluate.

## Why extend, not create

`prompt-eval-service` already owns:

- Cosmos wiring and containers for eval results
- JWT/auth plumbing consistent with the rest of the platform
- The comparison UI wiring (`GET /api/evaluations/compare`) that #378 (admin UI, Phase 4) will
  need to extend anyway to show trajectory results alongside prompt-eval results

A new `trajectory-eval-service` would duplicate all three, for a workload (batch-scoring runs
against a golden trace corpus) that is not latency-sensitive, has no conflicting scaling profile
with prompt eval, and does not need independent deploy cadence. The stated advantage of a new
service — "cleaner separation" — is real but not worth re-plumbing identity, storage, and the
comparison surface that #377 (CI gate) and #378 (admin UI) both need a single place to query.

## What this means for #376

- New module/route namespace inside `prompt-eval-service` (e.g. a `TrajectoryEval` area,
  mirroring how the service already separates prompt-eval concerns internally).
- New Cosmos container for trajectory scoring runs (container name/partition key to be decided at
  implementation time, following the existing containers' conventions in
  `infra/cloud/cosmos.tf`), rather than a new service's own Cosmos account/database.
- The escalation confusion matrix is a report generated from this container's stored results —
  reachable through the same service, no cross-service call needed for #377/#378 later.

## Revisit if

Trajectory scoring workload ever needs a genuinely different deploy/scale profile than prompt
eval (e.g., much heavier batch jobs, different latency SLA) — that would be the point to reconsider
carving it out.
