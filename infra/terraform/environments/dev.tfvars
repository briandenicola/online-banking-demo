resource_group_name = "banking-demo-rg"
location            = "East US"
aks_name            = "banking-demo-aks"
aks_node_count      = 2
aks_node_size       = "Standard_D2s_v3"
kubernetes_version  = "1.30"

tags = {
  Environment = "dev"
  Project     = "banking-demo"
  Owner       = "demo"
}