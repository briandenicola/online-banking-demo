# Orchestration: Foundry Managed VNet TF Apply Gate Closed

**Date:** 2026-05-14T15:59:44Z  
**Branch:** 138-foundry-troubleshooting  
**Agent:** Coordinator (Scribe recording)  
**Milestone:** ✅ `task cloud:up` SUCCEEDED  

---

## Summary

The Terraform apply gate for Azure AI Foundry Managed Virtual Network provisioning has been closed. After multiple failed rounds (capability host API version mismatch, missing project-MSI RBAC), the root cause was isolated and fixed. `terraform apply` now completes successfully and provisions all Foundry infrastructure as designed.

---

## Root Cause Analysis

### The Problem: Two-Layer Failure

1. **First Round (API Version Mismatch)**  
   - Error: Capability host creation returned HTTP 500 with no detail
   - Investigation: Applied sample-first discipline; diffed existing TF against `microsoft-foundry/foundry-samples` 18-managed-virtual-network
   - Finding: Our API version was `2025-10-01-preview` (May release); sample uses `2025-04-01-preview`

2. **Second Round (Missing RBAC)**  
   - After API fix, TF apply still failed waiting for capability host to be ready
   - Root cause: Project MSI (managed identity) lacked 5 critical RBAC roles:
     - `Storage Blob Data Contributor`
     - `Search Index Data Contributor`
     - `Search Service Contributor`
     - `Cosmos DB Account Reader`
     - `Cosmos DB Operator`
   - Without these, capability host cannot configure managed network connections to backing services
   - **Solution:** Added role assignments + `wait_project_rbac = 90` (allow 90s for IAM propagation)

### Sample-First Discipline Victory

The breakthrough came from applying sample-first discipline against Microsoft's official repository. Rather than pattern-matching from our existing (broken) code, we:
1. Fetched the canonical sample TF from `microsoft-foundry/foundry-samples`
2. Performed surgical diff against our implementation
3. Isolated two mismatches (API version + RBAC)
4. Validated each fix incrementally

**Lesson:** For complex Azure services still in preview, official samples are authoritative. Our existing TF had drifted through accumulation of trial-and-error fixes.

---

## Commits

| Commit | Message | Impact |
|--------|---------|--------|
| `3a6dd03` | fix(foundry): add project MSI RBAC + wait before capability host | **Primary fix** — Added 5 project roles + 90s settle wait |
| `fe9d752` | chore(squad): scribe hygiene pass — merge inbox, compress basher history, archive orchestration log | Pre-gate cleanup |
| `ac7dede` | docs(#138): Update Foundry managed VNet skill with correct connection schema | Connection target URI documentation |
| `ef20aab` | fix(squad): banner sample-first rule in skill + Basher charter | Documented sample-first principle |

---

## Verification

**Command:** `task cloud:up` (runs `terraform apply`)  
**Status:** ✅ SUCCEEDED  
**Output:** TF created Foundry account, managed networks, capability host, and backing service connections without error

Brian confirms: **"TF created!"**

---

## Knowledge Captured

1. **Managed Network Project MSI Roles** — The five roles are mandatory before capability host provisioning, not optional
2. **API Version Drift** — Preview services can decommission older API versions; samples stay current
3. **Sample-First Discipline** — For undocumented edge cases, official samples are more reliable than accumulated workarounds
4. **IAM Propagation Wait** — Even after successful role assignment, Azure requires ~90s for role propagation in Foundry agents

---

## Next Steps

1. Skill documentation updated with confirmed project-MSI RBAC requirement (commit `3a6dd03`)
2. Basher history appended with sample-first learning
3. Gate closed — Foundry infrastructure ready for agent workloads
