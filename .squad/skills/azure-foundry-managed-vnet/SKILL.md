# Azure Foundry Managed Virtual Network — Terraform Pattern

## Overview

Azure AI Foundry's Managed Virtual Network (preview) provides Microsoft-managed networking for Foundry agent egress. When configured, Azure **auto-creates** child resources that Terraform must handle correctly to avoid conflicts.

## Critical Pattern: Auto-Created managedNetworks/default

### The Problem

When `networkInjections` with `useMicrosoftManagedNetwork: true` is configured on a Foundry account, Azure **implicitly provisions** `managedNetworks/default` as a child resource. Attempting to create this resource explicitly in Terraform causes a conflict:

```
Error: Resource already exists
  ID: /subscriptions/.../accounts/{account-name}/managedNetworks/default
```

### The Solution

**Do NOT create `azapi_resource.managed_network` explicitly.** Instead:

1. Let Azure auto-create `managedNetworks/default` via the Foundry account configuration
2. Reference the auto-created path directly in outbound rule `parent_id` attributes

### Correct Pattern

```hcl
# Foundry account with networkInjections — Azure auto-creates managedNetworks/default
resource "azapi_resource" "foundry_account" {
  type      = "Microsoft.CognitiveServices/accounts@2025-10-01-preview"
  name      = "my-foundry"
  parent_id = azurerm_resource_group.main.id

  body = {
    kind = "AIServices"
    properties = {
      networkInjections = [
        {
          scenario                   = "agent"
          subnetArmId                = ""
          useMicrosoftManagedNetwork = true
        }
      ]
      # ... other properties
    }
  }
}

# ❌ DO NOT CREATE THIS — Azure auto-creates it
# resource "azapi_resource" "managed_network" {
#   type      = "Microsoft.CognitiveServices/accounts/managedNetworks@2025-10-01-preview"
#   name      = "default"
#   parent_id = azapi_resource.foundry_account.id
# }

# ✅ Reference auto-created path in outbound rules
resource "azapi_resource" "cosmos_outbound_rule" {
  type      = "Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2025-10-01-preview"
  name      = "cosmos-sql-rule"
  parent_id = "\${azapi_resource.foundry_account.id}/managedNetworks/default"  # ← direct path reference

  schema_validation_enabled = false

  body = {
    properties = {
      type = "PrivateEndpoint"
      destination = {
        serviceResourceId = azurerm_cosmosdb_account.main.id
        subresourceTarget = "Sql"
      }
      category = "UserDefined"
    }
  }

  depends_on = [
    time_sleep.wait_cosmos,  # 10m wait for backing service + PE
    azurerm_role_assignment.foundry_network_connection_approver,
    azurerm_role_assignment.foundry_cosmos_arm_contributor,
  ]
}
```

## Connection Auto-Created Outbound Rules (CRITICAL UPDATE 2026-06-10)

**Some Foundry project connection types auto-create managed-VNet outbound rules.** Attempting to create explicit outbound rules for these services causes a conflict:

```
Error: HTTP 400 "There is already an outbound rule to the same destination"
```

### Auto-Create Behavior by Connection Category

| Connection Category | Auto-Creates Outbound Rule? | Explicit Rule Required? |
|---------------------|----------------------------|------------------------|
| `CognitiveSearch`   | ✅ YES                      | ❌ NO (causes conflict) |
| `AzureStorageAccount` | ✅ YES                    | ❌ NO (causes conflict) |
| `CosmosDb`          | ❌ NO                       | ✅ YES                  |

### Correct Pattern for Connections

