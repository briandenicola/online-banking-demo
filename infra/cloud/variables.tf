variable "region" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "tags" {
  description = "Application name for tagging"
  type        = string
  default     = "Online Banking Demo"
}

variable "aks_node_count" {
  description = "Number of AKS nodes"
  type        = number
  default     = 3
}

variable "aks_node_size" {
  description = "VM size for AKS nodes"
  type        = string
  default     = "Standard_D4s_v3"
}

variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.35.3"
}

variable "deploy_embedding_model" {
  description = "Deploy the text-embedding-ada-002 model (not available in all regions)"
  type        = bool
  default     = false
}

variable "keyvault_allowed_ip_rules" {
  description = "Additional IP ranges (in CIDR notation) to allow Key Vault access during bootstrap. The detected deployer IP is always added. Use this to add more IPs if your egress is NAT'd across multiple addresses."
  type        = list(string)
  default     = []
}

#############################################
# JUMPBOX — In-VNet Linux VM reached through Azure Bastion (Developer SKU).
# Provides private-network line of sight to the Key Vault / Cosmos / Redis
# private endpoints so operators can run data-plane bootstrap (notably
# scripts/setup-keyvault-secrets.sh).
#############################################

variable "jumpbox_vm_size" {
  description = "VM size for the in-VNet jumpbox"
  type        = string
  default     = "Standard_D2s_v5"
}

variable "jumpbox_admin_username" {
  description = "Admin username for the jumpbox VM"
  type        = string
  default     = "manager"
}

variable "jumpbox_ssh_public_key_path" {
  description = "Path to the SSH public key authorized on the jumpbox VM"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}
