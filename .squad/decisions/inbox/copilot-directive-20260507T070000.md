### 2026-05-07T07:00:00Z: Reference — Proper RBAC with Azure Managed Redis

**By:** Brian (via Copilot)
**For:** Basher (Phase 0a Terraform cleanup)
**What:** Example Terraform showing correct pattern for Azure Managed Redis with RBAC via azapi_resource.

Key patterns to follow:
1. User Assigned Managed Identity for the workload
2. `azurerm_redis_cache` (or `azurerm_managed_redis`) for the cache resource
3. `azapi_resource` with type `Microsoft.Cache/redis/accessPolicyAssignments` for RBAC assignment
4. Properties: `accessPolicyName = "Data Contributor"`, `objectId` from identity principal, `objectIdAlias` from identity name

```hcl
resource "azurerm_user_assigned_identity" "uami" {
  name                = "redis-uami"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

# Redis resource (azurerm_managed_redis or azurerm_redis_cache)
# ...

# RBAC via azapi — this is the correct pattern since azurerm doesn't support it
resource "azapi_resource" "redis_access_policy_assignment" {
  type      = "Microsoft.Cache/redis/accessPolicyAssignments@2024-11-01"
  name      = "redis-uami-access"
  parent_id = azurerm_managed_redis.main.id

  body = {
    properties = {
      accessPolicyName = "Data Contributor"
      objectId         = azurerm_user_assigned_identity.uami.principal_id
      objectIdAlias    = azurerm_user_assigned_identity.uami.name
    }
  }
}
```

**Why:** Current `infra/cloud/main.tf` already uses this pattern (lines 333-344) but Basher should ensure it stays consistent during the Phase 0a Terraform reorganization into `redis.tf`.
