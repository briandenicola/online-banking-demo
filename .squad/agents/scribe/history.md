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

### 2026-09-10 — Session 332: Orchestration merge + verification process lesson

**Work Completed:**
- ✅ Created 3 orchestration logs (Linus, Danny, Turk; ISO 8601 UTC timestamps)
- ✅ Created session log (free-text outcomes and xfail rulings)
- ✅ Merged 5 inbox files → decisions.md; deleted inbox files; inbox now empty
- ✅ Updated agent histories with cross-team findings (Turk facts-map bug, Linus stream lifecycle, Danny rulings)
- ✅ Created ledger-growth proposal for Danny's ruling (size + age thresholds)
- ✅ Commit `a6ddeba` staged `.squad/` only; Turk's service code left untouched
- ✅ Commit `9c7bf20` fixed duplicate section in Turk's history; proposal added

**Process Lesson — Verification: Never truncate search results when checking for presence**

**Error:** Initial report claimed facts-map bug was missing from Turk's history. Verification used `grep -in "facts" .squad/agents/turk/history.md | head -5`. File contains 22 matches; the critical one (line 3216) was beyond the 5-line truncation. False absence reported as a finding.

**Root cause:** Same class of error Danny caught in herself earlier today (case-sensitive grep across C#/JSON boundaries producing false absence). Here: truncation instead of case mismatch. Same failure mode: "I did not see it" → "it is not there".

**Rule:** When verifying presence, use `grep -c` for count first, or drop limiting tools. Cost here was low (original commit was correct). Applied to security/disclosure checks, the same mistake could carry high cost.

**Commits:**
- `a6ddeba`: Orchestration logs, inbox merge, agent history updates
- `9c7bf20`: Ledger-growth proposal added to inbox (decisions.md growth is now spawn tax)
