# online-banking-demo Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-12

## Active Technologies
- Terraform (HCL) with AzureRM + AzAPI providers + `azurerm_subnet`, `azurerm_network_security_group`, `azurerm_subnet_network_security_group_association` (001-backlog-implementation-plan)
- .NET 9 (C#), Go 1.22+, Python 3.11+ (FastAPI), React 18 (TypeScript), Terraform 1.5+ + ASP.NET Core, Cosmos DB SDK 3.x (Newtonsoft), StackExchange.Redis, Azure.Identity, FastAPI, MUI v9, Playwright, OTEL SDK, azure-ai-evaluation (001-backlog-implementation-plan)
- Azure Cosmos DB (Entra RBAC auth, Newtonsoft serialization), Azure Managed Redis (Balanced B0, port 10000/TLS, Entra auth) (001-backlog-implementation-plan)
- C# / .NET 9.0 (ASP.NET Core Web API) + Azure.AI.Projects (prerelease), Microsoft.Azure.Cosmos, Azure.Identity, Microsoft.AspNetCore.Authentication.JwtBearer (002-ai-anomaly-detection)
- Azure Cosmos DB — new containers `prompt-templates` and `evaluation-runs` (002-ai-anomaly-detection)
- Terraform HCL (AzureRM ~> 4, AzAPI ~> 2, Random ~> 3) + `azurerm_private_endpoint`, `azurerm_private_dns_zone`, `azurerm_private_dns_zone_virtual_network_link`, `azapi_resource` (for AI Services PE) (001-azure-private-endpoints)
- VNet /16 with 3 subnets: AKS (offset 3), Private Endpoints (offset 4), Agents (offset 5, Microsoft.App/environments delegation). 9 private endpoints, 10 private DNS zones. All PaaS services accessed via PE (public access disabled except ACR Premium). (001-azure-private-endpoints)
- N/A (infrastructure-only change) (001-azure-private-endpoints)
- Python 3.11+ + `fpdf2` (PDF generation — pure Python, LGPL v3, no system deps) (016-sample-documents-account-opening)
- File system — static PDFs + JSON committed to `tests/fixtures/sample-documents/` (016-sample-documents-account-opening)

- ASP.NET Core, Gin/stdlib, FastAPI, React + MUI v9, OTEL SDK (001-backlog-implementation-plan)

## Project Structure

```text
src/
├── account-opening-service/   # Python/FastAPI - Account opening workflow with AI doc processing
├── account-service/            # .NET 9 - Account management CRUD
├── ai-service/                 # Python/FastAPI - AI anomaly detection and risk scoring
├── budget-service/             # Python/FastAPI - Budget insights and transaction categorization
├── chatbot-service/            # Python/FastAPI - AI financial advice chatbot
├── event-processor/            # Go - Background Redis Stream consumer for audit logging
├── prompt-eval-service/        # .NET 9 - Prompt template management and evaluation
├── transaction-service/        # .NET 9 - Transaction recording and retrieval
├── transfer-service/           # .NET 9 - Peer-to-peer and account transfers
├── user-service/               # .NET 9 - Authentication and user management
├── ui-app/                     # React 19 + TypeScript - Frontend web application
└── shared/                     # Shared contracts and utilities

infra/
├── cloud/                      # Azure infrastructure-as-code (Terraform)
└── local/                      # Local development infrastructure (Terraform + nginx configs)

tests/
├── e2e/                        # End-to-end Playwright tests
└── fixtures/                   # Test data and fixtures
```

## Commands

# Add commands for 

## Code Style

: Follow standard conventions

## Recent Changes
- 016-sample-documents-account-opening: Added Python 3.11+ + `fpdf2` (PDF generation — pure Python, LGPL v3, no system deps)
- 001-azure-private-endpoints: Added Terraform HCL (AzureRM ~> 4, AzAPI ~> 2, Random ~> 3) + `azurerm_private_endpoint`, `azurerm_private_dns_zone`, `azurerm_private_dns_zone_virtual_network_link`, `azapi_resource` (for AI Services PE)
- 002-ai-anomaly-detection: Added C# / .NET 9.0 (ASP.NET Core Web API) + Azure.AI.Projects (prerelease), Microsoft.Azure.Cosmos, Azure.Identity, Microsoft.AspNetCore.Authentication.JwtBearer


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
