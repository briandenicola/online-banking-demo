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
  scope                = azapi_resource.this.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.banking_services.principal_id
}

# RBAC: Cognitive Services User on Content Understanding
resource "azurerm_role_assignment" "banking_cognitive_services_user_cus" {
  scope                = azapi_resource.content_understanding.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.banking_services.principal_id
}

# RBAC: CUS system identity needs blob read access for document processing
resource "azurerm_role_assignment" "cus_storage_blob_reader" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azapi_resource.content_understanding.output.identity.principalId
}

# RBAC: Azure AI Project Manager (required for AI Foundry Agents API)
resource "azurerm_role_assignment" "banking_ai_project_manager" {
  scope                = azapi_resource.ai_foundry_project.id
  role_definition_name = "Azure AI Project Manager"
  principal_id         = azurerm_user_assigned_identity.banking_services.principal_id
}

# RBAC: Storage Blob Data Contributor
resource "azurerm_role_assignment" "banking_storage_blob_data_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
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

#############################################
# DEPLOYER / CURRENT USER — Grant admin access to new resources
#############################################

# RBAC: Search Service Contributor (for deployer to manage Search)
resource "azurerm_role_assignment" "current_user_search_service_contributor" {
  scope                = azapi_resource.ai_search.id
  role_definition_name = "Search Service Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

# RBAC: Search Index Data Contributor (for deployer to manage indexes)
resource "azurerm_role_assignment" "current_user_search_index_data_contributor" {
  scope                = azapi_resource.ai_search.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

#############################################
# FOUNDRY MSI — Grant Foundry account MSI data-plane access to BYO resources
#############################################

# RBAC: Storage Blob Data Contributor (Foundry → Storage)
resource "azurerm_role_assignment" "foundry_storage_blob_data_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azapi_resource.this.output.identity.principalId
}

# RBAC: Cosmos DB Built-in Data Contributor (Foundry → Cosmos)
resource "azurerm_cosmosdb_sql_role_assignment" "foundry_cosmos_contributor" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azapi_resource.this.output.identity.principalId
  scope               = azurerm_cosmosdb_account.main.id
}

# RBAC: Search Index Data Contributor (Foundry → Search)
resource "azurerm_role_assignment" "foundry_search_index_data_contributor" {
  scope                = azapi_resource.ai_search.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = azapi_resource.this.output.identity.principalId
}

# RBAC: Search Service Contributor (Foundry → Search)
resource "azurerm_role_assignment" "foundry_search_service_contributor" {
  scope                = azapi_resource.ai_search.id
  role_definition_name = "Search Service Contributor"
  principal_id         = azapi_resource.this.output.identity.principalId
}

#############################################
# FOUNDRY MANAGED VNET — RBAC required for managed private endpoint provisioning
# (issue #141 — Managed Virtual Network preview)
#############################################

# RBAC: Azure AI Enterprise Network Connection Approver (RG scope)
# Required for the Foundry account MSI to auto-approve managed private endpoints
# created inside the Microsoft-managed VNet by outbound rules.
# Role ID: b556d68e-0be0-4f35-a333-ad7ee1ce17ea
resource "azurerm_role_assignment" "foundry_network_connection_approver" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Azure AI Enterprise Network Connection Approver"
  principal_id         = azapi_resource.this.output.identity.principalId
}

# RBAC: Contributor on Cosmos DB (control-plane) — required by the canonical
# managed-VNet sample so the Foundry MSI can provision/approve the managed PE
# to Cosmos. This is the ARM Contributor role, distinct from the Cosmos SQL
# data-plane role above.
resource "azurerm_role_assignment" "foundry_cosmos_arm_contributor" {
  scope                = azurerm_cosmosdb_account.main.id
  role_definition_name = "Contributor"
  principal_id         = azapi_resource.this.output.identity.principalId
}

#############################################
# FOUNDRY PROJECT MSI — Required by capability host (Agents runtime)
# Per microsoft-foundry/foundry-samples 18-managed-virtual-network: the project's
# system-assigned identity must have data-plane access to BYO Storage/Cosmos/Search
# BEFORE the capability host is created. Otherwise capability host creation fails
# with "CapabilityHostOperationFailed" and no further detail.
#############################################

resource "azurerm_role_assignment" "project_storage_blob" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azapi_resource.ai_foundry_project.output.identity.principalId
}

resource "azurerm_role_assignment" "project_search_index" {
  scope                = azapi_resource.ai_search.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = azapi_resource.ai_foundry_project.output.identity.principalId
}

resource "azurerm_role_assignment" "project_search_contributor" {
  scope                = azapi_resource.ai_search.id
  role_definition_name = "Search Service Contributor"
  principal_id         = azapi_resource.ai_foundry_project.output.identity.principalId
}

# Cosmos DB control-plane RBAC (NOT the SQL data-plane role — the capability
# host validates these specific control-plane roles on the project MSI).
resource "azurerm_role_assignment" "project_cosmos_reader" {
  scope                = azurerm_cosmosdb_account.main.id
  role_definition_name = "Cosmos DB Account Reader Role"
  principal_id         = azapi_resource.ai_foundry_project.output.identity.principalId
}

resource "azurerm_role_assignment" "project_cosmos_operator" {
  scope                = azurerm_cosmosdb_account.main.id
  role_definition_name = "Cosmos DB Operator"
  principal_id         = azapi_resource.ai_foundry_project.output.identity.principalId
}

# Cosmos DB SQL data-plane RBAC for the project SAMI.
# Required by the Foundry Agents service when it reads/writes BYO Cosmos via
# the project identity (e.g. agent provisioning, thread/run state, evals).
# Symptom if missing: HTTP 403 with
#   "Request blocked by Auth ... does not have required RBAC permissions to
#    perform action [Microsoft.DocumentDB/databaseAccounts/readMetadata]"
# Role: Cosmos DB Built-in Data Contributor (00000000-0000-0000-0000-000000000002)
# Ref: https://learn.microsoft.com/azure/cosmos-db/how-to-setup-rbac#built-in-role-definitions
resource "azurerm_cosmosdb_sql_role_assignment" "project_cosmos_data_contributor" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azapi_resource.ai_foundry_project.output.identity.principalId
  scope               = azurerm_cosmosdb_account.main.id
}

# Wait for project-level RBAC to propagate before creating the capability host.
# Sample uses 90s; ARM RBAC propagation can take that long across regions.
resource "time_sleep" "wait_project_rbac" {
  create_duration = "90s"

  depends_on = [
    azurerm_role_assignment.project_storage_blob,
    azurerm_role_assignment.project_search_index,
    azurerm_role_assignment.project_search_contributor,
    azurerm_role_assignment.project_cosmos_reader,
    azurerm_role_assignment.project_cosmos_operator,
    azurerm_cosmosdb_sql_role_assignment.project_cosmos_data_contributor,
  ]
}
