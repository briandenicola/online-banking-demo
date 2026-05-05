output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}

output "openai_endpoint" {
  value     = azurerm_cognitive_account.openai.endpoint
  sensitive = true
}

