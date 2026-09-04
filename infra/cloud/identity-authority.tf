#############################################
# AUTHORITY-SERVICE WORKLOAD IDENTITY (issue #336, epic #332 Phase 1)
#
# Every other service in this repo shares one UAMI
# (azurerm_user_assigned_identity.banking_services in identity.tf) holding
# account-scoped Cosmos Data Contributor. That makes services indistinguishable
# to the mesh and to Cosmos, so "only authority-service may write approvals" is a
# naming convention rather than a control.
#
# authority-service is the ONLY component permitted to perform an
# agent-originated write, so it is the first service to get its own identity.
# This establishes the per-service identity pattern; re-identifying the remaining
# services is the rest of #336 and is deliberately NOT attempted here.
#
# Differences from the shared identity, all intentional:
#   - Cosmos data-plane access is scoped to the two authority CONTAINERS, not the
#     account. The shared identity cannot be narrowed without touching every
#     service, but the new one starts narrow.
#   - No AI Foundry, Storage, Search or OpenAI roles. authority-service does not
#     talk to any of them; granting them "for symmetry" is how least privilege
#     dies.
#   - Redis and Key Vault access ARE granted: it publishes audit events to the
#     banking-events stream and reads the JWT signing key.
#############################################

resource "azurerm_user_assigned_identity" "authority_service" {
  name                = "${local.resource_name}-authority-mi"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = {
    AppName = local.resource_name
    Service = "authority-service"
  }
}

# Federated credential — bound to its OWN Kubernetes service account, not the
# shared banking-workload-identity one. This is §4.4 layer 1: a pod running under
# any other service account cannot obtain this identity's token.
resource "azurerm_federated_identity_credential" "aks_authority_workload_identity" {
  name                      = "aks-authority-workload-identity"
  user_assigned_identity_id = azurerm_user_assigned_identity.authority_service.id
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "system:serviceaccount:${var.kubernetes_namespace}:${var.authority_service_service_account}"
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
}

# RBAC: Cosmos data plane, scoped to the approval store only.
resource "azurerm_cosmosdb_sql_role_assignment" "authority_cosmos_approvals" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.authority_service.principal_id
  scope               = "${azurerm_cosmosdb_account.main.id}/dbs/${azurerm_cosmosdb_sql_database.banking.name}/colls/${azurerm_cosmosdb_sql_container.copilot_approvals.name}"
}

# RBAC: Cosmos data plane, scoped to the resolved policy store only.
resource "azurerm_cosmosdb_sql_role_assignment" "authority_cosmos_policy" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.authority_service.principal_id
  scope               = "${azurerm_cosmosdb_account.main.id}/dbs/${azurerm_cosmosdb_sql_database.banking.name}/colls/${azurerm_cosmosdb_sql_container.authority_policy.name}"
}

# RBAC: Redis data access — audit event publishing and the sweeper's
# multi-replica lock.
resource "azapi_resource" "authority_redis_access_policy_assignment" {
  type      = "Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2024-09-01-preview"
  name      = "authorityservice"
  parent_id = "${azurerm_managed_redis.main.id}/databases/default"

  body = {
    properties = {
      accessPolicyName = "default"
      user = {
        objectId = azurerm_user_assigned_identity.authority_service.principal_id
      }
    }
  }
}

# RBAC: Key Vault Secrets User — reads the JWT signing key to verify signer
# tokens.
resource "azurerm_role_assignment" "authority_keyvault_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.authority_service.principal_id
}
