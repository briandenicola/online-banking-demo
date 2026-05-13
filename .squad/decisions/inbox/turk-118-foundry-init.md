# Decision: Explicitly declare `aiohttp` for Python services using agent-framework-foundry

**Status:** ✅ Implemented (ai-service)  
**Date:** 2026-05-13  
**Author:** Turk (Backend)  
**Issue:** #118  
**Commit:** 0cb17b8 (squad/p2-wave-3)

## Context

The `Check Foundry Status` admin panel reported both `transaction-categorizer` and `risk-assessor` agents as 🔴 ERROR / "Agent not initialized" on https://onlinebankingdemo.bjdazure.tech.

After ruling out (1) missing Foundry-side agents and (3) a faulty health check, root cause was (2): ai-service main container failed to instantiate `FoundryAgent` at lifespan startup with:

```
❌ Foundry initialization failed: No module named 'aiohttp'
```

`agent-framework-foundry`'s `FoundryAgent` uses `aiohttp.ClientSession` internally but does **not** declare it as a transitive dependency. The `try/except` in `anomaly_service.lifespan` swallowed the ImportError, leaving both agents with `_ready=False`.

## Decision

For every Python service that depends on `agent-framework-foundry` (or any Azure AI SDK that uses HTTP under the hood), **explicitly add `aiohttp` to `pyproject.toml`**. Do not rely on it being pulled in transitively.

Applied to: `src/ai-service/pyproject.toml` (`aiohttp = "^3.10.0"`).
Already correct: `src/chatbot-service/pyproject.toml`, `src/account-opening-service/pyproject.toml`.

## Rationale

- This is the **third time** the same missing-dependency pattern has surfaced (account-opening-service → chatbot-service → ai-service). It will keep recurring otherwise.
- `try/except Exception as e: logger.error(...)` in lifespan masks ImportError — by the time the symptom shows up in the UI, the cause is far removed. Better to declare deps up-front.
- Cost is negligible (one wheel, ~1MB).

## Alternatives Considered

1. **Pin `agent-framework-foundry` to a version that bundles aiohttp** — no such version published; relying on a future SDK fix is unreliable.
2. **Make Foundry init failures fatal (raise instead of log)** — would crash all services on any transient Foundry issue. Rejected.
3. **Add a startup smoke-call against the Foundry endpoint that fails-fast** — useful but orthogonal; doesn't replace the missing dep.

## Follow-ups (out-of-scope here, flagged for team)

- **Linus / Frontend:** the admin "Check Foundry Status" panel correctly surfaced the failure — no UI changes needed. Health-check code (`_check_agent` in `app/routes/api.py`) is also correct.
- **Basher / Cross-service patterns:** worth adding a CI lint or doc convention: "Any service that imports `agent_framework_foundry` MUST list `aiohttp` in pyproject.toml". A simple grep-based pre-commit would suffice.
- **Deploy ergonomics:** `task cloud:deploy` does not restart pods when the kustomize manifest is unchanged but the `:latest` image was rebuilt. Either (a) tag images with the git short-SHA in `_images:update`, or (b) add an automatic `kubectl rollout restart` for changed services. This affects every "rebuild and redeploy" workflow, not just ai-service.

## Verification

```
$ kubectl logs deploy/ai-service -c ai-service | grep Foundry
✅ Foundry risk agent created (persistent)
✅ Foundry categorizer agent created (persistent)

$ curl /api/admin/foundry-status
{"status":"ok","agents":{"transaction-categorizer":{"status":"ok"},"risk-assessor":{"status":"ok"}}}
```
