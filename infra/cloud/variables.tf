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
  description = "Deploy the text-embedding-ada-002 model, required by chatbot Agent Memory (not available in all regions)"
  type        = bool
  default     = true
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

#############################################
# BANKER COPILOT — authority-service platform wiring (epic #332, Phase 1)
#############################################

variable "kubernetes_namespace" {
  description = "Kubernetes namespace the banking workloads are deployed into. Used to build workload-identity federated credential subjects."
  type        = string
  default     = "banking-demo"
}

variable "authority_service_service_account" {
  description = "Kubernetes service account name bound to the dedicated authority-service workload identity (#336). Deliberately NOT the shared banking-workload-identity account — a distinct service account is what makes the isolation a control rather than a naming convention."
  type        = string
  default     = "authority-workload-identity"
}

variable "bootstrap_supervisor_email" {
  description = "Email address of the identity seeded with the `supervisor` role at user-service startup. Role promotion to supervisor is itself an L3 action and therefore cannot be performed through the Copilot harness, so the first supervisor must be provisioned out of band. Seeding is idempotent and is skipped entirely once any supervisor exists."
  type        = string
  default     = "supervisor@banking-demo.com"
}

variable "bootstrap_banker_email" {
  description = "Email address of the identity seeded with the `banker` role. Separation of duties needs two DISTINCT real identities to be demonstrable, so the banker is seeded alongside the supervisor rather than reusing one account."
  type        = string
  default     = "banker@banking-demo.com"
}

#############################################
# BANKER COPILOT — harness platform wiring (epic #332, Phase 2)
#############################################

variable "banker_copilot_service_account" {
  description = "Kubernetes service account name bound to the dedicated banker-copilot-service workload identity (#336). Distinct from both the shared banking-workload-identity account and the authority-service account: the two-service split of epic §2.1 is only a control if the harness cannot obtain authority-service's token."
  type        = string
  default     = "banker-copilot-workload-identity"
}

variable "copilot_session_retention_seconds" {
  description = "Cosmos default TTL for copilot-sessions documents. A session is a conversation, not a record of a decision — the decision lives in copilot-approvals, which has its own retention. Configuration, never a literal in code."
  type        = number
  default     = 2592000 # 30 days, matching ChatSessions
}

variable "copilot_artifact_retention_seconds" {
  description = "Cosmos default TTL for copilot-artifacts documents. Held as long as the trace that references them, so a replayed run can still resolve its artifact ids."
  type        = number
  default     = 7776000 # 90 days, matching Approval__RetentionSeconds
}

variable "copilot_trace_retention_seconds" {
  description = "Cosmos default TTL for copilot-traces frames. The trace is the eval input for #333, so this is the size of the eval corpus: raise it for a longer regression baseline, lower it to bound demo storage. Deliberately not -1 — an immortal per-frame container in a serverless demo account is a cost surprise, and an unconfigurable retention is a code change waiting to happen."
  type        = number
  default     = 7776000 # 90 days
}
