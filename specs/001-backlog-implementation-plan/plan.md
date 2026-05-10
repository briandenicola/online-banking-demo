# Implementation Plan: Azure Private Endpoints

**Branch**: `001-azure-private-endpoints` | **Date**: 2026-05-09 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-backlog-implementation-plan/spec.md` (US10: Private Networking)

## Summary

Add Azure Private Endpoints with Private DNS Zones for all six PaaS services (Key Vault, Cosmos DB, Azure Managed Redis, ACR, AI Services, Storage Account) so that AKS workloads communicate exclusively over private networks. A new `/24` private-endpoint subnet is added to the existing VNet at CIDR offset 4. Public network access is already disabled on 5 of 6 services; ACR retains public access for CI/CD image pushes. The deployer IP firewall rule on Key Vault resolves the Terraform chicken-and-egg problem for writing secrets during `terraform apply`.

## Technical Context

**Language/Version**: Terraform HCL (AzureRM ~> 4, AzAPI ~> 2, Random ~> 3)
**Primary Dependencies**: `azurerm_private_endpoint`, `azurerm_private_dns_zone`, `azurerm_private_dns_zone_virtual_network_link`, `azapi_resource` (for AI Services PE)
**Storage**: N/A (infrastructure-only change)
**Testing**: `terraform validate`, `terraform plan` (dry-run), post-apply connectivity verification from AKS pods
**Target Platform**: Azure (eastus default)
**Project Type**: Infrastructure-as-Code (Terraform)
**Performance Goals**: Private endpoint DNS resolution < 10ms within VNet
**Constraints**: All services must be reachable from AKS pods via private IP; deployer must reach Key Vault via IP allowlist during apply
**Scale/Scope**: 6 private endpoints, 6 private DNS zones, 6 VNet links, 1 new subnet

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| **I. Security by Design** | ✅ PASS | All PaaS services moved behind private endpoints; no new public attack surface |
| **II. Private Networking Always** | ✅ PASS | This feature directly implements this principle — PE + Private DNS for every service |
| **III. Entra ID for Service Authentication** | ✅ PASS | No auth changes; existing Workload Identity / RBAC roles preserved |
| **IV. Coding Best Practices** | ✅ PASS | Terraform follows established patterns in the repo (resource naming from `local.resource_name`) |
| **V. Convention over Configuration** | ✅ PASS | PE subnet CIDR derived from existing `local.pe_subnet_cidr` convention; DNS zone names follow Azure standards |
| **VI. Observability First** | ✅ PASS | No telemetry changes; existing App Insights / OTEL pipeline unaffected |

**Gate Result**: ✅ All principles satisfied. Proceeding to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/001-backlog-implementation-plan/
├── plan.md              # This file
├── research.md          # Phase 0: Private endpoint research & decisions
├── data-model.md        # Phase 1: Terraform resource model
├── quickstart.md        # Phase 1: Quick-start deployment guide
├── contracts/           # Phase 1: Terraform interface contracts
└── tasks.md             # Phase 2: Implementation tasks (via /speckit.tasks)
```

### Source Code (repository root)

```text
infra/cloud/
├── locals.tf            # MODIFY: pe_subnet_cidr already defined (no change needed)
├── networking.tf        # MODIFY: Add pe-subnet + NSG
├── private-endpoints.tf # NEW: All 6 private endpoints + DNS zone groups
├── private-dns.tf       # NEW: All 6 private DNS zones + VNet links
├── keyvault.tf          # EXISTING: Already has public_network_access_enabled = false + network_acls
├── cosmos.tf            # EXISTING: Already has public_network_access_enabled = false
├── redis.tf             # EXISTING: Already has public_network_access = "Disabled"
├── acr.tf               # EXISTING: Premium SKU, public_network_access_enabled = true (keep)
├── ai.tf                # EXISTING: publicNetworkAccess = "Disabled"
├── storage.tf           # EXISTING: public_network_access_enabled = false
└── variables.tf         # EXISTING: deployer_ip already defined
```

**Structure Decision**: Infrastructure-only change. Two new Terraform files (`private-dns.tf`, `private-endpoints.tf`) added to `infra/cloud/`. One existing file modified (`networking.tf` for the PE subnet). All other files already have correct public access settings.

## Complexity Tracking

No constitution violations. No complexity justifications required.
