---
date: 2026-09-04
author: Rusty (Platform/Infra)
status: proposed
component: epic/banker-copilot
issue: 332
---

# `copilot-sessions` is partitioned by `/sessionId`, not `/id`

## What

Epic §2.4 states the Phase 2 containers as
`copilot-sessions (PK /id)`, `copilot-artifacts (PK /sessionId)`, and §8.0 adds
`copilot-traces (PK /runId)`.

I built `copilot-traces` and `copilot-artifacts` exactly as specified. I built
**`copilot-sessions` with `partition_key_paths = ["/sessionId"]`**, deviating
from §2.4.

## Why

§2.4 was right for the container it was describing and is stale for the container
we are building. `banker-copilot-service` stores **two** document types in
`copilot-sessions`, discriminated by `docType`: the session, and every **run**
inside it. A run document's `id` is the *run* id.

Under `/id`:

- each run lands in its own logical partition;
- a session and its runs are therefore *not* co-located, which removes the only
  reason to put them in one container in the first place;
- `get_run` must be a cross-partition query forever, on the request path.

Under `/sessionId` a session and all of its runs share one partition, which is
what the co-location was for. **Nothing regresses for session documents:**
`Session.to_document()` sets `sessionId = id`, so a session's partition key and
its id are the same value and the point read
`read_item(item=sessionId, partition_key=sessionId)` behaves exactly as it would
have under `/id`.

This is also what the service already assumes. `CosmosSessionStore`'s docstring
says *"partitioned by `/sessionId`"* and `get_session` passes
`partition_key=session_id`. The implementation and the epic disagreed, and the
implementation had the analysis behind it — the same basis on which Danny made
design §5.3 authoritative over the epic for the approval schema. I am following
the analysis and filing the deviation rather than silently following the older
document.

## The reason this needed a decision rather than a quiet fix

A partition-key mismatch does not fail. Cosmos returns **zero rows, not an
error**, and a document whose declared partition-key path is absent lands in the
*undefined* partition rather than being rejected. An empty artifact pane and a
correctly-working-but-empty one are the same screen. This is the identical
failure mode Danny's §5.2 ruling identified for field paths, one level up, and it
is why the container keys need one home.

## Two related defects found by reading the store code against the Terraform

Neither is mine to fix — both are in `src/banker-copilot-service/`, reported to
Turk — but they are recorded here because they are the same class:

1. **`Artifact.to_document()` persists snake_case while `list_artifacts` queries
   camelCase.** `asdict()` yields `run_id` / `session_id`; the query reads
   `c.runId`. `Session` and `Run` explicitly re-add the camelCase keys after
   their `asdict()`, `Artifact` does not. Result: zero rows, no error, and every
   artifact in the undefined partition because `/sessionId` is absent from the
   document.
2. **`list_artifacts` passes `partition_key=run_id` against a `/sessionId`
   container.** Scopes the read to a partition that does not exist.

## Index directions — an ordinary bug hiding behind the same silence

`list_artifacts` orders `ORDER BY c.revision` **ascending**. I had declared the
composite index as `(runId ASC, revision DESC)`.

A Cosmos composite index serves an `ORDER BY` only when the directions match
exactly, or are exactly reversed for *every* path. `(ASC, DESC)` therefore does
**not** serve `WHERE runId = @r ORDER BY revision ASC`. Like the wrong field path,
this returns *correct rows* — just by scanning — so it is invisible at demo volume
and expensive later. `copilot-artifacts` now declares both directions.

This is the Phase 1 `(status, terminalReason, terminalAt)` lesson recurring with a
new variable: it is not enough for every filter and ORDER BY path to appear in the
composite index in order. **The sort directions have to line up too.**

## What I need

Danny to ratify the `/sessionId` deviation and, if accepted, correct epic §2.4 so
the epic does not continue to assert `/id` — one home per fact, per §5.2.1.
