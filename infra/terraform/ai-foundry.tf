resource "azurerm_resource_group" "banking_ai" {
  name     = "${var.prefix}-ai-rg"
  location = var.location
}

# Azure AI Foundry Hub
resource "azurerm_ai_foundry" "banking_hub" {
  name                = "${var.prefix}-banking-hub"
  location            = azurerm_resource_group.banking_ai.location
  resource_group_name = azurerm_resource_group.banking_ai.name
  sku_name            = "B1"
  
  identity {
    type = "SystemAssigned"
  }
}

# AI Foundry Project
resource "azurerm_ai_foundry_project" "banking_project" {
  name                = "${var.prefix}-banking-project"
  location            = azurerm_resource_group.banking_ai.location
  resource_group_name = azurerm_resource_group.banking_ai.name
  ai_foundry_id       = azurerm_ai_foundry.banking_hub.id
  sku_name            = "B1"
}

# OpenAI Connection
resource "azurerm_ai_services" "openai" {
  name                = "${var.prefix}-openai"
  location            = azurerm_resource_group.banking_ai.location
  resource_group_name = azurerm_resource_group.banking_ai.name
  sku_name            = "S0"
  kind                = "OpenAI"
  
  identity {
    type = "SystemAssigned"
  }
}

# Model Deployment - GPT-4o-mini for Chatbot
resource "azurerm_cognitive_deployment" "gpt4o_mini" {
  name                = "gpt-4o-mini"
  cognitive_account_id = azurerm_ai_services.openai.id
  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = "2024-07-18"
  }
  
  sku {
    name = "GlobalStandard"
    tier = "Global"
  }
}

# Model Deployment - Text Embedding for Anomaly Detection
resource "azurerm_cognitive_deployment" "text_embedding" {
  name                = "text-embedding-3-small"
  cognitive_account_id = azurerm_ai_services.openai.id
  model {
    format  = "OpenAI"
    name    = "text-embedding-3-small"
    version = "1"
  }
  
  sku {
    name = "GlobalStandard"
    tier = "Global"
  }
}

# Application Insights for monitoring
resource "azurerm_application_insights" "banking_ai" {
  name                = "${var.prefix}-ai-insights"
  location            = azurerm_resource_group.banking_ai.location
  resource_group_name = azurerm_resource_group.banking_ai.name
  workspace_id        = azurerm_log_analytics_workspace.banking_ai.id
  application_type    = "web"
}

resource "azurerm_log_analytics_workspace" "banking_ai" {
  name                = "${var.prefix}-ai-logs"
  location            = azurerm_resource_group.banking_ai.location
  resource_group_name = azurerm_resource_group.banking_ai.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# Role assignments for AI services
resource "azurerm_role_assignment" "ai_openai_connection" {
  scope                = azurerm_ai_services.openai.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_ai_foundry_project.banking_project.identity[0].principal_id
}