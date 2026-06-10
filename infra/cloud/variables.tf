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
