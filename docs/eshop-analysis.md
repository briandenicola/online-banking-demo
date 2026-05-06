# eShopOnAKS Analysis — Patterns for online-banking-demo

> **Author:** Danny (Lead/Architect) | **Date:** 2025-07-21
> **Source:** [briandenicola/eShopOnAKS](https://github.com/briandenicola/eShopOnAKS)

## Executive Summary

eShopOnAKS is Brian's workshop-format repo that deploys the .NET eShop microservices application to AKS. It excels at **documentation-as-a-guided-walkthrough**, **production-grade cluster configuration**, and **observable deployment patterns**. online-banking-demo should adopt its documentation structure, Taskfile-driven developer experience, testing/chaos patterns, and cluster-config approach — while keeping its own architecture (Redis Streams events, mixed .NET/Python/Go stack, Cosmos DB).

---

## 1. Repository Structure Comparison

### eShopOnAKS Layout
```
eShopOnAKS/
├── .assets/                  # Screenshots, architecture diagrams
├── .devcontainer/            # Codespaces-ready dev environment
├── .github/workflows/        # Playwright E2E workflow
├── charts/                   # Helm charts (app, certs, infrastructure)
│   ├── app/
│   ├── certs/
│   └── infrastructure/
├── cluster-config/           # GitOps-managed K8s addons (Kustomize)
│   ├── cert-manager/
│   ├── hubble/
│   ├── istio/
│   ├── keda/
│   └── prometheus/
├── docs/                     # 11 structured markdown guides
├── experiments/              # Azure Chaos Studio experiments
├── infrastructure/           # Terraform modules
│   ├── aks/
│   ├── chaos/
│   ├── core/ (networking)
│   ├── keyvault/
│   ├── monitoring/
│   ├── redis/
│   └── sql/
├── scripts/                  # PowerShell deploy/build automation
├── tests/                    # Playwright E2E tests
├── .aliases.rc               # Shell aliases for kubectl/docker
├── Taskfile.yaml             # Single-command orchestration
├── toc.md                    # Table of Contents for docs
└── README.md                 # Overview + architecture diagrams
```

### online-banking-demo Layout (Current)
```
online-banking-demo/
├── .github/workflows/        # CI workflow
├── deploy/kustomize/base/    # K8s manifests (flat)
├── docs/                     # 5 docs (architecture, deployment, testing, etc.)
├── infra/
│   ├── cloud/                # Single main.tf (monolith)
│   └── local/                # AI Foundry local setup
├── src/                      # 9 microservices + shared contracts
├── Taskfile*.yml             # Local/cloud sub-taskfiles
├── docker-compose.yml        # Local development
└── README.md
```

### Gap Analysis: Structure
| Feature | eShopOnAKS | online-banking-demo | Action |
|---------|-----------|---------------------|--------|
| Architecture diagrams | ✅ `.assets/` with PNG diagrams | ❌ Text-only in docs | **Add** visual architecture diagrams |
| DevContainer / Codespaces | ✅ Full setup with post-create script | ❌ None | **Add** `.devcontainer/` configuration |
| Table of Contents | ✅ `toc.md` with section-level links | ❌ None | **Add** navigation hub |
| Terraform modules | ✅ Modularized (core/aks/kv/monitoring/redis/sql) | ❌ Single `main.tf` monolith | **Refactor** into modules (matches Layer 2 plan) |
| Cluster config (GitOps) | ✅ `cluster-config/` with Kustomize | ⚠️ `deploy/kustomize/base/` (flat) | **Restructure** into cluster-config + app config |
| Helm charts | ✅ App + infrastructure charts | ❌ Raw K8s manifests | **Evaluate** — Kustomize may be sufficient |
| Chaos engineering | ✅ Azure Chaos Studio experiments | ❌ None | **Add** chaos experiments |
| E2E tests | ✅ Playwright with GitHub Actions | ❌ Tests exist but CI job is placeholder | **Implement** E2E test pipeline |
| Shell aliases | ✅ `.aliases.rc` | ❌ None | **Add** developer convenience aliases |

---

## 2. Documentation Quality — What eShopOnAKS Does Well

### Workshop-Style Guided Steps
Every doc page in eShopOnAKS follows a consistent pattern:
1. **Concept explanation** — What the component does and why
2. **Numbered task steps** with checkmarks (`:heavy_check_mark:`)
3. **Manual steps** — Full command-line examples for understanding
4. **Example output** — Actual terminal output showing what success looks like
5. **Optional Next Steps** — Challenge questions (`:bulb:` and `:question:`) for deeper learning
6. **Navigation** — Previous/Next/Home links at bottom of every page

This is the **single most valuable pattern** to adopt. online-banking-demo has good deployment docs but lacks the guided walkthrough format.

### Documentation Pages in eShopOnAKS
| Page | Content | Adopt? |
|------|---------|--------|
| `architecture.md` | Service descriptions, tech stack, communication patterns | ✅ Already have — enhance with visuals |
| `prerequisites.md` | Required tools, environment setup, Codespaces link | ✅ **Must add** — we have no prerequisites doc |
| `infrastructure.md` | Step-by-step infra deployment with component explanations | ✅ **Must add** — our deployment docs lack this detail |
| `certificates.md` | cert-manager + Istio TLS setup walkthrough | ✅ **Add** as part of Layer 1 implementation |
| `build.md` | Container build + Trivy scanning with example output | ✅ **Add** — we have no build documentation |
| `deployment.md` | Helm deploy with secrets/configmaps explanation | ✅ **Enhance** existing deployment docs |
| `monitoring.md` | OTEL pipeline, Grafana, App Insights with screenshots | ✅ **Must add** — no observability docs |
| `testing.md` | Playwright E2E + Chaos Engineering | ✅ **Must add** — testing doc is minimal |
| `scaling.md` | PDB + KEDA HTTP scaler examples | ✅ **Add** as part of production readiness |
| `cost-management.md` | Kubecost integration | ⚠️ Nice-to-have for later |
| `code.md` | Source code modifications for OTEL/metrics | ✅ **Add** — document instrumentation changes |

### README Quality
eShopOnAKS README includes:
- Architecture diagrams (embedded PNGs)
- Codespaces + DevContainer badges with one-click launch
- Link to detailed Table of Contents
- Copilot integration callout
- Roadmap with checked/unchecked items

online-banking-demo README should adopt: badges, architecture diagram, TOC link, and roadmap.

---

## 3. Infrastructure as Code Patterns

### Terraform Module Structure (eShopOnAKS)
```
infrastructure/
├── main.tf            # random_pet + random_id for naming, locals
├── modules.tf         # Module declarations with dependency chains
├── variables.tf       # Minimal variables (region, sku, k8s_version)
├── outputs.tf         # APP_NAME, cluster/RG names for scripts
├── identities.tf      # Workload Identity + federated credential
├── roles.tf           # RBAC assignments
├── providers.tf       # Provider config
├── references.tf      # Data sources
├── rg.tf              # Resource group
├── openai.tf          # Optional OpenAI (conditional deploy)
├── core/              # VNet, subnets, NSGs
├── aks/               # Cluster, node pools, Flux, ACR, logging
├── keyvault/          # Key Vault + private endpoint
├── monitoring/        # Log Analytics, App Insights, Grafana
├── redis/             # Azure Redis (optional)
├── sql/               # PostgreSQL (optional)
└── chaos/             # Azure Chaos Studio (optional)
```

### Key Patterns Worth Adopting

1. **Convention-based naming:** `random_pet + random_id` generates unique names (e.g., `airedale-60249`). All resources derive from this single name. No variables for individual resource names.

2. **Modular dependency chains:** `modules.tf` declares all modules with explicit `depends_on` — core → keyvault → monitoring → aks → sql/redis. Matches our Layer-cake approach.

3. **Optional resources via count:** `count = var.deploy_redis ? 1 : 0` — clean conditional deployment without complexity.

4. **Outputs drive scripts:** Terraform outputs (`APP_NAME`, `AKS_CLUSTER_NAME`, etc.) are consumed by Taskfile and PowerShell scripts — no manual value passing.

5. **Workload Identity pattern:** Federated identity credential binds K8s service account to Azure managed identity — exactly what we need for our services.

### What online-banking-demo Should Do
- **Refactor `infra/cloud/main.tf`** into modules following this pattern (already planned in Layer 2)
- **Adopt the outputs-drive-scripts pattern** for Taskfile integration
- **Keep our existing naming convention** (`${resource_name}-suffix`) — it already follows this pattern

---

## 4. Kubernetes & Cluster Configuration

### GitOps with Flux (eShopOnAKS)
eShopOnAKS uses **Azure Flux extension** (deployed via Terraform) with multiple Kustomizations:
- `istio-cfg` — Istio mesh configuration (ConfigMaps, RBAC)
- `istio-gw` — Istio gateway (depends on istio-cfg)
- `addons` — Prometheus, KEDA, cert-manager (depends on istio-cfg)

This is configured in `infrastructure/aks/flux.tf` and points at `cluster-config/` in the same repo.

### cluster-config Structure
```
cluster-config/
├── kustomization.yaml          # Root: includes prometheus, keda, cert-manager
├── cert-manager/
│   └── cert-manager.yaml       # HelmRelease for cert-manager
├── istio/
│   ├── configuration/
│   │   ├── istio-configuration.yaml  # Mesh config (access logging, tracing)
│   │   └── istio-cluster-roles.yaml  # VirtualService RBAC
│   └── gateway/
│       └── default-ingress.yaml      # Istio Gateway definition
├── keda/
│   └── (KEDA HTTP scaler config)
├── prometheus/
│   └── (Prometheus scrape config)
└── hubble/
    └── (Cilium Hubble observability)
```

### What to Adopt
- **Restructure `deploy/` to match:** Separate cluster-config (platform concerns) from app manifests
- **Flux GitOps in Terraform:** Add `azurerm_kubernetes_flux_configuration` resource (already planned)
- **Kustomization dependency ordering:** Ensures Istio mesh is ready before gateway, gateway before apps
- **Hubble for network observability:** Cilium is already enabled in our AKS — Hubble is a task command away

---

## 5. CI/CD & Build Automation

### eShopOnAKS Approach
- **No CI/CD for infra or app deploy** — intentionally uses Taskfile for transparency
- **Single GitHub Actions workflow:** `playwright.yml` — manual trigger E2E tests against deployed environment
- **Build via Taskfile:** `task build` → PowerShell script → `dotnet publish` to ACR
- **Trivy scanning:** Built into build process (scan containers after push)

### Gap Analysis
| Feature | eShopOnAKS | online-banking-demo | Action |
|---------|-----------|---------------------|--------|
| Taskfile orchestration | ✅ `task up/down/build/deploy/status` | ⚠️ Partial (local + cloud sub-taskfiles) | **Enhance** — add status, restart, dns commands |
| Build documentation | ✅ Full with example output | ❌ None | **Add** build guide |
| Container scanning | ✅ Trivy in build pipeline | ❌ None | **Add** Trivy scanning step |
| E2E test workflow | ✅ Playwright via GitHub Actions | ❌ Placeholder CI job | **Implement** Playwright E2E |
| Deploy workflow | ❌ Manual via Taskfile (intentional) | ⚠️ CI deploys via Flux | **Keep** — our Flux approach is better for production |

---

## 6. Security Posture

### eShopOnAKS Security Features
- **API Server authorized IP ranges** — Restricts cluster API access to deployer's IP
- **Azure RBAC for AKS** — No local accounts, AAD-integrated
- **Workload Identity** — Federated credentials for pod-to-Azure auth
- **Key Vault CSI driver** — Secrets mounted as K8s secrets via SecretProviderClass
- **Istio mTLS** — Service mesh encrypts pod-to-pod traffic
- **Private endpoints** — Optional for Redis, PostgreSQL, KeyVault
- **Cert Manager + Let's Encrypt** — Automated TLS certificate management
- **Network Security Groups** — On VNet subnets
- **Image cleaner** — AKS image cleaner enabled (48h interval)
- **Microsoft Defender** — Enabled for container scanning
- **Firewall update script** — Dynamic IP allowlisting for Codespaces

### What online-banking-demo Already Has (from Layer 1-4 plan)
- Istio mesh addon ✅
- Cilium CNI + network policies ✅
- cert-manager ✅
- Private endpoints (planned Layer 2) ✅
- APIM + AppGW (planned Layers 3-4) ✅

### Additional Security to Adopt
- **API server IP restrictions** — Add `authorized_ip_ranges` to AKS config
- **Image cleaner** — Enable in AKS cluster config
- **Microsoft Defender for Containers** — Add to monitoring module
- **Trivy in CI** — Container vulnerability scanning before deployment
- **Firewall update automation** — Script for dynamic IP environments

---

## 7. Observability

### eShopOnAKS Observability Stack
```
Application → OTEL SDK (traces, metrics, logs)
    ↓
OTEL Collector (otel-system namespace)
    ↓ zipkin (traces) + otlp (metrics/logs)
Azure Monitor Workspace → Application Insights + Managed Grafana
    ↓
Prometheus (metrics scraping from pods)
    ↓
Grafana Dashboards (threads, memory, network)
```

### Key Components
- **Azure Monitor Workspace** — Central telemetry store
- **Application Insights** — Distributed tracing, application map, logging
- **Managed Grafana** — Dashboards with Prometheus data source
- **OTEL Collector** — Deployed in `otel-system` namespace, pipelines for traces/metrics/logs
- **Prometheus** — Pod metrics scraping via cluster-config
- **Hubble** — Cilium network observability (optional `task hubble`)

### What to Adopt for online-banking-demo
1. **OTEL Collector deployment** — Add to cluster-config with same pipeline pattern
2. **Monitoring Terraform module** — Log Analytics + App Insights + Managed Grafana
3. **Prometheus scrape configs** — Via cluster-config GitOps
4. **Hubble integration** — Already have Cilium, just need Hubble UI
5. **Monitoring documentation** — Screenshots of dashboards, example queries

---

## 8. Developer Experience

### eShopOnAKS DX Features
| Feature | Implementation |
|---------|---------------|
| **One-click Codespaces** | `.devcontainer/` with all tools pre-installed |
| **Taskfile commands** | `task up` (full env), `task status`, `task restart`, `task down` |
| **Shell aliases** | `.aliases.rc` — k=kubectl, utils pod, docker shortcuts |
| **Post-create script** | Installs k9s, envsubst, task, skaffold, trivy, flux |
| **Post-start script** | Configures git, sources aliases |
| **Copilot integration** | Mentioned in README and VS Code extensions |
| **Convention naming** | `eshop_naming.ps1` derives all resource names from APP_NAME |

### What to Adopt
- **DevContainer config** — Critical for onboarding new contributors
- **Enhanced Taskfile** — Add `status`, `restart`, `logs` commands
- **Shell aliases** — `.aliases.rc` with project-specific shortcuts
- **Naming convention module** — Script that derives all names from `resource_name`

---

## 9. Testing

### eShopOnAKS Testing
- **Playwright E2E tests** — 3 spec files (AddItem, BrowseItem, RemoveItem)
- **Login setup fixture** — `login.setup.ts` handles authentication state
- **GitHub Actions workflow** — Manual trigger with URL input
- **Chaos Engineering** — Azure Chaos Studio (pod failures, network delays)
- **Test artifacts** — HTML reports uploaded to GitHub Actions

### What to Adopt
1. **Playwright E2E framework** — We have the testing doc but need actual tests
2. **Login setup pattern** — Reusable auth state across test suites
3. **GitHub Actions E2E workflow** — Manual trigger against deployed environment
4. **Chaos Engineering** — Azure Chaos Studio experiments for resilience testing

---

## 10. Patterns NOT to Adopt

| eShopOnAKS Pattern | Reason to Skip |
|--------------------|--------------  |
| Helm charts for app deployment | We use Kustomize — simpler, aligns with GitOps |
| PowerShell scripts | Our Taskfile + bash approach is simpler and cross-platform |
| Manual DNS record creation | We should automate this via Azure DNS zone |
| Optional SQL/Redis toggle | We have fixed dependencies (Cosmos + Redis) |
| Workshop-only (no CI/CD for deploy) | We need automated deployment via Flux |

---

## 11. Agentic / AI Features

### Current State in eShopOnAKS
- **OpenAI resource** in Terraform (optional, disabled by default)
- **Copilot** mentioned in README and DevContainer extensions
- **No agentic coding features** — no squad setup, no AI-assisted workflows

### What online-banking-demo Should Showcase
Since the goal is to be a showcase for **agentic coding AND secure cloud native apps**:
1. **Document the squad setup** — How agents (Danny, Basher, Linus, Livingston) work together
2. **Copilot setup steps** — `.github/copilot-setup-steps.yml` configuration
3. **Architecture Decision Records** — Document decisions made by agents and humans
4. **AI-assisted development workflow** — How to use agents for code review, implementation, testing

---

## 12. Summary: Priority Backlog Items

### Must Have (High Impact)
1. **Workshop-style documentation overhaul** — Prerequisites, infrastructure, build, deploy, monitoring, testing guides with guided steps and example output
2. **Table of Contents** (`toc.md`) — Navigation hub for all documentation
3. **Architecture diagrams** — Visual diagrams in `.assets/` directory
4. **DevContainer / Codespaces setup** — One-click development environment
5. **E2E testing with Playwright** — Actual tests + GitHub Actions workflow
6. **Observability stack documentation** — OTEL, Prometheus, Grafana, App Insights

### Should Have (Medium Impact)
7. **Terraform module refactoring** — Break `infra/cloud/main.tf` into modules
8. **cluster-config restructuring** — Separate platform config from app manifests
9. **Trivy container scanning** — In CI/CD pipeline
10. **Chaos Engineering setup** — Azure Chaos Studio experiments
11. **Enhanced Taskfile** — status, restart, logs, dns commands
12. **Shell aliases** — `.aliases.rc` for developer convenience

### Nice to Have (Low Impact)
13. **Kubecost integration** — Cost visibility
14. **Hubble network observability** — Already have Cilium
15. **CODE_OF_CONDUCT.md / CONTRIBUTING.md** — Community docs
16. **API server IP restrictions** — Additional AKS hardening

### Agentic Showcase (Unique to online-banking-demo)
17. **Squad documentation** — How agentic team works
18. **Copilot integration guide** — Setup steps, best practices
19. **ADR (Architecture Decision Records)** — Living decision log
20. **Developer onboarding guide** — From clone to running in 15 minutes
