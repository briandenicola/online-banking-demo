# ADR-002: KeyVault CSI Driver over External Secrets Operator

**Status**: Accepted  
**Date**: 2026-05  
**Author**: Brian De Nicola

## Context

The application must synchronize secrets from Azure Key Vault into Kubernetes Secrets for use by pods (JWT signing key, Redis connection string, Application Insights connection string, OpenAI endpoint). Two main options exist in the AKS ecosystem: the Azure Key Vault Provider for Secrets Store CSI Driver (built into AKS) and the External Secrets Operator (community-managed).

## Decision

Use the **Azure Key Vault Provider for Secrets Store CSI Driver**, which is AKS-native and requires no additional operator installation.

### Reasons

1. **AKS built-in** — Enabled via `key_vault_secrets_provider` on the AKS cluster resource in Terraform. No Helm chart or operator to manage.
2. **Workload Identity integration** — The CSI driver uses the pod's workload identity (`banking-workload-identity` service account with federated credentials) to authenticate to Key Vault. Zero service principal secrets.
3. **SecretProviderClass CRD** — A single `SecretProviderClass` manifest maps Key Vault secrets to a K8s Secret (`banking-secrets`), which pods reference via `envFrom`.
4. **Convention alignment** — Brian's eShopOnAKS uses the same pattern (CSI driver + SecretProviderClass), keeping both projects consistent.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **External Secrets Operator** | Multi-provider support (AWS, GCP, Vault), richer sync options (polling intervals, templating) | Additional operator to install/upgrade, not AKS-native, more YAML for same outcome |
| **Terraform `kubernetes_secret`** | Simple, declarative in Terraform | Secrets in Terraform state (security risk), manual rotation, breaks GitOps |
| **Sealed Secrets** | GitOps-friendly (encrypted in repo) | Extra controller, manual encryption step, no Azure-native integration |

## Consequences

- **Positive**: Zero operator maintenance, workload identity auth (no keys), single manifest for all secrets
- **Negative**: CSI driver requires a pod mount to trigger sync (at least one pod must reference the volume), secrets only refresh on pod restart or CSI driver poll interval
- **Operational**: `deploy/kustomize/base/secret-provider-class.yaml` defines the mapping; `task cloud:infra:config` patches Key Vault name, tenant ID, and client ID from Terraform outputs
