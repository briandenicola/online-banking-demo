# Session: Foundry TF Connections Merge & Commit

**Date:** 2026-05-14T15:11:20Z  
**Branch:** 138-foundry-troubleshooting  

## Summary

Merged two post-basher decision inbox items into decisions.md. Fixed Foundry managed VNet project connection schema errors (HTTP 400) by adding `useWorkspaceManagedIdentity: true` to Azure AI project connections. Also resolved resource auto-creation conflict on managedNetworks/default.

## Key Decisions Merged

1. **Foundry Managed VNet Connection Schema Fix** — Added `useWorkspaceManagedIdentity: true` flag to all three project connections (storage, cosmos, aisearch) in `infra/cloud/ai-connections.tf`
2. **Auto-Created managedNetworks/default** — Removed explicit resource definition; reference auto-created path in outbound rules via parent_id

## Files Updated

- `infra/cloud/ai-connections.tf` — Lines 48, 75, 102
- `.squad/decisions.md` — Merged inbox entries
- `.squad/skills/foundry-managed-vnet/SKILL.md` — Updated canonical pattern

## Git Status

Staged for commit: `.squad/decisions.md`, `.squad/decisions/inbox/*` (deleted), `infra/cloud/ai-connections.tf`
