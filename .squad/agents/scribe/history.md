# Project Context

- **Project:** online-banking-demo
- **Created:** 2026-05-05

## Core Context

Agent Scribe initialized and ready for work.

## Recent Updates

📌 Team initialized on 2026-05-05

## Sessions

### 2026-05-14 — Foundry Connection Schema Debugging + Hygiene Pass (Issues #138 / #141)

**Context:** Foundry managed VNet TF debugging session burned ~35 minutes across 3 Basher rounds due to pattern-matching from broken TF instead of consulting official Microsoft samples first. Final resolution required sample-first discipline.

**Issues Addressed:**
- **#138 / #141:** Foundry managed VNet HTTP 400 errors on connection creation
- Root cause: Connection schema mismatch with Microsoft's official reference implementation
  - Storage: Wrong category `AzureStorage` → `AzureStorageAccount`
  - Cosmos: Wrong category `AzureCosmosDB` → `CosmosDb`
  - AI Search: Wrong target format (resource ID → HTTPS URL)
  - All three: Invalid property `useWorkspaceManagedIdentity` (doesn't exist in API schema)

**Three Basher Rounds:**
1. **R1 (dismissed):** Hypothesis that `useWorkspaceManagedIdentity: true` was required. Not the issue.
2. **R2 (partially correct, abandoned):** Target-URI format hypothesis. Partially correct but coordinator strategy changed before completion.
3. **R3 (convergence):** Fetched Microsoft's official sample (foundry-samples/18-managed-virtual-network); identified correct schema. Fix committed in `b99f3d7`, `ac7dede`, `ef20aab`.

**Process Lesson Codified:**
- Established sample-first discipline for all Microsoft service TF tasks
- Updated Basher charter with mandatory sample-first requirement
- Added banner to SKILL workflow highlighting source-of-truth discipline
- Background agents unable to terminate must be considered abandoned on strategy change

**Commits:**
- `b99f3d7`: ai-connections.tf schema corrections (storage, cosmos, AI Search)
- `ac7dede`: Basher R3 charter + discipline update
- `ef20aab`: Coordinator sample-first rule banner + charter enforcement

**Hygiene Passed:**
- ✅ Merged decisions inbox (2 files: coordinator directive + basher RCA) into `.squad/decisions.md`
- ✅ Compressed `.squad/agents/basher/history.md` (197KB → 107KB, 45% reduction); preserved Foundry sample references
- ✅ Preserved all recent 2026-05-13 and 2026-05-14 entries; archived pre-2026-05 sessions into bullet summary
- ✅ Deleted inbox files post-merge
- ✅ Decisions.md (355KB) retained; all Foundry entries kept discoverable

### 2026-06-05 — Turk Seed URL Output (Orchestration & Documentation)

**Context:** Turk (Backend Dev) implemented seed script URL output. Scribe processed orchestration logs and decision documentation.

**Work Completed:**
- ✅ Created `.squad/orchestration-log/2026-06-05T19:26:26Z-turk.md` (workflow tracking)
- ✅ Created `.squad/log/2026-06-05T19:26:26Z-seed-url-output.md` (brief session log)
- ✅ Merged `.squad/decisions/inbox/turk-seed-url-output.md` → `.squad/decisions.md`
- ✅ Deleted inbox file post-merge
- ✅ Verified decisions.md: 400KB, 4 entries; no entries >30 days old (archival not required)
- ✅ Verified cross-agent notes: none applicable

## Learnings

Initial setup complete. Scribe hygiene discipline established 2026-05-14.
Turk orchestration processed 2026-06-05.
