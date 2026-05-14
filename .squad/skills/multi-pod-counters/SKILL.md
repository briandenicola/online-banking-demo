# Multi-Pod Counters

## TL;DR

> **Any per-pod, in-process counter on a multi-replica deployment is broken.**
> Move it to Redis: `INCR` on a day-bucketed key (`<ns>:<metric>:{YYYY-MM-DD}` UTC) with a `36h` TTL set **only on key creation**. Increment on the **success path only**. Failures of the counter must never crash the request path.

This is the pattern that fixed issue #130 (`aiCallsToday` flicker) and the broader anti-pattern it represents.

## When to apply

You need this skill any time **all** of the following are true:

- The service runs with `replicas > 1` (or HPA `minReplicas >= 2`)
- A counter / gauge / metric is being maintained as a Python module variable, a class instance attribute, a `static int` field, or any other in-process state
- That value is read by an external consumer (HTTP endpoint, dashboard, monitoring scrape)

If the value is only read by the *same* pod that wrote it (e.g. circuit-breaker state, per-request retry count), in-process is fine.

## The anti-pattern (what NOT to do)

```python
# BAD — every pod has its own _ai_calls_today
class AnalyzerPipeline:
    def __init__(self):
        self._ai_calls_today = 0

    async def assess(self, tx):
        result = await self._foundry.run(tx)
        self._ai_calls_today += 1   # local to this pod only
        return result

@router.get("/api/admin/stats")
async def stats(state):
    return {"aiCallsToday": state.pipeline._ai_calls_today}  # flickers!
```

**Symptom in production:** dashboard refresh shows `17` then `68` then `41` then `17` again as the load balancer round-robins reads across pods. Each pod is internally consistent but they have wildly different views of "today."

## The fix (what TO do)

```python
from datetime import datetime, timezone
from typing import Optional
import redis.asyncio as redis

AI_CALLS_COUNTER_PREFIX = "ai:metrics:calls"
AI_CALLS_COUNTER_TTL_SECONDS = 36 * 60 * 60  # 36h: covers UTC day + buffer


async def _increment_ai_calls_counter(redis_client: Optional[redis.Redis]) -> None:
    """Increment today's counter. Failures are logged, never raised."""
    if not redis_client:
        return
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{AI_CALLS_COUNTER_PREFIX}:{today}"
        new_value = await redis_client.incr(key)
        if new_value == 1:
            # Set TTL only on key creation; do NOT reset on every increment.
            await redis_client.expire(key, AI_CALLS_COUNTER_TTL_SECONDS)
    except Exception as e:
        logger.warning("counter increment failed (non-fatal)", error=str(e))


async def get_ai_calls_today(redis_client: Optional[redis.Redis]) -> int:
    """Read today's count. Returns 0 if Redis is down (graceful degrade)."""
    if not redis_client:
        return 0
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{AI_CALLS_COUNTER_PREFIX}:{today}"
        count = await redis_client.get(key)
        return int(count) if count else 0
    except Exception as e:
        logger.warning("counter read failed", error=str(e))
        return 0
```

Call site:

```python
async def analyze(self, tx, redis_client=None):
    try:
        response = await self._agent.run(tx)
        result = self._parse(response)
        # Success path ONLY — after we know the AI call worked and we have a result.
        await _increment_ai_calls_counter(redis_client)
        return result
    except Exception:
        # Do NOT increment on failure. Return fallback.
        return RiskAssessment(...)
```

## The five rules

1. **Day-bucket the key.** `<ns>:<metric>:{YYYY-MM-DD}` using `datetime.now(timezone.utc).strftime("%Y-%m-%d")`. Never naive `datetime.now()`.

2. **TTL on first write only.** `INCR` returns the new value; if it returns `1`, the key was just created — call `EXPIRE`. Otherwise skip. (Equivalent: check `TTL == -1`.) Resetting TTL on every increment means the key never expires.

3. **TTL = 36h** for daily counters. Covers day boundary + 12h overlap so reads at 00:00:30 still find yesterday's key if needed for transition logic. Use 25h for hourly counters.

4. **Success-path-only increments.** After the work succeeds, before returning. Never in `except` blocks. Never on retries that ultimately fail. The counter measures completed work, not attempts.

5. **Counter failures never crash the request.** Wrap increment in its own `try/except` that logs and returns. The original work matters more than the metric. Wrap reads similarly: dashboard returns `0` (or last-known), never `500`.

## Common foot-guns

- **Forgetting to thread `redis_client` through every call site.** If three endpoints call `pipeline.assess()` and only one passes `redis_client`, two-thirds of your traffic is uncounted. `grep` for every caller.
- **Counting inside a broad `try:` that returns a fallback.** A Redis blip then turns successful AI calls into "fallback assessment" responses with `ai_unavailable` flags. The fix: either move the increment out of the broad try, or wrap it in its own swallow-all try/except.
- **Mixing `time.time()` UTC with naive `datetime.now()`.** Pick one (UTC strftime). Mixed timezones across pods → multiple keys per "day" → flicker is back.
- **Adding `EXPIRE` after every `INCR`.** Keys never expire, Redis fills up, your daily metric becomes a lifetime metric.
- **Treating Prometheus/OTEL as a fix.** They're per-process and aggregate at the collector — same problem unless your collector dedups by service+pod. Use Redis for the source of truth, then expose it as an OTEL gauge if you want.

## Variants

| Variant | Key shape | TTL |
| --- | --- | --- |
| Daily | `ns:metric:{YYYY-MM-DD}` | 36h |
| Hourly | `ns:metric:{YYYY-MM-DD}:{HH}` | 25h |
| Per-user daily (rate limit) | `ns:metric:{userId}:{YYYY-MM-DD}` | 36h |
| Sliding window | sorted set + `ZREMRANGEBYSCORE` | depends |

## Verification checklist

After deploying:

1. Refresh the dashboard endpoint **10×** in quick succession. The value must be **monotonically non-decreasing**. Any decrease = pods still disagree = counter is still in-process somewhere.
2. `kubectl exec` into **each** replica and hit the dashboard endpoint via `localhost`. All replicas must return the **same** number.
3. `redis-cli TTL <key>` → positive integer < 129600. (Confirms TTL was set, not stuck at -1.)
4. Watch across UTC midnight: a new `:{YYYY-MM-DD}` key appears, old key still present until its 36h TTL expires.
5. Trigger a known-failure path (e.g. force a 500 from the AI provider) and confirm the counter does **not** advance.

## Naming convention (this codebase)

- `ai:metrics:*` — ai-service operational metrics
- `<service>:metrics:*` — same pattern for other services
- Domain data (transactions, accounts, sessions) keeps its existing keys; do not rename.

## Related skills

- `redis-daily-counter` — the lower-level pattern this skill builds on
- `redis-stream-consumer-resilience` — defensive Redis patterns for stream consumers
- `cosmos-casing-audit` — cross-replica consistency trap, but on the storage side

## Reference

- Issue: #130 ("aiCallsToday flickers across pods")
- Fix sites:
  - `src/ai-service/app/services/anomaly_service.py` — `_increment_ai_calls_counter`, `get_ai_calls_today_from_redis`, `FoundryRiskAnalyzer.analyze`
  - `src/ai-service/app/routes/api.py` — `/detect` (must pass `state.redis_client` to `assess`); `/api/admin/stats` (read endpoint)
  - `src/ai-service/tests/test_detection.py` — `TestAiCallsCounter`
EOF
