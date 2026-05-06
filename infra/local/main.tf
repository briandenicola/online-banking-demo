terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4"
    }
    azapi = {
      source  = "azure/azapi"
      version = "~> 2"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
  storage_use_azuread = true
}

provider "azuread" {}

locals {
  location            = var.region
  resource_name       = "${random_pet.this.id}-${random_id.this.dec}"
  resource_group_name = "${local.resource_name}-rg"
  openai_name         = "${local.resource_name}-foundry"
  loganalytics_name   = "${local.resource_name}-logs"
  appinsights_name    = "${local.resource_name}-appinsights"
  project_name        = "${local.resource_name}-project"
}

data "azurerm_client_config" "current" {}

resource "random_pet" "this" {}

resource "random_id" "this" {
  byte_length = 2
}

resource "random_uuid" "guid" {}

resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = local.location
  tags = {
    Application = var.tags
    DeployedOn  = timestamp()
    AppName     = local.resource_name
  }
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = local.loganalytics_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_application_insights" "main" {
  name                = local.appinsights_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.main.id

  tags = {
    AppName = local.resource_name
  }
}

# Azure OpenAI
resource "azapi_resource" "this" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-04-01-preview"
  name                      = local.openai_name
  parent_id                 = azurerm_resource_group.this.id
  location                  = azurerm_resource_group.this.location
  schema_validation_enabled = false

  body = {
    kind = "AIServices"
    sku = {
      name = "S0"
    }
    identity = {
      type = "SystemAssigned"
    }
    properties = {
      disableLocalAuth       = true
      allowProjectManagement = true
      customSubDomainName    = local.openai_name
    }
  }

  response_export_values = [
    "properties.endpoint",
    "identity.principalId"
  ]
}

data "azurerm_cognitive_account" "openai" {
  depends_on          = [azapi_resource.this]
  name                = local.openai_name
  resource_group_name = azurerm_resource_group.this.name
}

# User-assigned managed identity for OpenAI RBAC access
resource "azurerm_user_assigned_identity" "openai_managed_identity" {
  name                = "${local.resource_name}-openai-mi"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
}

# Role assignment for OpenAI RBAC access
resource "azurerm_role_assignment" "openai_cognitive_services_openai_user" {
  scope                = data.azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.openai_managed_identity.principal_id
}

resource "azurerm_role_assignment" "current_user_cognitive_services_openai_user" {
  scope                = data.azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Azure AI Developer role for AI Foundry project (required by AgentsClient in chatbot-service)
resource "azurerm_role_assignment" "current_user_ai_developer" {
  scope                = azapi_resource.ai_foundry_project.id
  role_definition_name = "Azure AI Developer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "managed_identity_ai_developer" {
  scope                = azapi_resource.ai_foundry_project.id
  role_definition_name = "Azure AI Developer"
  principal_id         = azurerm_user_assigned_identity.openai_managed_identity.principal_id
}

resource "azapi_resource" "gpt54_mini" {
  type      = "Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview"
  name      = "gpt-5.4-mini"
  parent_id = data.azurerm_cognitive_account.openai.id

  depends_on = [azapi_resource.this]

  body = {
    sku = {
      name     = "GlobalStandard"
      capacity = 10
    }
    properties = {
      model = {
        format  = "OpenAI"
        name    = "gpt-5.4-mini"
        version = "2026-03-17"
      }
    }
  }
}

resource "azapi_resource" "text_embedding" {
  type      = "Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview"
  name      = "text-embedding-ada-002"
  parent_id = data.azurerm_cognitive_account.openai.id

  depends_on = [azapi_resource.gpt54_mini]

  body = {
    sku = {
      name     = "GlobalStandard"
      capacity = 10
    }
    properties = {
      model = {
        format  = "OpenAI"
        name    = "text-embedding-ada-002"
        version = "2"
      }
    }
  }
}

resource "azapi_resource" "ai_foundry_project" {
  type                      = "Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview"
  name                      = local.project_name
  parent_id                 = data.azurerm_cognitive_account.openai.id
  location                  = azurerm_resource_group.this.location
  schema_validation_enabled = false

  body = {
    sku = {
      name = "S0"
    }
    identity = {
      type = "SystemAssigned"
    }

    properties = {
      displayName = local.project_name
      description = var.tags
    }
  }

  response_export_values = [
    "identity.principalId",
    "properties.internalId"
  ]
}

# Azure AD Application and Service Principal for chatbot-service local Docker auth
resource "azuread_application" "chatbot_local" {
  display_name = "banking-demo-chatbot-local"
  owners       = [data.azurerm_client_config.current.object_id]
}

resource "azuread_service_principal" "chatbot_local" {
  client_id = azuread_application.chatbot_local.client_id
  owners    = [data.azurerm_client_config.current.object_id]
}

resource "azuread_application_password" "chatbot_local" {
  application_id = azuread_application.chatbot_local.id
  display_name   = "chatbot-local-secret"
  end_date       = timeadd(timestamp(), "168h") # 7 days
}

# Assign Azure AI Developer role to SPN for AI Foundry project access
resource "azurerm_role_assignment" "chatbot_spn_ai_developer" {
  scope                = azapi_resource.ai_foundry_project.id
  role_definition_name = "Azure AI Developer"
  principal_id         = azuread_service_principal.chatbot_local.object_id
}

# Assign Cognitive Services OpenAI User role to SPN
resource "azurerm_role_assignment" "chatbot_spn_cognitive_services_openai_user" {
  scope                = data.azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azuread_service_principal.chatbot_local.object_id
}