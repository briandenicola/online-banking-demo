# Redis Daily Counter Pattern

## When to Apply

Any time you need a **per-day metric** that must be **cross-replica consistent** in a multi-pod deployment. Examples:
- AI API calls per day
- Rate limits (requests per user per day)
- Usage tracking (transactions processed per day)
- Feature quotas (searches per day, exports per day)

**Don't use in-memory counters** if:
- HPA min > 1 (multiple replicas running)
- The metric is read from an admin dashboard or monitoring endpoint
- You need accurate totals across pod restarts

**Symptom of in-memory counter:** Dashboard value "flickers" between different numbers on refresh (each pod returns its own local count).

## The Pattern

### Python (redis.asyncio)

```python
from datetime import datetime, timezone
import redis.asyncio as redis

async def increment_daily_counter(redis_client: redis.Redis, counter_name: str):
    """Increment today's counter and set TTL if needed."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counter_key = f"{counter_name}:{today}"
    
    # Increment the counter
    await redis_client.incr(counter_key)
    
    # Set TTL to 36 hours on first increment (covers day boundary + buffer)
    ttl = await redis_client.ttl(counter_key)
    if ttl == -1:  # Key exists but has no TTL
        await redis_client.expire(counter_key, 36 * 60 * 60)

async def get_daily_counter(redis_client: redis.Redis, counter_name: str) -> int:
    """Get today's counter value."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counter_key = f"{counter_name}:{today}"
    
    count = await redis_client.get(counter_key)
    return int(count) if count else 0
```

### Usage Example (AI Service)

```python
# In FoundryRiskAnalyzer.analyze()
async def analyze(self, transaction: dict, redis_client: Optional[redis.Redis] = None) -> RiskAssessment:
    try:
        # ... do the AI call ...
        response = await self._agent.run(user_message, session=session)
        
        # Increment counter on SUCCESS path only (not 429s, not 500s)
        if redis_client:
            await increment_daily_counter(redis_client, "ai:metrics:calls")
        
        return result
    except Exception as e:
        # Don't increment on failure
        return fallback_result

# In dashboard endpoint
@router.get("/api/admin/dashboard")
async def get_dashboard(state: AnomalyState = Depends(get_anomaly_state)):
    ai_calls_today = await get_daily_counter(state.redis_client, "ai:metrics:calls")
    return {"aiCallsToday": ai_calls_today}
```

## Key Design Choices

### Why 36 hours TTL?

Covers UTC day boundary + buffer. If you set TTL at 23:59 UTC, the key survives into the next day for 1 hour. 36 hours gives a full day + 12 hours overlap.

Alternative TTLs:
- **25 hours** — if you need per-hour granularity (`ai:metrics:calls:{YYYY-MM-DD}:{HH}`)
- **7 days** — if you want to keep a week of daily history (`ai:metrics:calls:{YYYY-MM-DD}` keys from the last 7 days)

### Why check TTL == -1?

Redis `INCR` **creates the key** but **doesn't set TTL**. You need a separate `EXPIRE` call.

TTL return values:
- `-2` — key doesn't exist
- `-1` — key exists but has **no TTL** (will never expire)
- `N` (positive) — key expires in N seconds

By checking `ttl == -1`, we ensure the first caller sets the TTL and subsequent callers skip it (idempotent).

### Why increment ONLY on success path?

If you increment on every attempt (including retries, 429s, 500s), the counter becomes meaningless. It counts "attempts" not "actual work done."

**Rule:** Increment **after** the work succeeds, **before** returning the result. Don't increment in `except` blocks.

### Why UTC strftime?

Always use `datetime.now(timezone.utc)` (not `.now()` alone). This ensures:
- Consistent day boundaries across all replicas (no timezone drift)
- Matches logging/observability timestamps (OTEL/Serilog use UTC)
- Works correctly when pods run in different time zones (rare but possible in multi-region)

## Per-Hour Variant

If you need finer granularity:

```python
from datetime import datetime, timezone

async def increment_hourly_counter(redis_client: redis.Redis, counter_name: str):
    now = datetime.now(timezone.utc)
    hour_key = f"{counter_name}:{now.strftime('%Y-%m-%d')}:{now.strftime('%H')}"
    
    await redis_client.incr(hour_key)
    
    ttl = await redis_client.ttl(hour_key)
    if ttl == -1:
        await redis_client.expire(hour_key, 25 * 60 * 60)  # 25 hours (covers hour overlap)

async def get_hourly_counter(redis_client: redis.Redis, counter_name: str) -> int:
    now = datetime.now(timezone.utc)
    hour_key = f"{counter_name}:{now.strftime('%Y-%m-%d')}:{now.strftime('%H')}"
    
    count = await redis_client.get(hour_key)
    return int(count) if count else 0
```

## Per-User Variant

If you need per-user counters:

```python
async def increment_user_daily_counter(redis_client: redis.Redis, counter_name: str, user_id: str):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counter_key = f"{counter_name}:{user_id}:{today}"
    
    await redis_client.incr(counter_key)
    
    ttl = await redis_client.ttl(counter_key)
    if ttl == -1:
        await redis_client.expire(counter_key, 36 * 60 * 60)
```

**Use case:** Rate limiting per user (e.g., "100 AI calls per user per day").

## Verification Checklist

After deploying a Redis daily counter fix:

1. **Dashboard refresh 10x** — value should be monotonically non-decreasing (no flicker)
2. **Cross-pod check** — `kubectl exec` into each pod and hit the dashboard endpoint directly. All pods should return the **same** value.
3. **TTL visible** — `redis-cli TTL <counter_key>` should show a positive number (seconds remaining)
4. **Day rollover** — At UTC midnight, verify a new key is created with the new date. Old key should still exist (until TTL expires).
5. **Counter semantics** — Manually trigger a few operations and confirm the counter increments correctly (only on success).

## Related Skills

- **redis-stream-consumer-resilience** — Defensive Redis patterns for XGROUP CREATE
- **cosmos-casing-audit** — Another cross-replica consistency trap (but storage-side, not in-memory)

## Reference

- Issue: #130
- Commit: 8fc8c76
- Original in-memory counter: `src/ai-service/app/services/anomaly_service.py` (pre-fix)
