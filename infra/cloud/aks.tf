#############################################
# AKS — Azure Kubernetes Service cluster
#############################################

resource "azurerm_kubernetes_cluster" "main" {
  lifecycle {
    ignore_changes = [
      default_node_pool[0].node_count,
      kubernetes_version
    ]
  }

  name                = local.aks_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  node_resource_group = local.aks_node_rg_name
  kubernetes_version  = var.kubernetes_version
  dns_prefix          = local.aks_name
  sku_tier            = "Standard"

  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "SecurityPatch"

  local_account_disabled       = true
  run_command_enabled          = false
  azure_policy_enabled         = true
  open_service_mesh_enabled    = false
  cost_analysis_enabled        = true
  image_cleaner_enabled        = true
  image_cleaner_interval_hours = 48

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  default_node_pool {
    name                        = "system"
    temporary_name_for_rotation = "temp"
    node_count                  = var.aks_node_count
    vm_size                     = var.aks_node_size
    vnet_subnet_id              = azurerm_subnet.aks.id
    type                        = "VirtualMachineScaleSets"
    auto_scaling_enabled        = true
    min_count                   = 1
    max_count                   = var.aks_node_count * 2
    max_pods                    = 250
    os_sku                      = "AzureLinux"

    upgrade_settings {
      max_surge = "25%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = data.azurerm_client_config.current.tenant_id
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    service_cidr        = "10.${random_integer.services_cidr.result}.0.0/16"
    dns_service_ip      = "10.${random_integer.services_cidr.result}.0.10"
    pod_cidr            = "10.${random_integer.pod_cidr.result}.0.0/16"
  }

  workload_autoscaler_profile {
    keda_enabled                    = true
    vertical_pod_autoscaler_enabled = true
  }

  key_vault_secrets_provider {
    secret_rotation_enabled  = true
    secret_rotation_interval = "2m"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }

  monitor_metrics {}

  maintenance_window_auto_upgrade {
    frequency   = "Weekly"
    interval    = 1
    duration    = 4
    day_of_week = "Friday"
    start_time  = "21:00"
    utc_offset  = "-06:00"
  }

  maintenance_window_node_os {
    frequency   = "Weekly"
    interval    = 1
    duration    = 4
    day_of_week = "Saturday"
    start_time  = "21:00"
    utc_offset  = "-06:00"
  }

  tags = {
    AppName = local.resource_name
  }
}
