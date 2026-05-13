## Decision Drop: #123 — AI dashboard tiles stuck at 0 post-purge

**Status:** ✅ Fixed & verified live (onlinebankingdemo.bjdazure.tech)
**Date:** 2026-05-13
**Author:** Basher
**Branch/Commit:** `squad/p2-wave-3` / `c241a18`

### What the issue thought it was

A follow-up to #119: the Redis purge cleared `scored-transactions` (157
poisoned entries), so the **Avg Risk Score / Total Scored** tiles being
0 was "expected pending recovery." The **AI Calls Today** tile being 0
was suspected as either a missing increment or ai-service not being
called at all.

### What it actually was — TWO root causes

**1. Real bug: ai-service consumer task was dead.**

`consume_redis_stream()` calls `xgroup_create(...)` at startup. The
first time, this creates the `anomaly-consumer-group`. **Every
subsequent restart**, it raises `redis.ResponseError: BUSYGROUP
Consumer Group name already exists`. The exception was uncaught, the
asyncio task created in `lifespan()` died before entering its `while
True` loop, and **no transactions were ever scored**. No `/score` HTTP
endpoint exists — all scoring flows through this stream consumer — so
"AI Calls Today: 0" was literal: the analyzer was never invoked.

This bug has been latent for who knows how long. It only surfaced with
the purge because the dashboard previously displayed stale (poisoned)
data that masked the dead consumer. Confirmed via Redis state:
`anomaly-consumer-group` had `lag=199, last-delivered-id` from ~21h
prior; `event-processor-group` (separate consumer, separate code path)
had `lag=0`.

**Fix:** wrap `xgroup_create` in try/except, ignore BUSYGROUP, log
"resuming existing group". Two lines that should have been there from
day one.

**2. Recovery: 155 historical transactions in Cosmos never re-flowed.**

With the consumer revived, new transactions score on ingest, but the
existing Cosmos backlog had no path back through the stream.

**Fix:** new admin endpoint `POST /api/admin/replay-events?limit=N`
on transaction-service. Reads all transactions from Cosmos (drains
all pages — not the single-page truncation pattern that bit us in
#125), re-publishes each as a `TransactionCreated` event onto
`banking-events`. ai-service consumes and scores them naturally. No
new dependencies in ai-service, full reuse of the existing scoring
path, reusable for any future Redis purge or schema fix.

### Why not [Alternative X]

1. **Add Cosmos SDK to ai-service + backfill endpoint there.** Bloats
   ai-service's surface area with persistence concerns it doesn't
   own. transaction-service already has Cosmos + Redis publisher.
2. **One-shot pod script reading Cosmos directly.** Works but isn't
   discoverable or reusable. Next on-call would be cargo-culting the
   workload-identity pod recipe again. An admin endpoint is one
   `curl` for any future maintenance.
3. **Ignore the consumer crash and just document the 0s as
   "expected post-purge."** Wrong — the consumer was dead and
   *would never recover* without the BUSYGROUP fix. Subsequent
   organic transactions would not have moved the tiles.

### Verified live

```
before: avgRiskScore=0.00, totalScored=0,  aiCallsToday=0
after : avgRiskScore=0.27, totalScored=84+, aiCallsToday=17/68 (per-pod)
flagged: 27 → 44 (high-risk replays caught and flagged correctly)
```

### Operational notes

- Demoted-to-admin: `e2e-default@banking-demo.com` was promoted in
  Cosmos via the workload-identity pod pattern (history line for
  reference). Demotion left as-is; no harm in a demo cluster but
  flag for next on-call.
- New gateway route `/api/admin/replay-events` → transaction-service
  must precede the generic `/api/admin` → ai-service rule in
  `cluster-config/istio/gateway/default-ingress.yaml`. Already
  ordered correctly.

### Follow-ups (NOT blocking #123 — file as separate)

1. **`aiCallsToday` is per-pod in-memory.** With N replicas the
   dashboard flickers between pod values (saw 68 → 8 → 17 across
   consecutive polls during recovery — round-robin between two pods).
   Should be a Redis `INCR` against a `ai-calls:YYYY-MM-DD` key with
   `EXPIRE`. Self-resetting, accurate across replicas. ~10 lines.
2. **No DLQ instrumentation visibility.** If the consumer ever dies
   silently again (some other unhandled exception type), there's no
   alert. Worth a `/readyz` enhancement that checks the consumer
   task is alive (`not consumer_task.done()`).
3. **`xreadgroup` count=10 + 1s block** is fine for steady state but
   slow for backfills (took ~12min to drain 155 events @ ~5s per
   Foundry call). Acceptable for one-shot maintenance, not a
   problem to fix.

### Related Issues

- **#119** Redis purge — done, this is the unmasked latent bug
- **#125** Cosmos casing serializer fix — orthogonal, still pending
- **#120** systemPrompt exposure — unrelated, already shipped
