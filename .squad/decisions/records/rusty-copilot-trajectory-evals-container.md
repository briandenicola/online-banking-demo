---
date: 2026-09-15
author: Rusty (Platform/Infra)
status: decided
component: prompt-eval-service
issue: 376
---

# Trajectory evals use `copilot-trajectory-evals` partitioned by `/sessionId`

## Decision

Store trajectory evaluation records in the `copilot-trajectory-evals` Cosmos
container with `/sessionId` as its partition key.

## Rationale

Trajectory eval records are copilot/session-shaped: each replay produces scored
records for one session. Session partitioning keeps those records together so
confusion-matrix aggregation can read a replay's results within one logical
partition, following the existing session-oriented Cosmos conventions.
