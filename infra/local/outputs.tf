output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}

output "openai_endpoint" {
  value     = "https://${local.project_name}.services.ai.azure.com/api/projects/${local.project_name}"
  sensitive = false
}

output "managed_identity_client_id" {
  value = azurerm_user_assigned_identity.openai_managed_identity.client_id
}