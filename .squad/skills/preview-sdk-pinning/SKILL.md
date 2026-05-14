---
name: "preview-sdk-pinning"
description: "Managing preview/beta Azure AI SDK dependencies in Python services to prevent build-time drift"
domain: "dependency-management"
confidence: "high"
source: "earned (eval-403 incident, issue #137, commit 0b6255a)"
---

## Context

Preview-channel Azure AI SDKs (agent-framework-*, azure-ai-inference betas, azure-ai-projects prereleases) do **not** follow semantic versioning guarantees. Minor version bumps often introduce breaking API changes. Using wildcard (`"*"`) or open-ended ranges (`">=1.0.0b9,<2.0.0"`) in pyproject.toml causes non-deterministic builds — every `pip install` or container rebuild resolves to the latest PyPI release, potentially breaking working code.

**Incident example (eval-403):**
- pyproject.toml had `agent-framework-core = "*"`
- PyPI published 1.3.0 (2026-05-08) with eval contract changes
- Container rebuild (2026-05-13) pulled 1.3.0 → eval pipeline failed with 403
- Roll back to 1.2.2 restored functionality

This skill applies when:
- Adding any Azure AI SDK dependency with "preview", "beta", "rc", or version `< 1.0.0`
- Maintaining services that use `agent-framework-core`, `agent-framework-foundry`, `azure-ai-inference` betas
- Reviewing pyproject.toml changes that touch preview SDK versions

## Patterns

### 1. Exact-Pin Preview SDKs

**Rule:** All preview-channel Azure AI SDKs use exact version pins (no ranges, no wildcards).

```toml
# ✅ CORRECT
agent-framework-core = "1.2.2"
agent-framework-foundry = "1.2.2"
azure-ai-inference = "1.0.0b9"

# ❌ WRONG (allows arbitrary upgrades)
agent-framework-core = "*"
agent-framework-foundry = ">=1.2.0,<2.0.0"
azure-ai-inference = ">=1.0.0b9,<2.0.0"
```

**Exception to repo standard:** Normal Python deps use `^` or `>=min,<next-major` ranges to prevent transitive conflicts (per `.squad/decisions.md` memory). Preview SDKs are the **only exception** — exact pins prevent silent breakage.

### 2. Query PyPI for Last-Known-Good Version

Before pinning, identify the version published **before** the breaking change:

```bash
# Get all releases sorted chronologically
curl -s https://pypi.org/pypi/agent-framework-core/json \
  | jq -r '.releases | to_entries | .[] | "\(.key): \(.value[0].upload_time)"' \
  | sort -V

# Filter releases after a specific date
curl -s https://pypi.org/pypi/agent-framework-core/json \
  | jq -r '.releases | to_entries | .[] | select(.value[0].upload_time > "2026-05-13T00:00:00") | "\(.key): \(.value[0].upload_time)"'

# Get just version numbers (for quick listing)
curl -s https://pypi.org/pypi/agent-framework-core/json \
  | jq -r '.releases | keys | .[]' | sort -V | tail -10
```

**Pattern:** Use the last version published before your container stopped working (look at Docker build timestamps or deployment logs).

### 3. Document Every Preview SDK Upgrade

When bumping preview SDKs, commit message MUST include:
- Old version → new version
- Why the upgrade is needed (new feature, security patch, bug fix)
- Test results (especially eval pipeline if touching agent-framework-*)

```bash
git commit -m "build(deps): bump agent-framework-core 1.2.2 → 1.3.1

Upgrade for async streaming support in FoundryAgent.

Tested:
- Eval pipeline: ✅ (prompt-134 passes)
- Chatbot streaming: ✅ (no token lag)
- AI service anomaly detection: ✅

Refs: #142
"
```

### 4. Stable Deps Keep Range Pins

Do **not** exact-pin stable libraries — transitive dependency conflicts will occur.

```toml
# ✅ CORRECT (stable libs use ranges)
fastapi = "^0.115.0"
pydantic = "^2.9.0"
redis = "^5.2.1"
azure-identity = "^1.17.0"  # stable API

# Preview SDKs get exact pins
agent-framework-core = "1.2.2"

# ❌ WRONG (exact-pinning everything causes dep hell)
fastapi = "0.115.3"
pydantic = "2.9.2"
redis = "5.2.1"
```

