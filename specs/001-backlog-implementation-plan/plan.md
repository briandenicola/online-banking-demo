# Implementation Plan: Add Private Endpoints & Agent Service Subnets

**Branch**: `001-backlog-implementation-plan` | **Date**: 2026-05-07 | **Spec**: [spec.md](./spec.md)
**Input**: User request to add two subnets (private endpoints + Agent Service) following the pattern from `briandenicola/ai-application-architectures`

## Summary

Add two new subnets to the VNet in `infra/cloud/networking.tf`:
1. **private-endpoints** — for Azure Private Link connections (Redis, Cosmos, KV, ACR, OpenAI)
2. **agents** — delegated to `Microsoft.App/environments` for Azure AI Agent Service

Both subnets get an NSG. This aligns with Constitution Principle II (Private Networking Always) by enabling future private endpoint migration and Agent Service integration.

## Technical Context

**Language/Version**: Terraform (HCL) with AzureRM + AzAPI providers  
**Primary Dependencies**: `azurerm_subnet`, `azurerm_network_security_group`, `azurerm_subnet_network_security_group_association`  
**Storage**: N/A  
**Testing**: `terraform validate` + `terraform plan`  
**Target Platform**: Azure (eastus)  
**Project Type**: Infrastructure-as-Code  
**Constraints**: Must fit within existing VNet CIDR (`cidrsubnet("10.0.0.0/8", 8, random)` = a /16 block). Current AKS subnet uses index 3.  
**Scale/Scope**: 2 new subnets, 1 NSG, 2 NSG associations, 2 new locals

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Security by Design | ✅ PASS | NSG attached to both subnets |
| II. Private Networking Always | ✅ PASS | Enables PE migration for all Azure services |
| III. Entra ID for Auth | N/A | No auth changes |
| IV. Coding Best Practices | ✅ PASS | Follows reference pattern from ai-application-architectures |
| V. Convention over Config | ✅ PASS | CIDR derived from `local.vnet_cidr` using `cidrsubnet` |
| VI. Observability First | N/A | No telemetry changes |

## Project Structure

### Documentation (this feature)

```text
specs/001-backlog-implementation-plan/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (N/A for infra-only)
├── quickstart.md        # Phase 1 output
└── contracts/           # Phase 1 output (N/A for infra-only)
```

### Source Code (repository root)
```text
infra/cloud/
├── networking.tf        # VNet + all subnets + NSG + associations (modified)
├── locals.tf            # Add pe_subnet_cidr, agent_subnet_cidr locals (modified)
└── ...                  # No other files affected
```

**Structure Decision**: All networking resources live in `networking.tf`. CIDR calculations live in `locals.tf`.

## Implementation Details

### Changes to `infra/cloud/locals.tf`

Add two new CIDR locals derived from `local.vnet_cidr`:

```hcl
pe_subnet_cidr    = cidrsubnet(local.vnet_cidr, 8, 4)   # /24 for private endpoints
agent_subnet_cidr = cidrsubnet(local.vnet_cidr, 8, 5)   # /24 for agent service
```

Index 3 is taken by AKS. Use 4 and 5.

### Changes to `infra/cloud/networking.tf`

Add (following the reference pattern from `ai-application-architectures`):

1. **`azurerm_subnet.private_endpoints`** — subnet for Private Link endpoints
2. **`azurerm_subnet.agents`** — subnet delegated to `Microsoft.App/environments`
3. **`azurerm_network_security_group.this`** — shared NSG for both new subnets
4. **`azurerm_subnet_network_security_group_association.pe`** — attach NSG to PE subnet
5. **`azurerm_subnet_network_security_group_association.agents`** — attach NSG to agents subnet

### Reference Pattern (from `briandenicola/ai-application-architectures`)

```hcl
resource "azurerm_subnet" "private-endpoints" {
  name                 = "private-endpoints"
  address_prefixes     = [local.pe_subnet_cidr]
}

resource "azurerm_subnet" "agents" {
  name             = "agents"
  address_prefixes = [local.agent_subnet_cidr]
  delegation {
    name = "agent-delegation"
    service_delegation {
      name = "Microsoft.App/environments"
    }
  }
}
```

### Outputs (optional)

Consider adding to `outputs.tf`:
- `pe_subnet_id` — needed when creating private endpoints in later phases
- `agent_subnet_id` — needed for Agent Service environment deployment

## Complexity Tracking

No constitution violations — this change is directly aligned with Principle II (Private Networking Always).
