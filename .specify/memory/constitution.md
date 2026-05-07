<!--
Sync Impact Report:
- Version change: 0.0.0 → 1.0.0
- Added principles: Security by Design, Private Networking Always, Entra ID for Service Authentication, Coding Best Practices, Convention over Configuration, Observability First
- Added sections: Technology Stack, Development Workflow
- Templates requiring updates: ✅ plan-template.md (Constitution Check section aligns), ✅ spec-template.md (FR section supports security requirements), ✅ tasks-template.md (security hardening phase present)
- Follow-up TODOs: None
-->

# Online Banking Demo Constitution

## Core Principles

### I. Security by Design (NON-NEGOTIABLE)

Security MUST be addressed at every layer from the first commit, not bolted on later.

- Every service MUST authenticate and authorize requests — no anonymous internal endpoints
- Secrets MUST NOT be stored in source code, environment variables passed from ConfigMaps, or plain K8s Secrets; use Azure Key Vault CSI driver or equivalent sealed-secret mechanism
- Container images MUST be scanned for vulnerabilities before deployment (Trivy or equivalent)
- All APIs MUST validate input at the boundary — never trust upstream services
- Dependencies MUST be kept current; Dependabot or equivalent MUST be enabled
- RBAC MUST be enforced at both the Azure resource layer and the application layer

### II. Private Networking Always (NON-NEGOTIABLE)

All service-to-service and service-to-data communication MUST traverse private networks.

- Azure resources (Redis, Cosmos DB, Key Vault, ACR) MUST use private endpoints — no public IPs exposed
- AKS cluster MUST use private API server or authorized IP ranges at minimum
- Ingress MUST terminate TLS; internal pod-to-pod traffic MUST use mTLS via service mesh (Istio)
- No service may be reachable from the public internet except the designated ingress gateway
- DNS resolution for Azure resources MUST use private DNS zones

### III. Entra ID for Service Authentication (NON-NEGOTIABLE)

Azure services MUST authenticate via Microsoft Entra ID (formerly AAD) — never access keys or connection string passwords in cloud deployments.

- All AKS workloads MUST use Workload Identity (federated credentials) to obtain Entra tokens
- Azure Managed Redis, Cosmos DB, Key Vault, and AI services MUST be accessed via RBAC role assignments — not shared keys
- Local/container development MAY use key-based auth (docker-compose) as a pragmatic exception
- The presence of `AZURE_CLIENT_ID` environment variable is the signal for Entra auth mode
- Token refresh MUST be handled automatically (SDK default credential or explicit refresh loop)

### IV. Coding Best Practices

All code MUST follow industry-standard patterns for the respective language and framework.

- .NET services: follow Microsoft coding conventions, use dependency injection, async/await patterns
- Go services: follow Effective Go, use structured error handling, context propagation
- Python services: follow PEP 8, use type hints, async frameworks where appropriate
- React frontend: functional components, hooks, proper state management
- All services MUST implement structured logging (JSON format for cloud, human-readable for local)
- All services MUST handle errors gracefully with meaningful error messages — no swallowed exceptions
- Code MUST be self-documenting; comments explain WHY, not WHAT

### V. Convention over Configuration

Prefer deriving values from existing context over introducing new variables or manual configuration.

- Resource names MUST follow a consistent pattern derived from a single `resource_name` local
- Environment-specific behavior MUST be driven by convention (e.g., `AZURE_CLIENT_ID` presence) not explicit mode flags
- Kustomize overlays handle environment differences — base manifests work for any target
- Taskfile commands MUST be idempotent and composable
- Terraform outputs drive downstream configuration — no hardcoded values in deployment scripts

### VI. Observability First

Every service MUST emit telemetry from day one — not added retroactively.

- All services MUST export OpenTelemetry traces, metrics, and logs to the OTEL Collector
- Health check endpoints (`/healthz`, `/readyz`) MUST be implemented on every service
- Distributed tracing context MUST propagate across service boundaries
- Application Insights integration via OTEL Collector — services never call App Insights directly
- Alerting thresholds MUST be defined for critical paths (latency, error rate, saturation)

## Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Infrastructure | Terraform + AzAPI | Azure-native IaC with RBAC-first patterns |
| Container Orchestration | AKS (Azure Kubernetes Service) | Managed K8s with Workload Identity |
| Service Mesh | Istio (AKS addon) | mTLS, traffic management, observability |
| Secrets | Azure Key Vault + CSI Driver | Zero secrets in K8s, automatic rotation |
| Database | Azure Cosmos DB | Global distribution, multi-model |
| Cache/Events | Azure Managed Redis | Balanced B0, Entra auth, port 10000/TLS |
| AI Services | Azure AI Foundry | Managed models with eval/red-teaming |
| Observability | OTEL Collector → App Insights | Vendor-neutral telemetry pipeline |
| Frontend | React + MUI | Component library with design system |
| Backend (.NET) | ASP.NET Core 8 | User, Account, Transaction, Transfer services |
| Backend (Go) | Go 1.22+ | Event processor (Redis Streams) |
| Backend (Python) | FastAPI | Anomaly, Budget, Chatbot services |
| CI/CD | GitHub Actions | Build, scan, deploy pipeline |
| Deployment | Kustomize | Overlay-based K8s manifest management |
| Task Runner | Taskfile | Composable, idempotent deployment commands |

## Development Workflow

### Local Development

- `docker-compose up` MUST bring up all services with zero Azure dependencies
- Redis runs as a plain container (port 6379, no auth) — dual-mode code handles this
- Services MUST start and pass health checks without cloud connectivity
- Hot-reload MUST be supported for frontend development

### Cloud Deployment

- `task deploy` MUST be the single command to deploy the full stack to AKS
- Deployment order: infrastructure → observability → cluster-config → application services
- All deployments MUST be idempotent — running twice produces the same result
- Rollback MUST be possible via `kubectl rollout undo` or redeploying a previous image tag

### Testing

- Unit tests MUST exist for business logic in every service
- Integration tests MUST cover cross-service communication
- E2E tests (Playwright) MUST validate critical user journeys
- CI MUST run all tests before merging to main

### Code Review

- All changes MUST go through PR review (human or AI-assisted)
- Security-sensitive changes (auth, networking, secrets) MUST have explicit security review
- Breaking API changes MUST be documented and versioned

## Governance

This constitution is the authoritative source of engineering standards for the online-banking-demo project. It supersedes conflicting guidance in any other document.

- **Amendment process:** Propose changes via PR with rationale. Constitution changes require project owner approval.
- **Compliance:** All PRs MUST be evaluated against these principles. Violations MUST be justified in writing or the PR MUST be revised.
- **Exceptions:** Local/container development is explicitly exempt from cloud-specific principles (Entra auth, private networking). This is the ONLY permitted exception.
- **Versioning:** Constitution follows semantic versioning. MAJOR = principle removal/redefinition, MINOR = new principle or section, PATCH = clarification.

**Version**: 1.0.0 | **Ratified**: 2026-05-07 | **Last Amended**: 2026-05-07
