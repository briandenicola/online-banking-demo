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
