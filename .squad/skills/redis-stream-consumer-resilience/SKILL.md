# Redis Stream Consumer Resilience

## When to apply

Any time you call `XGROUP CREATE` (Redis stream consumer-group creation)
defensively at service startup. Applies to `redis.asyncio` (Python),
`StackExchange.Redis` (.NET), and any other client.

## The bug

```python
await redis_client.xgroup_create(name=STREAM, groupname=GROUP, id="0", mkstream=True)
```

This succeeds the FIRST time. Every subsequent call raises:

```
redis.exceptions.ResponseError: BUSYGROUP Consumer Group name already exists
```

If uncaught — and it usually is, because "create at startup" feels like
a one-shot — this kills the consumer task immediately on every restart
after the first deploy. The service appears healthy (`/healthz` 200,
Redis ping 200) but processes zero messages. **A "data is missing"
dashboard symptom can be a dead consumer underneath.**

## The fix

```python
try:
    await redis_client.xgroup_create(name=STREAM, groupname=GROUP, id="0", mkstream=True)
    logger.info(f"Created consumer group {GROUP} on stream {STREAM}")
except redis.ResponseError as e:
    if "BUSYGROUP" in str(e):
        logger.info(f"Consumer group {GROUP} already exists — resuming")
    else:
        logger.error(f"Failed to create consumer group: {e}")
        raise
```

Same shape applies to `xgroup_createconsumer` (returns 0 if exists, but
some client versions raise) and `xgroup_setid`.

## How to detect it

Inside an in-cluster pod with Redis access:

```python
info = await r.xinfo_groups(STREAM)
# Look for: lag > 0, last-delivered-id far behind current XLEN tip,
# pending = 0 (means messages aren't even being read, let alone
# failing to ACK).
pending = await r.xpending(STREAM, GROUP)
```

A consumer with `lag=N, pending=0` and `last-delivered-id` from hours
ago is almost certainly dead — the loop never started.

## Related observability gap

`/readyz` typically checks Redis connectivity, not consumer-task
liveness. Add:

```python
checks["consumer_task"] = consumer_task is not None and not consumer_task.done()
```

This would have caught the dead-consumer state in seconds instead of
days.

## Reference

- Bug: `src/ai-service/app/services/anomaly_service.py:643` (pre-fix)
- Fix: commit `c241a18` (issue #123)
- Detection pattern used: workload-identity pod + Entra-auth Redis
  client (see `redis-from-workload-identity-pod` skill / basher
  history #119 entry).
