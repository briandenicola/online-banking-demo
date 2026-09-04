# Orchestration Log: basher-130 (Redis-backed aiCallsToday Counter)

**Timestamp:** 2026-05-13T22:54:14Z  
**Agent:** basher-130  
**Model:** claude-opus-4.7  
**Mode:** background  
**Status:** COMPLETED  

## Summary

Implemented Redis-backed daily AI call counter for issue #130, replacing in-process counter that caused "17 → 68 → 17" flickering on multi-replica dashboard reads.

## Work Done

- Moved counter from in-process to Redis key `ai:metrics:calls:{YYYY-MM-DD}` (UTC)
- Used `INCR` with TTL set to 129600 seconds (36 hours) only on key creation (when INCR returns 1)
- Added `_increment_ai_calls_counter()` helper with resilient error handling
- Fixed bug in `/detect` endpoint where `pipeline.assess()` was called without `state.redis_client` (silently uncounted on-demand scores)
- Added 6 new tests in TestAiCallsCounter class
- Test results: 72 passing, 1 skipped

## Outcome

✅ **SUCCESS.** Counter now correctly aggregates across all ai-service replicas. Dashboard reads no longer flicker. No deploy step specified.

## Files Modified

- `src/ai-service/app/services/anomaly_service.py`
- `src/ai-service/app/routes/api.py`
- `src/ai-service/tests/test_detection.py`

## Decision Captured

Decision stored in `.squad/decisions/inbox/basher-130-redis-counter.md` (Redis key naming convention for all ai-service metrics).