**Rule of thumb:** If the package version is `< 1.0.0`, has "beta" / "rc" suffix, or is in the `azure-ai-*` preview family, exact-pin it. Everything else uses ranges.

## Examples

### Multi-Service Repin (eval-403 fix)

```bash
# 1. Query PyPI for last-good version (before 2026-05-13)
curl -s https://pypi.org/pypi/agent-framework-core/json \
  | jq -r '.releases | to_entries | .[] | "\(.key): \(.value[0].upload_time)"' \
  | sort -V

# Result: 1.2.2 published 2026-04-29, 1.3.0 published 2026-05-08 (breaking)
# Last-known-good: 1.2.2

# 2. Edit all affected services
vi src/ai-service/pyproject.toml
vi src/chatbot-service/pyproject.toml
vi src/account-opening-service/pyproject.toml

# Change:
#   agent-framework-core = "*"  →  "1.2.2"
#   agent-framework-foundry = "*"  →  "1.2.2"
#   azure-ai-inference = ">=1.0.0b9,<2.0.0"  →  "1.0.0b9"

# 3. Commit with detailed message
git add src/*/pyproject.toml
git commit -m "fix(deps): exact-pin agent-framework preview SDKs to stop daily-build drift"
```

### Adding New Preview Dependency

```toml
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.115.0"
pydantic = "^2.9.0"

# New preview SDK — exact-pin from day 1
azure-ai-contentunderstanding = "0.1.0a3"  # ← exact version
```

## Anti-Patterns

### ❌ Wildcard Pins on Preview SDKs

```toml
agent-framework-core = "*"
azure-ai-inference = "*"
```

**Why wrong:** Every `pip install` resolves to latest PyPI. Non-deterministic builds, silent breakage on container rebuild.

### ❌ Open-Ended Beta Ranges

```toml
azure-ai-inference = ">=1.0.0b9,<2.0.0"
```

**Why wrong:** Still allows arbitrary beta upgrades (b9 → b10 → b11, all with breaking changes). Lock to exact beta.

### ❌ Exact-Pinning Stable Libs

```toml
fastapi = "0.115.3"
pydantic = "2.9.2"
```

**Why wrong:** Transitive deps (uvicorn, starlette, etc.) need wiggle room. Exact pins cause "cannot resolve dependency" errors. Only preview SDKs get exact pins.

### ❌ Upgrading Preview SDKs Without Testing Eval Pipeline

```bash
# Someone bumps agent-framework-core 1.2.2 → 1.4.0 without testing
# Eval pipeline breaks in production
```

**Why wrong:** Eval contract is fragile. Always smoke-test `POST /evals/run` after upgrading agent-framework-*.

## Remediation Checklist (When Preview SDK Breaks)

1. **Identify breaking version:**
   - Check Docker image build timestamp
   - Query PyPI for releases published after last-known-good build
2. **Roll back to last-known-good:**
   - Find version published before breakage date
   - Exact-pin in all affected pyproject.toml files
3. **File issue:**
   - Document symptoms, RBAC ruling-out, SDK drift timeline
   - Reference commits that introduced unpinning
   - Link PyPI release history
4. **Add CI protection:**
   - Pre-commit lint: fail on `agent-framework.*= "\*"`
   - Dependabot: explicit upgrade PRs for preview SDKs
   - Required smoke-test: eval pipeline must pass before merge
5. **Upstream investigation:**
   - Is new version intentionally breaking? (changelog review)
   - File bug if SDK broke without notice

## References

- **Incident:** #137 (eval-403 caused by agent-framework 1.3.0 drift)
- **Fix commit:** 0b6255a (exact-pin to 1.2.2)
- **CI guard (enforces this skill):** `.github/workflows/preview-sdk-pin-guard.yml`
- **Local check:** `task lint:preview-sdk-pins`
- **Decision:** `.squad/decisions/inbox/basher-137-preview-sdk-pinning.md`
- **Repo standard (exception):** `.squad/decisions.md` line 4250 (normal deps use `>=min,<next-major`, preview SDKs are exception)
