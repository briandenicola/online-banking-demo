variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "bankingdemo"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "aks_name" {
  description = "Name of the AKS cluster"
  type        = string
  default     = "banking-demo-aks"
}

variable "aks_node_count" {
  description = "Number of AKS nodes"
  type        = number
  default     = 2
}

variable "aks_node_size" {
  description = "VM size for AKS nodes"
  type        = string
  default     = "Standard_D2s_v3"
}

variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.30"
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}