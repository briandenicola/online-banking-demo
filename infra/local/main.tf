terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4"
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

locals {
  location            = var.region
  resource_name       = "${random_pet.this.id}-${random_id.this.dec}"
  resource_group_name = "${local.resource_name}-rg"
  openai_name         = "${local.resource_name}-foundry"
  loganalytics_name   = "${local.resource_name}-logs"
  appinsights_name    = "${local.resource_name}-appinsights"
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
resource "azurerm_cognitive_account" "openai" {
  name                = local.openai_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku_name            = "S0"
  kind                = "OpenAI"
  tags = {
    AppName = local.resource_name
  }
}

# User-assigned managed identity for OpenAI RBAC access
resource "azurerm_user_assigned_identity" "openai_managed_identity" {
  name                = "${local.resource_name}-openai-mi"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
}

# Role assignment for OpenAI RBAC access
resource "azurerm_role_assignment" "openai_cognitive_services_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.openai_managed_identity.principal_id
}

resource "azurerm_cognitive_deployment" "gpt54" {
  name                 = "gpt-5.4"
  cognitive_account_id = azurerm_cognitive_account.openai.id
  model {
    format  = "OpenAI"
    name    = "gpt-5.4"
    version = "2026-03-05"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 10
  }
}

resource "azurerm_cognitive_deployment" "text_embedding" {
  name                 = "text-embedding-3-large"
  cognitive_account_id = azurerm_cognitive_account.openai.id
  model {
    format  = "OpenAI"
    name    = "text-embedding-3-large"
    version = "1"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 10
  }
}
