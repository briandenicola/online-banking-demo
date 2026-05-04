# Resource Group
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

# Virtual Network
resource "azurerm_virtual_network" "main" {
  name                = "${var.resource_group_name}-vnet"
  address_space       = ["10.0.0.0/8"]
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = var.tags
}

# AKS Subnet
resource "azurerm_subnet" "aks" {
  name                 = "aks-subnet"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.240.0.0/16"]
}

# AKS Cluster
resource "azurerm_kubernetes_cluster" "main" {
  name                = var.aks_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  kubernetes_version  = var.kubernetes_version
  dns_prefix          = var.aks_name
  sku_tiers           = "Standard"

  default_node_pool {
    name                = "default"
    node_count          = var.aks_node_count
    vm_size             = var.aks_node_size
    vnet_subnet_id      = azurerm_subnet.aks.id
    type                = "VirtualMachineScaleSets"
    enable_auto_scaling = true
    min_count           = 1
    max_count           = 5
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

  tags = var.tags
}

# Log Analytics Workspace for monitoring
resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.resource_group_name}-law"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

# Cosmos DB
resource "azurerm_cosmosdb_account" "main" {
  name                = "${replace(var.resource_group_name, "-", "")}cosmos"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  
  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.main.location
    failover_priority = 0
  }

  capabilities {
    name = "EnableServerless"
  }

  tags = var.tags
}

# Cosmos DB SQL Database
resource "azurerm_cosmosdb_sql_database" "banking" {
  name                = "BankingDemo"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
}

# Cosmos DB Containers
resource "azurerm_cosmosdb_sql_container" "users" {
  name                = "Users"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_path  = "/id"
}

resource "azurerm_cosmosdb_sql_container" "accounts" {
  name                = "Accounts"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_path  = "/id"
}

resource "azurerm_cosmosdb_sql_container" "transactions" {
  name                = "Transactions"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_path  = "/accountId"
}

resource "azurerm_cosmosdb_sql_container" "transfers" {
  name                = "Transfers"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_path  = "/id"
}

# Event Hub Namespace
resource "azurerm_eventhub_namespace" "main" {
  name                = "${replace(var.resource_group_name, "-", "")}eh"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "Standard"
  capacity            = 1
  tags                = var.tags
}

# Event Hub
resource "azurerm_eventhub" "banking" {
  name                = "banking-events"
  namespace_name      = azurerm_eventhub_namespace.main.name
  resource_group_name = azurerm_resource_group.main.name
  partition_count     = 4
  message_retention   = 7
}

# Redis Cache
resource "azurerm_redis_cache" "main" {
  name                = "${replace(var.resource_group_name, "-", "")}redis"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  capacity            = 1
  family              = "C"
  sku_name            = "Standard"
  enable_non_ssl_port = false
  minimum_tls_version = "1.2"
  tags                = var.tags
}

# Application Insights
resource "azurerm_application_insights" "main" {
  name                = "${var.resource_group_name}-ai"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "web"
  tags                = var.tags
}

# Key Vault
resource "azurerm_key_vault" "main" {
  name                        = "${replace(var.resource_group_name, "-", "")}kv"
  location                    = azurerm_resource_group.main.location
  resource_group_name         = azurerm_resource_group.main.name
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  soft_delete_enabled         = true
  purge_protection_enabled    = false
  
  tags = var.tags
}

data "azurerm_client_config" "current" {}

# Azure OpenAI
resource "azurerm_cognitive_account" "openai" {
  name                = "${replace(var.resource_group_name, "-", "")}openai"
  location            = "East US"
  resource_group_name = azurerm_resource_group.main.name
  sku_name            = "S0"
  kind                = "OpenAI"
  
  tags = var.tags
}

# OpenAI Deployment
resource "azurerm_cognitive_deployment" "gpt4" {
  name                = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.openai.id
  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = "2024-07-18"
  }
  
  sku {
    name = "Standard"
    capacity = 10
  }
}