```hcl
# AI Search connection — auto-creates outbound rule
resource "azapi_resource" "aisearch_connection" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview"
  name      = azapi_resource.ai_search.name
  parent_id = azapi_resource.ai_foundry_project.id
  
  body = {
    properties = {
      category = "CognitiveSearch"  # ← Auto-creates outbound rule
      target   = "https://${azapi_resource.ai_search.name}.search.windows.net"
      authType = "AAD"
      # ...
    }
  }
}

# ❌ DO NOT create explicit outbound rule for AI Search or Storage
# resource "azapi_resource" "aisearch_outbound_rule" {
#   # This will conflict with auto-created rule
# }

# ✅ DO create explicit outbound rule for Cosmos
resource "azapi_resource" "cosmos_outbound_rule" {
  type      = "Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2025-10-01-preview"
  name      = "cosmos-sql-rule"
  parent_id = "\${azapi_resource.foundry_account.id}/managedNetworks/default"
  # ...
}

# Wait for all outbound rules (both explicit and auto-created)
resource "time_sleep" "wait_outbound_rules" {
  create_duration = "600s"
  depends_on = [
    azapi_resource.cosmos_outbound_rule,        # explicit
    azapi_resource.aisearch_connection,         # auto-creates rule
    azapi_resource.storage_connection,          # auto-creates rule
  ]
}
```

**Note:** This auto-creation behavior is empirically confirmed but not clearly documented by Microsoft. The canonical foundry-samples may use conditional `count` flags to avoid conflicts.

## Provisioning Delays

Managed VNet outbound rules require **significant wait times** for Azure backend provisioning:

1. **10 minutes per backing service**: Wait after each backing service (Cosmos) and its private endpoint are created (Storage and Search waits removed — their connections auto-create rules)
2. **600 seconds after all outbound rules**: Extra buffer for rules to reach \`Succeeded\` state before capability host creation

```hcl
resource "time_sleep" "wait_cosmos_outbound" {
  create_duration = "10m"
  depends_on = [
    azurerm_cosmosdb_account.main,
    azurerm_private_endpoint.cosmos,
  ]
}

resource "time_sleep" "wait_outbound_rules" {
  create_duration = "600s"
  depends_on = [
    azapi_resource.cosmos_outbound_rule,        # explicit rule
    azapi_resource.aisearch_connection,         # auto-creates outbound rule
    azapi_resource.storage_connection,          # auto-creates outbound rule
  ]
}
```

**Total clean provisioning time: 20+ minutes** (reduced from 30+ since Storage and Search no longer need explicit 10m waits)

## Required RBAC

The Foundry account's system-assigned identity needs:

```hcl
# Required for approving managed network PE connections
resource "azurerm_role_assignment" "foundry_network_connection_approver" {
  scope                = azurerm_resource_group.main.id
  role_definition_name = "Azure AI Enterprise Network Connection Approver"
  principal_id         = azapi_resource.foundry_account.identity[0].principal_id
}

# Per backing service (example: Storage)
resource "azurerm_role_assignment" "foundry_storage_blob_data_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azapi_resource.foundry_account.identity[0].principal_id
}
```

## Isolation Modes

- **AllowInternetOutbound** (recommended): Private endpoints to backing services, open internet egress. No Azure Firewall cost.
- **AllowOnlyApprovedOutbound**: Requires Azure Firewall for FQDN rules. Higher cost, stricter control.

Configure via \`networkInjections\` settings (implicitly set when Azure creates the managed network).

## Differences from Microsoft Canonical Sample

Microsoft's foundry-samples/18-managed-virtual-network explicitly creates \`azapi_resource.managed_network\`. This may be:
- An older pattern predating auto-create behavior
- Using a different API version where auto-create doesn't occur
- Providing explicit control over managed network settings

**For 2025-10-01-preview API**: Azure auto-creates the resource, so explicit creation causes conflicts. Use the direct path reference pattern documented above.

## Verification

After applying:

```bash
# Check managed network exists (auto-created)
az cognitiveservices account show \
  --name my-foundry \
  --resource-group my-rg \
  --query "properties.networkAcls"

# List outbound rules (both explicit and auto-created)
az rest --method get \
  --url "https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{account}/managedNetworks/default/outboundRules?api-version=2025-10-01-preview"
```

## Related

- Issue #141: Managed VNet implementation
- PR #143: Foundry Managed VNet refactor
- Commit 89c888f: Fix for auto-create conflict
- Decision: \`.squad/decisions/inbox/basher-managed-network-autocreate.md\`
- Decision: \`.squad/decisions/inbox/danny-tf-deploy-regressions.md\` (2026-06-10: connection auto-create behavior)
- History: \`.squad/agents/basher/history.md\` (2026-05-14 learning)
- History: \`.squad/agents/danny/history.md\` (2026-06-10: Storage connection auto-create fix)

