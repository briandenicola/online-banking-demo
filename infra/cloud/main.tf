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
  location              = var.region
  resource_name         = "${random_pet.this.id}-${random_id.this.dec}"
  resource_group_name   = "${local.resource_name}-rg"
  aks_name              = "${local.resource_name}-aks"
  vnet_name             = "${local.resource_name}-vnet"
  storage_name          = "${substr(replace(random_uuid.guid.result, "-", ""), 0, 22)}sa"
  cosmos_name           = "${local.resource_name}-cosmos"
  openai_name           = "${local.resource_name}-openai"
  redis_name            = "${local.resource_name}-redis"
  eventhub_name         = "${local.resource_name}-eh"
  loganalytics_name     = "${local.resource_name}-logs"
  appinsights_name      = "${local.resource_name}-ai"
  keyvault_name         = "${local.resource_name}-kv"
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

resource "azurerm_eventhub_namespace" "main" {
  name                = local.eventhub_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Standard"
  capacity            = 1
  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_eventhub" "banking" {
  name                = "banking-events"
  namespace_name      = azurerm_eventhub_namespace.main.name
  resource_group_name = azurerm_resource_group.this.name
  partition_count     = 4
  message_retention   = 7
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
resource "azurerm_cognitive_account" "openai" {
  name                = local.openai_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku_name            = "S0"
  kind                = "OpenAI"
  
  identity {
    type = "SystemAssigned"
  }

  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_cognitive_deployment" "gpt41_mini" {
  name                = "gpt-4.1-mini"
  cognitive_account_id = azurerm_cognitive_account.openai.id
  model {
    format  = "OpenAI"
    name    = "gpt-4.1-mini"
    version = "2025-04-14"
  }
  
  sku {
    name = "GlobalStandard"
    capacity = 10
  }
}

resource "azurerm_cognitive_deployment" "text_embedding" {
  name                = "text-embedding-3-large"
  cognitive_account_id = azurerm_cognitive_account.openai.id
  model {
    format  = "OpenAI"
    name    = "text-embedding-3-large"
    version = "1"
  }
  
  sku {
    name = "GlobalStandard"
    capacity = 10
  }
}