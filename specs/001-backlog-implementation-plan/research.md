# Research: Backlog Implementation Plan

**Date**: 2026-05-07
**Status**: Complete

## R1: Istio AKS Addon Configuration

**Decision**: Use AKS-managed Istio addon (not standalone Istio)
**Rationale**: Managed lifecycle, automatic upgrades, native integration with AKS diagnostics. Brian's eShopOnAKS uses this pattern with revision-based canary upgrades (`istio.io/rev: asm-1-24`).
**Alternatives considered**:
- Standalone Istio via Helm: More control but requires manual upgrades and CRD management
- Linkerd: Lighter weight but less Azure integration and no AKS addon support

## R2: KeyVault CSI Driver vs External Secrets Operator

**Decision**: Use Azure KeyVault CSI Driver (already enabled on AKS)
**Rationale**: Native AKS addon, already provisioned with `secret_rotation_enabled = true` and 2m interval. Zero additional infrastructure. Supports both volume mounts and K8s Secret sync.
**Alternatives considered**:
- External Secrets Operator: More flexible (multi-cloud) but adds a controller dependency
- Sealed Secrets: Requires committing encrypted secrets to git — less clean for rotation

## R3: User Roles Implementation Pattern

**Decision**: JWT claim-based roles stored in Cosmos DB user document
**Rationale**: Roles embedded in JWT avoid per-request database lookups. Cosmos DB user document stores canonical role. .NET `[Authorize(Roles="Admin")]` attribute provides declarative enforcement.
**Alternatives considered**:
- Entra ID App Roles: More enterprise but couples to AAD; local dev would be harder
- Separate authorization service: Over-engineered for 2 roles (Admin, User)
- Redis-cached roles: Adds complexity without clear benefit for 2-role model

## R4: Azure AI Foundry Evaluation SDK

**Decision**: Use `azure-ai-evaluation` Python SDK for prompt evaluation and red teaming
**Rationale**: Native Azure integration, supports quality metrics (groundedness, relevance, coherence, fluency) and adversarial testing. Aligns with existing Python services.
**Alternatives considered**:
- Custom evaluation pipeline: More work, less standardized
- Promptflow: Heavier framework; SDK is sufficient for evaluation-only use case
- Third-party (LangSmith, Weights & Biases): Violates private networking principle

## R5: Playwright E2E Strategy

**Decision**: Playwright with auth state fixture (login once, reuse across tests)
**Rationale**: eShopOnAKS pattern. Playwright supports multiple browsers, trace-on-failure for debugging, and native GitHub Actions integration.
**Alternatives considered**:
- Cypress: Good DX but heavier bundle, no multi-browser
- Selenium: More mature but worse DX and slower

## R6: Terraform Module Boundaries

**Decision**: Split into 5 modules: `aks`, `redis`, `cosmos`, `keyvault`, `ai-foundry`
**Rationale**: Each module owns one Azure resource group concept. Outputs wire between modules via root `main.tf` locals. Matches eShopOnAKS infrastructure/ layout.
**Alternatives considered**:
- Keep monolith: Works today but 400+ line main.tf is hard to navigate
- Terragrunt: Over-engineered for single-environment project
- Per-resource modules: Too granular (50+ modules)

## R7: OTEL Collector Restart Issue

**Decision**: Add liveness probe with longer initialDelaySeconds + increase memory limits
**Rationale**: Collector logs show clean startup then SIGTERM after 30s — matches default K8s liveness probe timeout killing the pod before it's ready. Health check extension runs on localhost:13133.
**Alternatives considered**:
- Switch to DaemonSet: More resource-efficient but changes deployment model
- Remove health check: Masks real failures

## R8: Workshop Documentation Pattern

**Decision**: Follow eShopOnAKS format: concept → numbered steps → commands → output → challenges → navigation
**Rationale**: Proven pattern in Brian's existing work. Consistent user experience across all doc pages.
**Alternatives considered**:
- README-only: Insufficient for multi-page walkthrough
- Docusaurus/MkDocs: Adds build tooling dependency; raw markdown is simpler

## R9: Subnet CIDR Allocation for Private Endpoints & Agent Service

**Decision**: Use `cidrsubnet(local.vnet_cidr, 8, 4)` for private endpoints and `cidrsubnet(local.vnet_cidr, 8, 5)` for agents.
**Rationale**: VNet is /16, each subnet is /24 (254 IPs). Index 3 = AKS. Sequential indices 4, 5 follow convention. /24 is future-proof for PE growth and agent scaling.
**Alternatives considered**:
- Smaller subnets (/27): Constrains future PE count; no cost savings on a /16
- Non-sequential indices: Breaks convention-over-configuration principle

