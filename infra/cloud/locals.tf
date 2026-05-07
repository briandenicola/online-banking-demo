#############################################
# LOCALS — Common values, random resources, resource group, storage
#############################################

locals {
  location            = var.region
  resource_name       = "${random_pet.this.id}-${random_id.this.dec}"
  resource_group_name = "${local.resource_name}-rg"
  aks_name            = "${local.resource_name}-aks"
  aks_node_rg_name    = "${local.aks_name}_nodes_rg"
  vnet_name           = "${local.resource_name}-vnet"
  vnet_cidr           = cidrsubnet("10.0.0.0/8", 8, random_integer.vnet_cidr.result)
  nodes_subnet_cidr   = cidrsubnet(local.vnet_cidr, 8, 3)
  storage_name        = "${substr(replace(random_uuid.guid.result, "-", ""), 0, 22)}sa"
  cosmos_name         = "${local.resource_name}-cosmos"
  openai_name         = "${local.resource_name}-foundry"
  project_name        = "${local.resource_name}-project"
  redis_name          = "${local.resource_name}-redis"
  loganalytics_name   = "${local.resource_name}-logs"
  appinsights_name    = "${local.resource_name}-ai"
  keyvault_name       = "${local.resource_name}-kv"
  acr_name            = "${replace(local.resource_name, "-", "")}acr"
}

data "azurerm_client_config" "current" {}

resource "random_pet" "this" {}

resource "random_id" "this" {
  byte_length = 2
}

resource "random_uuid" "guid" {}

resource "random_integer" "vnet_cidr" {
  min = 10
  max = 250
}

resource "random_integer" "services_cidr" {
  min = 64
  max = 99
}

resource "random_integer" "pod_cidr" {
  min = 100
  max = 127
}

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
  name                      = local.storage_name
  resource_group_name       = azurerm_resource_group.this.name
  location                  = azurerm_resource_group.this.location
  account_tier              = "Standard"
  account_replication_type  = "LRS"
  shared_access_key_enabled = false
}
