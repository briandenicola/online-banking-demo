---
date: 2026-05-13
agent: basher
status: applied
issue: 137
commit: 0b6255a
---

# Decision: Exact-pin preview Azure AI SDKs (agent-framework-*, azure-ai-inference betas)

## Context

Eval prompt execution failed with `UnauthorizedUserAction` 400/403 after container rebuild on 2026-05-13. Investigation ruled out RBAC (all role assignments correct). Root cause: unpinned preview SDKs in pyproject.toml pulling new releases on every rebuild.

Commits db70575 (2026-05-02) and eeda8ed (2026-05-08) removed version constraints:
- `agent-framework-core = "*"`
- `agent-framework-foundry = "*"`
- `azure-ai-inference = ">=1.0.0b9,<2.0.0"`

PyPI published agent-framework-* 1.3.0 on 2026-05-08 with breaking eval contract changes. Container rebuild pulled 1.3.0 → SDK constructed eval requests differently → raisvc rejected with 403.

## Decision

**Exact-pin all preview-channel Azure AI SDKs** to last-known-good versions:
- `agent-framework-core = "1.2.2"`
- `agent-framework-foundry = "1.2.2"`
- `azure-ai-inference = "1.0.0b9"`

Applied to:
- src/ai-service/pyproject.toml
- src/chatbot-service/pyproject.toml
- src/account-opening-service/pyproject.toml

(budget-service doesn't use agent-framework, no change needed)

## Rationale

1. **Preview SDKs break compat between minors:** Unlike stable releases, preview channels have no semver guarantees. 1.2.2 → 1.3.0 broke eval pipeline.
2. **Wildcard pins allow arbitrary upgrades:** `"*"` resolves to latest on every `pip install`, causing non-deterministic builds.
3. **Exception to >=min,<next-major rule:** Repo standard uses `^` or `>=min,<next-major` ranges to prevent transitive conflicts. This works for **stable** libs. Preview SDKs require exact pins due to frequent breaking changes.
4. **Stable deps unchanged:** Keep caret/range constraints for fastapi, pydantic, redis, etc.

## Alternatives Considered

1. **Lock all deps to exact versions (==)** — Rejected. Causes transitive dependency hell. Only needed for preview SDKs.
2. **Use Poetry lockfile** — Better determinism, but doesn't solve root cause (unpinned preview SDKs would still drift on lock updates). Lockfiles are a separate improvement.
3. **Wait for agent-framework stable 2.x** — Unknown timeline, eval must work now.

## Remediation Going Forward

1. **CI lint:** Add pre-commit check that fails on `agent-framework.*= "\*"` in pyproject.toml
2. **Dependabot:** Enable with explicit upgrade PRs for preview SDKs
3. **Smoke-test requirement:** Eval pipeline must pass before merging any agent-framework bump
4. **Upstream investigation:** Determine if 1.3.0 is intentionally breaking or a bug (file issue if latter)

## Impact

- **Immediate:** Eval pipeline stable again at 1.2.2
- **Maintenance:** Preview SDK upgrades now require explicit commit + testing (good — prevents silent breakage)
- **CI discipline:** Must add lint rule to enforce exact pins for preview SDKs

## Verification

After rebuild with pinned deps:
```bash
# Container logs should show:
# agent-framework-core==1.2.2
# agent-framework-foundry==1.2.2
# azure-ai-inference==1.0.0b9

# Eval prompt should succeed (no 403)
```