## R10: NSG Strategy for New Subnets

**Decision**: Single shared NSG for PE and agent subnets (separate from AKS-managed NSG).
**Rationale**: Reference pattern (`ai-application-architectures`) uses one NSG. Both subnets have similar traffic profiles. AKS manages its own NSG on node subnet.
**Alternatives considered**:
- Per-subnet NSG: Over-engineering unless rules diverge later
- No NSG: Violates Constitution Principle I (Security by Design)

## R11: Agent Subnet Delegation

**Decision**: Delegate agent subnet to `Microsoft.App/environments`.
**Rationale**: Azure AI Agent Service requires this delegation type. Confirmed in user's reference repo and Azure docs.
**Alternatives considered**:
- No delegation: Blocks Agent Service deployment
- `Microsoft.Web/serverFarms`: Wrong provider for Container Apps-based agents

## R12: Private DNS Zone Names (Azure-Canonical)

**Decision**: Use Azure's canonical private DNS zone names for each service:

| Service | Private DNS Zone | Sub-resource |
|---------|-----------------|--------------|
| Key Vault | `privatelink.vaultcore.azure.net` | `vault` |
| Cosmos DB (SQL) | `privatelink.documents.azure.com` | `Sql` |
| Azure Managed Redis | `privatelink.redisenterprise.cache.azure.net` | `redisEnterprise` |
| ACR | `privatelink.azurecr.io` | `registry` |
| AI Services (Cognitive) | `privatelink.cognitiveservices.azure.com` | `account` |
| Storage Account (blob) | `privatelink.blob.core.windows.net` | `blob` |

**Rationale**: These are the Azure-documented canonical zone names. Using non-standard names breaks automatic DNS resolution. Each zone must be linked to the VNet for resolution to work from AKS pods.
**Alternatives considered**:
- Azure DNS Private Resolver: Overkill for single-VNet topology
- Custom CoreDNS forwarding in AKS: Fragile, harder to maintain

## R13: Key Vault Deployer Access (Chicken-and-Egg)

**Decision**: Keep existing `var.deployer_ip` mechanism in `keyvault.tf`. The `network_acls` block allows the deployer's public IP via `ip_rules`, `bypass = "AzureServices"` ensures managed identities work. The private endpoint provides runtime connectivity for AKS pods.
**Rationale**: The deployer runs `terraform apply` from CI/CD or a developer machine outside the VNet. The IP allowlist is the standard Azure pattern — `default_action = "Deny"` blocks all other public traffic.
**Alternatives considered**:
- Self-hosted runner inside VNet: Circular dependency (AKS must be up first)
- Disabling firewall during apply then re-enabling: Race condition, not idempotent
- VPN/ExpressRoute: Overkill for a demo project

## R14: ACR Public Access Retention

**Decision**: Keep `public_network_access_enabled = true` on ACR. Add private endpoint so AKS pulls images privately. SKU is already `Premium` (required for PE support).
**Rationale**: GitHub Actions CI/CD pushes images from outside the VNet. AKS kubelet pulls via the private endpoint (faster, no egress charges). Azure-recommended pattern for CI/CD workflows.
**Alternatives considered**:
- Disable public + use self-hosted runner: Adds complexity, not worth it for demo
- ACR Tasks (build inside ACR): Requires rearchitecting CI/CD pipeline

## R15: AI Services Private Endpoint via AzAPI

**Decision**: Use `azurerm_private_endpoint` targeting `azapi_resource.this.id`. Sub-resource type is `account`.
**Rationale**: Private endpoints are ARM-level. PE doesn't care whether target was created via `azurerm` or `azapi` — it just needs the resource ID.
**Alternatives considered**:
- Creating PE via `azapi_resource`: Unnecessary complexity, `azurerm_private_endpoint` works fine

## R16: Azure Managed Redis PE Sub-Resource Type

**Decision**: Use `redisEnterprise` as the sub-resource name. DNS zone is `privatelink.redisenterprise.cache.azure.net`.
**Rationale**: Azure Managed Redis uses `Microsoft.Cache/redisEnterprise` resource provider. The sub-resource is `redisEnterprise`, NOT `redisCache` (which is for classic Azure Cache for Redis Basic/Standard/Premium).
**Alternatives considered**:
- `redisCache`: Wrong resource provider type

## R17: Storage Account Sub-Resource Scope

**Decision**: Create PE for `blob` only.
**Rationale**: The storage account is used by AI Foundry for model artifacts and project data — blob only. The project doesn't use Table, Queue, or File storage.
**Alternatives considered**:
- PE for all four sub-resources: Over-provisioning, increases Terraform complexity
- PE for blob + table: Table not currently used
