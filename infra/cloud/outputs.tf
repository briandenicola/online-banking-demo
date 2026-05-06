output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "aks_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "storage_account_name" {
  value = azurerm_storage_account.main.name
}

output "cosmos_db_endpoint" {
  value     = azurerm_cosmosdb_account.main.endpoint
  sensitive = true
}

output "cosmos_db_key" {
  value     = azurerm_cosmosdb_account.main.primary_key
  sensitive = true
}

output "redis_host" {
  value = azurerm_managed_redis.main.hostname
}

output "application_insights_key" {
  value     = azurerm_application_insights.main.instrumentation_key
  sensitive = true
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}

output "key_vault_uri" {
  value = azurerm_key_vault.main.vault_uri
}

output "openai_endpoint" {
  value     = "https://${local.openai_name}.services.ai.azure.com/api/projects/${local.project_name}"
  sensitive = false
}

output "managed_identity_client_id" {
  value = azurerm_user_assigned_identity.openai_managed_identity.client_id
}

output "acr_name" {
  value = azurerm_container_registry.main.name
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "cosmos_connection_string" {
  value     = "AccountEndpoint=${azurerm_cosmosdb_account.main.endpoint};AccountKey=${azurerm_cosmosdb_account.main.primary_key};"
  sensitive = true
}