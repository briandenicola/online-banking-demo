# Decision: Exact-pin agent-framework preview SDKs (issue #137)

**Author:** Basher
**Date:** 2026-05-13
**Status:** proposed
**Issue:** #137 — Eval-403 caused by unpinned agent-framework preview SDKs
**Branch:** squad/p2-wave-3

## Context

The eval pipeline broke when containers were rebuilt and pip resolved
`agent-framework-core 1.3.0` / `agent-framework-foundry 1.3.0` (published
2026-05-08). Last-known-good is **1.2.2** (published 2026-04-29). The 403 from
`raisvc` was *not* an RBAC issue — RBAC has been verified clean (Cognitive
Services User, Azure AI User, Cognitive Services OpenAI User, Azure AI Project
Manager are all assigned). This was SDK contract drift caused by `"*"` version
specifiers silently pulling a breaking minor release.

This has bitten the squad multiple times (commits db70575, 19d9173, 0b6255a,
65f6c9f). We need to fix it once and for all.

## Decision

### 1. Exception to the "ranges, not pins" rule

The repo standard for Python deps is `>=min,<next-major` ranges (caret pins) to
keep transitive deps resolvable. **Preview-channel SDKs are the sole exception
and MUST be exact-pinned.**

The packages this exception currently applies to:

| Package | Pinned version | Rationale |
|---|---|---|
| `agent-framework-core` | `1.2.2` | Last-known-good before 1.3.0 broke eval contract |
| `agent-framework-foundry` | `1.2.2` | Must move in lockstep with `-core` (same publisher, daily-build cadence) |
| `azure-ai-inference` | `1.0.0b9` | Beta-channel — every `bN` bump has historically been breaking |

### 2. CI guard

Added `.github/workflows/preview-sdk-pin-guard.yml` — runs on every PR that
touches `src/**/pyproject.toml`. Fails the build if any
`agent-framework[-suffix] = "*" | ">=…" | "^…" | "~…"` line is found in any
service `pyproject.toml`. Bare exact versions (`"1.2.2"`) pass.

Also added `task lint:preview-sdk-pins` (Taskfile.lint.yml) for the same check
locally before pushing.

Verified the guard:
- ✅ Green against current tree (all three services exact-pinned).
- ✅ Red when temporarily reverting `agent-framework-core` to `"*"`.

### 3. Verified resolutions

Ran `uv pip compile --python-version 3.11` against each pyproject.toml. All
three services (`ai-service`, `chatbot-service`, `account-opening-service`)
resolve cleanly with no transitive conflicts on the `mcp → pydantic → httpx`
chain. Pins do not regress dep resolution.

### 4. Bump procedure (for future)

When a future feature genuinely needs a new agent-framework release:

1. Open a *separate* PR that only bumps the pin (e.g. `1.2.2 → 1.3.1`).
2. Run `uv pip compile` on all three services to confirm no transitive break.
3. **Run the eval smoke test** before merge:
   ```bash
   kubectl exec -n banking-demo deploy/ai-service -- \
     curl -sf -X POST http://localhost:8080/evals/run -d '{"prompt_id":"smoke"}'
   ```
   (or trigger via prompt-eval-service UI). A 200 with `status:"ok"` is the
   gate.
4. Commit message MUST list old → new versions and eval test result (per
   `.squad/skills/preview-sdk-pinning/SKILL.md`).

### 5. Out of scope (follow-up tickets recommended)

The CI guard surfaced two additional preview-SDK pin violations *outside* this
incident's blast radius. Brian explicitly asked me not to touch
`budget-service`. Leaving these for a separate decision:

- `src/account-opening-service/pyproject.toml:26` — `azure-ai-contentunderstanding = "*"`
- `src/budget-service/pyproject.toml:13` — `azure-ai-inference = ">=1.0.0b9"`

Recommend filing a follow-up issue to exact-pin these too. The guard
intentionally does not flag them today (scope limited to `agent-framework-*`).

## Why this resolves #137 "for good"

Previous fixes (0b6255a, 65f6c9f) corrected the pins but added no enforcement.
The pins drifted back because contributors copy-pasted from older feature
branches or because Dependabot-style auto-bumps weren't blocked. The CI guard
makes regressing impossible without an explicit, reviewed override.

## References

- Issue: #137
- Existing fix commits: 0b6255a, 65f6c9f
- Skill: `.squad/skills/preview-sdk-pinning/SKILL.md`
- Workflow: `.github/workflows/preview-sdk-pin-guard.yml`
- Local task: `task lint:preview-sdk-pins`
