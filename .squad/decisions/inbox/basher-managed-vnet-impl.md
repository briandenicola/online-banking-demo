# Decision: Foundry Managed VNet — implementation choices

**Date:** 2026-05-14
**Author:** Basher
**Status:** Inbox (proposed)
**Issue:** #141
**Branch:** `138-foundry-troubleshooting`

## Context

Issue #141 directed migration of Foundry private networking from BYO VNet injection (#138) to the Managed Virtual Network (preview) pattern. Implementation choices below; calling out where I deviated from Brian's verbal prompt and why.

## Decisions

### 1. Isolation mode = `AllowInternetOutbound` (not `AllowOnlyApprovedOutbound`)

- Avoids automatic Azure Firewall provisioning (FQDN rules in approved-only mode trigger one — ~$288–912/mo per Foundry account, cannot be shared).
- Internet outbound is implicitly allowed → no need for ServiceTag rules (AzureMonitor, AAD, ACR) at all.
- PrivateEndpoint outbound rules still take effect for the listed destinations (Storage, Cosmos, Search) — those targets ARE reached via managed PE inside Microsoft's VNet, not internet.
- Trade-off: Foundry agents can egress to arbitrary internet endpoints. For a demo this is acceptable. If data-exfiltration prevention becomes a requirement, flip to `AllowOnlyApprovedOutbound` and add ServiceTag/FQDN rules — but accept the firewall cost.

### 2. Skipped ServiceTag and FQDN outbound rules entirely

Rationale: Redundant under `AllowInternetOutbound`. Brian's prompt suggested adding ServiceTag rules for AzureMonitor / AAD / ACR — these are unnecessary with internet egress allowed. Adding them now would be net-zero behaviour and net-positive blast radius if the mode flips later. **Zero rules added beyond the three PE rules.**

### 3. KEPT the Foundry inbound private endpoint and DNS zones (deviated from Brian's prompt)

Brian's prompt instructed to REMOVE `azurerm_private_endpoint.ai` and the `privatelink.cognitiveservices.azure.com` / `openai.azure.com` / `services.ai.azure.com` DNS zones. I did NOT remove them, because:

1. **AKS pods can't reach Foundry without it.** With `publicNetworkAccess = "Disabled"` (which we keep), the Foundry data plane is only reachable via PE. Removing the inbound PE breaks chatbot-service, ai-service, and prompt-eval-service.
2. **Issue #141 itself explicitly lists this PE as KEEP** in the file-by-file table.
3. **The canonical Microsoft sample keeps it** (`microsoft-foundry/foundry-samples@main` `18-managed-virtual-network/ai-foundry.tf` defines `azurerm_private_endpoint.cognitive_services`).
4. **The DNS zones are also still needed for `azurerm_private_endpoint.content_understanding`** (separate AI Services account, also has `publicNetworkAccess = "Disabled"`).

Managed VNet only handles Foundry's **outbound** (agent → backing services). Inbound (AKS → Foundry data plane) still requires the BYO PE in our VNet. Brian was likely conflating the two; flagged in PR body for him to override if intended otherwise.

### 4. Cosmos: ARM Contributor role added separately from existing SQL data-plane role

Sample requires `Contributor` at the Cosmos account scope for the Foundry MSI to provision the managed PE. We already have a `azurerm_cosmosdb_sql_role_assignment.foundry_cosmos_contributor` (data-plane role). Added a NEW `azurerm_role_assignment.foundry_cosmos_arm_contributor` (control-plane). Different resource types, different role scopes — no conflict.

### 5. `userOwnedStorage` (not `userOwnedStorageAccounts`)

Switched the Foundry account property to match canonical sample form. `userOwnedStorageAccounts = [{ id = ... }]` was the older shape; `userOwnedStorage = [{ resourceId = ... }]` is the form used in `2025-10-01-preview`. Since `schema_validation_enabled = false`, both serialize, but aligning with canonical sample reduces drift risk. Also added `userOwnedCosmosDB` and `userOwnedSearch` (new in this pattern).

### 6. Capability host API version unchanged

Kept `capabilityHosts@2025-10-01-preview` (already in repo). The canonical sample uses `2025-04-01-preview` for capability host but both work; no need to downgrade.

### 7. No Terraform feature registration

Per Microsoft docs, no explicit `az feature register` is documented as required for Managed VNet. Region must be in the supported list — verify before `task cloud:up`.

## Risks

- Outbound rule provisioning takes 30+ minutes from clean state. `task cloud:up` will appear hung; that's expected.
- If the region is not in the Managed VNet supported list (East US, East US2, etc. — see SKILL.md for full list), creation will fail with an opaque error. Verify region first.
- `useMicrosoftManagedNetwork` cannot be flipped post-creation without account recreate. Brian's destroy-everything-first approach side-steps this.
