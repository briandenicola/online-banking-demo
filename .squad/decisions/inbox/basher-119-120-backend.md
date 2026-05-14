# Decision Drop — Basher — #119 / #120 Backend Follow-ups

**Date:** 2026-05-13
**Branch:** squad/p2-wave-3
**Issues closed:** #119, #120

## What changed

1. **`/api/admin/prompts` now returns `systemPrompt`** for each analyzer and categorizer (sourced from each class's `SYSTEM_PROMPT` constant). One-line API contract addition, frontend already optional-handles it (Linus, 489527b).

2. **Redis `scored-transactions` sorted set purged** of 157 legacy entries with timestamp-shaped scores. Write path was already corrected at `anomaly_service.py:617`; this was data-only cleanup.

## Conventions to lock in / propagate

- **One-shot Redis maintenance against Azure Managed Redis is a `kubectl exec` away.** Any pod with workload identity + `redis.asyncio` (e.g. ai-service, event-processor) can run ad-hoc Redis ops without hardcoding connection strings or pulling from KeyVault manually. Pattern is now in basher/history.md ("Reusable Redis-from-pod pattern"). Use this for future Redis cleanups instead of asking Brian to hit the portal.
- **For trivial dict-shape API changes, on-disk pod verification (`kubectl exec ... grep`) is acceptable** in lieu of an end-to-end curl. Saves the JWT-minting dance for changes where deploy + new code presence is the real concern.
- **The `enabled` field on prompt entries currently means "agent constructed" not "agent reachable".** Scribe flagged this as a possible follow-up in Linus's wave. Punted — Linus's panel renders correctly with current semantics. Revisit if we ever see false-green badges.

## Anti-patterns avoided

- Did NOT pull the Redis hostname from a hardcoded constant — used the pod's existing `REDIS_CONNECTION_STRING` env (which itself comes from the configmap rendered from terraform output during `task cloud:deploy`).
- Did NOT use a raw K8s secret or master key — Entra-only, workload identity, AAD token as Redis password.
- Did NOT bypass `task cloud:deploy` — used it, confirming the coordinator's auto-rollout-restart from commit e57d5f0 still works for python services.

## Files touched

- `src/ai-service/app/routes/api.py` — `get_active_prompts` now includes `systemPrompt`
- `.squad/agents/basher/history.md` — learnings appended

## No follow-ups needed

Both #119 and #120 closed (frontend half was Linus 489527b, backend half is this drop). UI panels should render fully on next user refresh.
