# Foundry Eval Empty Dataset Bug — RCA Summary

**Root Cause:** Foundry eval backend cannot upload inline datasets to private-endpoint-only blob storage.

**Evidence:**
- SDK sends valid JSONL; Foundry returns 201 Created
- Storage account container is empty (0 blobs despite 6 eval runs)
- All 6 runs stuck in "Starting" — no progress
- No network path or RBAC for Foundry to reach private blob endpoint

**Workaround:** Explicit dataset upload using pod's managed identity + URI reference (Option 1 in full RCA)

**Files:** `.squad/decisions/inbox/basher-eval-empty-dataset-rca.md` (full), `.squad/agents/basher/eval-empty-dataset-summary.md`
