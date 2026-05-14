#############################################
# KEY VAULT SECRETS — Secrets stored in Azure Key Vault
#
# Secrets are written over the public endpoint (locked to the deployer's IP
# in keyvault.tf). The Private Endpoint is created AFTER all secrets exist
# (see depends_on in private-endpoints.tf) so runtime workloads use the
# private path while bootstrap stays unblocked.
#############################################

# JWT signing key — generated once, persisted in KeyVault
resource "random_password" "jwt_key" {
  length  = 32
  special = false
}

resource "azurerm_key_vault_secret" "jwt_key" {
  name         = "jwt-key"
  value        = base64encode(random_password.jwt_key.result)
  key_vault_id = azurerm_key_vault.main.id
  depends_on = [
    azurerm_role_assignment.deployer_keyvault_admin,
  ]
}

resource "azurerm_key_vault_secret" "openai_endpoint" {
  name         = "openai-endpoint"
  value        = "https://${local.openai_name}.services.ai.azure.com/api/projects/${local.project_name}"
  key_vault_id = azurerm_key_vault.main.id
  depends_on = [
    azurerm_role_assignment.deployer_keyvault_admin,
  ]
}

resource "azurerm_key_vault_secret" "content_understanding_endpoint" {
  name         = "content-understanding-endpoint"
  value        = data.azurerm_cognitive_account.content_understanding.endpoint
  key_vault_id = azurerm_key_vault.main.id
  depends_on = [
    azurerm_role_assignment.deployer_keyvault_admin,
  ]
}

resource "azurerm_key_vault_secret" "redis_connection_string" {
  name         = "redis-connection-string"
  value        = "${azurerm_managed_redis.main.hostname}:10000,ssl=True,abortConnect=False"
  key_vault_id = azurerm_key_vault.main.id
  depends_on = [
    azurerm_role_assignment.deployer_keyvault_admin,
  ]
}

resource "azurerm_key_vault_secret" "appinsights_connection_string" {
  name         = "appinsights-connection-string"
  value        = azurerm_application_insights.main.connection_string
  key_vault_id = azurerm_key_vault.main.id
  depends_on = [
    azurerm_role_assignment.deployer_keyvault_admin,
  ]
}

#############################################
# RBAC — CSI driver (kubelet identity) needs Key Vault access
#############################################

resource "azurerm_role_assignment" "csi_keyvault_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_kubernetes_cluster.main.key_vault_secrets_provider[0].secret_identity[0].object_id
}
