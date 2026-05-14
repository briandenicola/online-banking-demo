# Decision: Azure Foundry Managed VNet — Auto-Created managedNetworks/default

**Status:** Implemented  
**Date:** 2026-05-14  
**Author:** Basher  
**Context:** PR #143 (branch 138-foundry-troubleshooting), issue #141

## Problem

After `terraform destroy` (fresh state) + `task cloud:up`, Terraform failed with:
```
Error: Resource already exists
  with azapi_resource.managed_network,
  on foundry-managed-vnet.tf line 19
  ID: /subscriptions/.../accounts/funky-elephant-11797-foundry/managedNetworks/default
```

## Root Cause

Azure **auto-creates** `managedNetworks/default` as a child resource when `networkInjections` is configured on the Foundry account:
```hcl
resource "azapi_resource" "this" {
  type = "Microsoft.CognitiveServices/accounts@2025-10-01-preview"
  body = {
    properties = {
      networkInjections = [
        {
          scenario                   = "agent"
          subnetArmId                = ""
          useMicrosoftManagedNetwork = true
        }
      ]
    }
  }
}
```

Our explicit standalone `azapi_resource "managed_network"` conflicted with the already-existing auto-created resource.

## Decision

**Do NOT create `azapi_resource.managed_network` explicitly.** Instead, reference the auto-created path directly in outbound rule resources:

```hcl
resource "azapi_resource" "storage_outbound_rule" {
  type      = "Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2025-10-01-preview"
  name      = "storage-blob-rule"
  parent_id = "${azapi_resource.this.id}/managedNetworks/default"
  # ...
}
```

This approach:
- Avoids conflict with Azure's implicit provisioning
- Maintains full control over outbound rules (which we DO need to create explicitly)
- Simplifies resource graph (no standalone managed_network lifecycle to track)

## Alternatives Considered

1. **Import auto-created managedNetworks/default into state**: Adds complexity; Azure owns the lifecycle anyway.
2. **Follow Microsoft canonical sample exactly**: Their sample explicitly creates managed_network, but likely predates auto-create behavior or uses different API versions. Our testing confirms auto-create happens on 2025-10-01-preview API.

## Implementation

**Changed files:**
- `infra/cloud/foundry-managed-vnet.tf`:
  - Removed `azapi_resource.managed_network` block (lines 19-39)
  - Updated `parent_id` in all three outbound rules to `"${azapi_resource.this.id}/managedNetworks/default"`
  - Added explanatory comment at top of outbound rules section

**Validation:**
- `terraform validate`: ✅ Success
- `terraform plan`: ✅ 79 adds, 0 changes, 64 destroys (expected for fresh state)
- No managed_network conflicts, all outbound rules show as new `create` actions

## Impact

- **Positive:** Eliminates resource conflict; aligns with Azure's implicit provisioning model
- **Neutral:** Managed network settings (isolationMode, managedNetworkKind) are now implicit based on Foundry account `networkInjections` config (already the case)
- **None:** Outbound rules remain fully configurable and explicit

## Related

- PR #143: Foundry Managed VNet refactor
- Issue #141: Managed VNet implementation
- Commit 89c888f: Fix implementation
- Microsoft canonical sample: foundry-samples/infrastructure/infrastructure-setup-terraform/18-managed-virtual-network (note: may differ in API version or provisioning behavior)

## Follow-up

Document this pattern in `.squad/skills/azure-foundry-managed-vnet/SKILL.md` for future infrastructure work.
