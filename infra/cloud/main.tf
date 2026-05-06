terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2"
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
  location              = var.region
  resource_name         = "${random_pet.this.id}-${random_id.this.dec}"
  resource_group_name   = "${local.resource_name}-rg"
  aks_name              = "${local.resource_name}-aks"
  vnet_name             = "${local.resource_name}-vnet"
  storage_name          = "${substr(replace(random_uuid.guid.result, "-", ""), 0, 22)}sa"
  cosmos_name           = "${local.resource_name}-cosmos"
  openai_name           = "${local.resource_name}-foundry"
  project_name          = "${local.resource_name}-project"
  redis_name            = "${local.resource_name}-redis"
  loganalytics_name     = "${local.resource_name}-logs"
  appinsights_name      = "${local.resource_name}-ai"
  keyvault_name         = "${local.resource_name}-kv"
  acr_name              = "${replace(local.resource_name, "-", "")}acr"
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

resource "azurerm_storage_account" "main" {
  name                          = local.storage_name
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  account_tier                  = "Standard"
  account_replication_type      = "LRS"
  shared_access_key_enabled     = false
}

resource "azurerm_virtual_network" "main" {
  name                = local.vnet_name
  address_space       = ["10.0.0.0/8"]
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_subnet" "aks" {
  name                 = "aks-subnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.240.0.0/16"]
}

resource "azurerm_kubernetes_cluster" "main" {
  name                = local.aks_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  kubernetes_version  = var.kubernetes_version
  dns_prefix          = local.aks_name
  sku_tier            = "Standard"

  default_node_pool {
    name           = "default"
    node_count     = var.aks_node_count
    vm_size        = var.aks_node_size
    vnet_subnet_id = azurerm_subnet.aks.id
    type           = "VirtualMachineScaleSets"
  }

  identity {
    type = "SystemAssigned"
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  network_profile {
    network_plugin = "azure"
    service_cidr   = "10.0.0.0/16"
    dns_service_ip = "10.0.0.10"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }

  tags = {
    AppName = local.resource_name
  }
}

# Azure Container Registry
resource "azurerm_container_registry" "main" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Basic"
  admin_enabled       = false

  tags = {
    AppName = local.resource_name
  }
}

# Grant AKS kubelet identity AcrPull role on ACR
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.main.kubelet_identity[0].object_id
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

resource "azurerm_cosmosdb_account" "main" {
  name                = local.cosmos_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  
  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.this.location
    failover_priority = 0
  }

  capabilities {
    name = "EnableServerless"
  }

  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_cosmosdb_sql_database" "banking" {
  name                = "BankingDemo"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
}

resource "azurerm_cosmosdb_sql_container" "users" {
  name                = "Users"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/id"]
}

resource "azurerm_cosmosdb_sql_container" "accounts" {
  name                = "Accounts"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/id"]
}

resource "azurerm_cosmosdb_sql_container" "transactions" {
  name                = "Transactions"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/accountId"]
}

resource "azurerm_cosmosdb_sql_container" "transfers" {
  name                = "Transfers"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/id"]
}

# Azure Managed Redis (newer API)
resource "azurerm_managed_redis" "main" {
  name                = local.redis_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku_name            = "Balanced_B0"
  default_database {
    access_keys_authentication_enabled = false
  }
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

resource "azurerm_key_vault" "main" {
  name                = local.keyvault_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"
  tags = {
    AppName = local.resource_name
  }
}

# Azure OpenAI
resource "azapi_resource" "this" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-10-01-preview"
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

# AKS workload identity setup for accessing OpenAI
resource "azurerm_federated_identity_credential" "aks_openai_workload_identity" {
  name                      = "aks-openai-workload-identity"
  user_assigned_identity_id = azurerm_user_assigned_identity.openai_managed_identity.id
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "system:serviceaccount:banking:anomaly-service"
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
}

resource "azurerm_federated_identity_credential" "aks_budget_workload_identity" {
  name                      = "aks-budget-workload-identity" 
  user_assigned_identity_id = azurerm_user_assigned_identity.openai_managed_identity.id
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "system:serviceaccount:banking:budget-service"
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
}

resource "azurerm_federated_identity_credential" "aks_chatbot_workload_identity" {
  name                      = "aks-chatbot-workload-identity"
  audience                  = ["api://AzureADTokenExchange"]
  user_assigned_identity_id = azurerm_user_assigned_identity.openai_managed_identity.id
  subject                   = "system:serviceaccount:banking:chatbot-service"
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
}

resource "azurerm_cognitive_deployment" "gpt54" {
  name                 = "gpt-5.4"
  cognitive_account_id = data.azurerm_cognitive_account.openai.id
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
  cognitive_account_id = data.azurerm_cognitive_account.openai.id
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

resource "azapi_resource" "ai_foundry_project" {
  type                      = "Microsoft.CognitiveServices/accounts/projects@2026-01-15-preview"
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