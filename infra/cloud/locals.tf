#############################################
# LOCALS — Common values, resource group
#############################################
data "azurerm_client_config" "current" {}

data "http" "myip" {
  url = "http://checkip.amazonaws.com/"
}

locals {
  location            = var.region
  resource_name       = "${random_pet.this.id}-${random_id.this.dec}"
  resource_group_name = "${local.resource_name}-rg"
  aks_name            = "${local.resource_name}-aks"
  aks_node_rg_name    = "${local.aks_name}_nodes_rg"
  vnet_name           = "${local.resource_name}-vnet"
  vnet_cidr           = cidrsubnet("10.0.0.0/8", 8, random_integer.vnet_cidr.result)
  nodes_subnet_cidr   = cidrsubnet(local.vnet_cidr, 8, 3)
  pe_subnet_cidr      = cidrsubnet(local.vnet_cidr, 8, 4)
  jumpbox_subnet_cidr = cidrsubnet(local.vnet_cidr, 8, 6)
  storage_name        = "${substr(replace(random_uuid.guid.result, "-", ""), 0, 22)}sa"
  cosmos_name         = "${local.resource_name}-cosmos"
  openai_name         = "${local.resource_name}-foundry"
  cus_name            = "${local.resource_name}-cus"
  project_name        = "${local.resource_name}-project"
  redis_name          = "${local.resource_name}-redis"
  search_service_name = "${local.resource_name}-search"
  loganalytics_name   = "${local.resource_name}-logs"
  appinsights_name    = "${local.resource_name}-ai"
  keyvault_name       = substr("${replace(local.resource_name, "-", "")}kv", 0, 24)
  acr_name            = "${replace(local.resource_name, "-", "")}acr"
  jumpbox_name        = "${local.resource_name}-jump"
  bastion_name        = "${local.resource_name}-bastion"
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

