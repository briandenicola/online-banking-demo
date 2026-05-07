#############################################
# WORKLOAD IDENTITY — Single identity for all banking services
#############################################

resource "azurerm_user_assigned_identity" "banking_services" {
  name                = "${local.resource_name}-banking-mi"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
}

# Federated credential for AKS workload identity
resource "azurerm_federated_identity_credential" "aks_banking_workload_identity" {
  name                      = "aks-banking-workload-identity"
  user_assigned_identity_id = azurerm_user_assigned_identity.banking_services.id
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "system:serviceaccount:banking-demo:banking-workload-identity"
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
}

# RBAC: Redis Data Access (Enterprise/Managed Redis uses database-level policy)
resource "azapi_resource" "redis_access_policy_assignment" {
  type      = "Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2024-09-01-preview"
  name      = "bankingservices"
  parent_id = "${azurerm_managed_redis.main.id}/databases/default"

  body = {
    properties = {
      accessPolicyName = "default"
      user = {
        objectId = azurerm_user_assigned_identity.banking_services.principal_id
      }
    }
  }
}

# RBAC: Cognitive Services OpenAI User
resource "azurerm_role_assignment" "banking_cognitive_services_openai_user" {
  scope                = data.azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.banking_services.principal_id
}

# RBAC: Azure AI Developer (required for AI Foundry Agents API)
resource "azurerm_role_assignment" "banking_ai_developer" {
  scope                = data.azurerm_cognitive_account.openai.id
  role_definition_name = "Azure AI Developer"
  principal_id         = azurerm_user_assigned_identity.banking_services.principal_id
}

# RBAC: Cosmos DB Built-in Data Contributor
resource "azurerm_cosmosdb_sql_role_assignment" "banking_cosmos_contributor" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.banking_services.principal_id
  scope               = azurerm_cosmosdb_account.main.id
}

# RBAC: Key Vault Secrets User
resource "azurerm_role_assignment" "banking_keyvault_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.banking_services.principal_id
}
