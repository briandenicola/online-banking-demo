# online-banking-demo Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-09

## Active Technologies
- Terraform (HCL) with AzureRM + AzAPI providers + `azurerm_subnet`, `azurerm_network_security_group`, `azurerm_subnet_network_security_group_association` (001-backlog-implementation-plan)
- .NET 9 (C#), Go 1.22+, Python 3.11+ (FastAPI), React 18 (TypeScript), Terraform 1.5+ + ASP.NET Core, Cosmos DB SDK 3.x (Newtonsoft), StackExchange.Redis, Azure.Identity, FastAPI, MUI v9, Playwright, OTEL SDK, azure-ai-evaluation (001-backlog-implementation-plan)
- Azure Cosmos DB (Entra RBAC auth, Newtonsoft serialization), Azure Managed Redis (Balanced B0, port 10000/TLS, Entra auth) (001-backlog-implementation-plan)
- C# / .NET 9.0 (ASP.NET Core Web API) + Azure.AI.Projects (prerelease), Microsoft.Azure.Cosmos, Azure.Identity, Microsoft.AspNetCore.Authentication.JwtBearer (002-ai-anomaly-detection)
- Azure Cosmos DB — new containers `prompt-templates` and `evaluation-runs` (002-ai-anomaly-detection)
- Terraform HCL (AzureRM ~> 4, AzAPI ~> 2, Random ~> 3) + `azurerm_private_endpoint`, `azurerm_private_dns_zone`, `azurerm_private_dns_zone_virtual_network_link`, `azapi_resource` (for AI Services PE) (001-azure-private-endpoints)
- VNet /16 with 3 subnets: AKS (offset 3), Private Endpoints (offset 4), Agents (offset 5, Microsoft.App/environments delegation). 9 private endpoints, 10 private DNS zones. All PaaS services accessed via PE (public access disabled except ACR Premium). (001-azure-private-endpoints)
- N/A (infrastructure-only change) (001-azure-private-endpoints)

- ASP.NET Core, Gin/stdlib, FastAPI, React + MUI v9, OTEL SDK (001-backlog-implementation-plan)

## Project Structure

```text
backend/
frontend/
tests/
```

## Commands

# Add commands for 

## Code Style

: Follow standard conventions

## Recent Changes
- 001-azure-private-endpoints: Added Terraform HCL (AzureRM ~> 4, AzAPI ~> 2, Random ~> 3) + `azurerm_private_endpoint`, `azurerm_private_dns_zone`, `azurerm_private_dns_zone_virtual_network_link`, `azapi_resource` (for AI Services PE)
- 002-ai-anomaly-detection: Added C# / .NET 9.0 (ASP.NET Core Web API) + Azure.AI.Projects (prerelease), Microsoft.Azure.Cosmos, Azure.Identity, Microsoft.AspNetCore.Authentication.JwtBearer
- 001-backlog-implementation-plan: Added .NET 8 (C#), Go 1.22+, Python 3.11+ (FastAPI), React 18 (TypeScript), Terraform 1.5+ + ASP.NET Core, Cosmos DB SDK 3.x (Newtonsoft), StackExchange.Redis, Azure.Identity, FastAPI, MUI v9, Playwright, OTEL SDK, azure-ai-evaluation


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
