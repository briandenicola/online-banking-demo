# SKILL: Cross-Artifact Spec Audit

**When to use:** After `/speckit.analyze` flags findings, or when reviewing spec docs before `/speckit.implement`.

## Playbook

### 1. Load all artifacts into context

Read in parallel: spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md, and any OpenAPI contracts. You need the full picture before making changes.

### 2. Verify authoritative sources for common drift categories

| Category | Authoritative source | Common drift locations |
|---|---|---|
| .NET version / TFM | Actual `.csproj` files in repo | spec.md, plan.md, quickstart.md, research.md |
| Container count | data-model.md entity list | plan.md summary, research.md RBAC section, data-model.md indexing section |
| Event list | data-model.md Lifecycle Events table | spec.md FR-14, plan.md summary, plan.md constitution check |
| Agent count | tasks.md agent registration task | spec.md FR-5/FR-6, acceptance criteria |
| State-machine transitions | tasks.md implementation tasks (what code actually does) | data-model.md diagram + table |

**Pro tip:** Always check `.csproj` files directly — don't trust doc references to framework versions.

### 3. Separation-of-concerns gate (constitution check)

For any state-machine transition or service interaction, verify:
- Does the doc say Service A calls Service B synchronously? If so, check if spec/plan/research say "events only."
- Cross-domain writes are ALWAYS wrong in this repo. The only cross-domain mechanisms are: (a) read-only REST calls for FK validation, (b) publish-only events on `banking-events` Redis Stream.

### 4. Count consistency sweep

Run `grep -n "four\|five\|six\|seven" *.md` across the spec directory. When entities are added to a data model, the count in surrounding docs often lags behind. Common fossils:
- "four Cosmos entities" when six exist
- "four new containers" when six were added
- "six agents" when seven are registered

### 5. Decision protocol for ambiguities

When spec and data-model disagree (e.g., 2 events vs 5):
1. Check what tasks.md implements — that's the current implementation intent.
2. Check what the existing repo pattern is (e.g., do other services publish per-state-change events?).
3. Decide based on consistency with existing patterns, then update ALL artifacts to match.
4. Write a decision drop to `.squad/decisions/inbox/`.

### 6. Deliverable structure

Always produce:
- Direct edits to the spec docs (the fixes themselves)
- `REMEDIATION.md` in the spec directory with one section per finding
- A "NEW TASKS NEEDED" section for anything that requires tasks.md changes (never edit tasks.md directly)
- Decision drops for any M-level (architect decision required) findings
- History.md update with learnings

### 7. Verification

After all edits, grep for the old values to confirm they're gone:
```bash
grep -rn "account-service.*transaction-service" specs/NNN/
grep -rn "\.NET 9" specs/NNN/
grep -rn "four.*container\|four.*entit" specs/NNN/
```
