#############################################
# AI — Azure AI Services, OpenAI deployments, AI Foundry project
#############################################

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
      publicNetworkAccess = "Disabled"
      userOwnedStorageAccounts = [
        {
          id = azurerm_storage_account.main.id
        }
      ]
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

# Grant the deployer (current user) OpenAI access
resource "azurerm_role_assignment" "current_user_cognitive_services_openai_user" {
  scope                = data.azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azapi_resource" "content_understanding" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-04-01-preview"
  name                      = local.cus_name
  parent_id                 = azurerm_resource_group.this.id
  location                  = "westus"
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
      customSubDomainName    = local.cus_name
      publicNetworkAccess    = "Disabled"
      userOwnedStorageAccounts = [
        {
          id = azurerm_storage_account.main.id
        }
      ]
    }
  }

  response_export_values = [
    "properties.endpoint",
    "identity.principalId"
  ]
}

data "azurerm_cognitive_account" "content_understanding" {
  depends_on          = [azapi_resource.content_understanding]
  name                = local.cus_name
  resource_group_name = azurerm_resource_group.this.name
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
  count     = var.deploy_embedding_model ? 1 : 0
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
