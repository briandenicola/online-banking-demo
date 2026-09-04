# Session Log: Foundry AI Search Outbound Rule Fix

**Session:** 2026-06-10T13:54:38Z  
**Duration:** ~30 minutes  
**Outcome:** ✅ Bug Fixed + Pattern Discovered

## Root Cause
Azure AI Foundry CognitiveSearch connections auto-create managed-VNet outbound rules. Explicit rule duplication → HTTP 400 "already an outbound rule to the same destination."

## Solution
Removed explicit `aisearch_outbound_rule` and `time_sleep.wait_aisearch_outbound`. Repointed dependencies to auto-created rule via `aisearch_connection`.

## Files Touched
- `infra/cloud/foundry-managed-vnet.tf`
- `infra/cloud/ai-connections.tf`

## Validation
- terraform validate: ✅ Passed
- terraform fmt: ✅ Passed
- No dangling refs

## Key Learning
**CognitiveSearch** connections behave differently from Storage/Cosmos — they auto-manage outbound rules. This is NOT documented in Microsoft's public docs; discovered empirically.
