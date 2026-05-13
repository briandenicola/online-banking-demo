# Decisions Archive

**Purpose:** Store decisions older than 30 days to keep decisions.md manageable.

**Current Policy:** decisions.md is now ~218KB. Archive entries older than 2026-04-13 (30 days before 2026-05-13).

**Note:** Most entries are recent (2026-05-xx from P2 Wave 1). A full archival sweep extracting 2025 entries will be done when decisions.md next requires pruning.

## Archived Entries
(To be populated in future archival sweeps)

# Decision: Kubernetes Deployment Best Practices

**Author:** Danny (Lead/Architect)
**Date:** 2026-05-05
**Status:** Implemented
**Branch:** squad/k8s-review

## Context

The existing `deploy/kustomize/base/app.yaml` was a monolithic manifest with several production-readiness issues: wrong container ports (docker-compose host ports instead of internal), no health probes, missing Services, no autoscaling, no security contexts, and `:latest` image tags.

## Decision

Refactored into per-service files with full production best practices:

| Practice | Implementation |
|----------|---------------|
| Container ports | .NET=8080, Python=8001/8002/8003, Go=8080 |
| Health probes | liveness=/healthz, readiness=/readyz on all |
| Services | ClusterIP for all 9 deployments |
| HPA | user-service + account-service (2-5, 70% CPU) |
| Security | runAsNonRoot, no privilege escalation, RO filesystem where possible |
| Image tags | Semver :1.0.0 (digest pinning via CI) |
| Config | ConfigMap for OTEL, service URLs, Redis host |
| Redis | Dedicated deployment in K8s (not just docker-compose) |
| Ingress | ingressClassName instead of deprecated annotation |

## File Structure

```
deploy/kustomize/base/
├── kustomization.yaml
├── namespace.yaml
├── configmap.yaml
├── user-service.yaml
├── account-service.yaml
├── transaction-service.yaml
├── transfer-service.yaml
├── ai-service.yaml
├── budget-service.yaml
├── chatbot-service.yaml
├── event-processor.yaml
├── redis.yaml
├── hpa.yaml
└── ingress.yaml
```

## Deferred Items

- **NetworkPolicies** — Requires overlay-specific rules (dev vs prod)
- **PodDisruptionBudgets** — Need to align with HPA min replicas
- **Image digest pinning** — Should be automated by CI on tag push
- **Secrets management** — Currently references `banking-secrets` (needs External Secrets or Sealed Secrets)

## Consequences

- GitOps diffs are cleaner (per-file changes)
- Deployments will actually health-check and auto-restart unhealthy pods
- user-service and account-service scale under load
- Pods run with minimal privileges
- Services can discover each other via DNS (configmap URLs)


---

# Decision: Deploy OTEL Collector with App Insights Exporter

**Author:** Basher
**Date:** 2025-07
**Status:** proposed

## Context

Brian requested an OpenTelemetry Collector deployment to centralize traces/metrics/logs and export them to Azure Application Insights. The App Insights resource and Terraform output already exist.

## Decision

1. **Single manifest file** (`deploy/kustomize/observability/otel-collector.yaml`) containing Namespace (`observability`), Service, Deployment, and ConfigMap. Separate kustomization directory since base enforces `namespace: banking-demo`.
2. **Secret-based connection string** — The collector reads `APPINSIGHTS_CONNECTION_STRING` from a K8s Secret (`appinsights-secret` in `observability` namespace). The OTEL config uses native `${env:APPINSIGHTS_CONNECTION_STRING}` substitution.
3. **Operator responsibility** — The K8s secret must be created out-of-band (e.g., via Terraform's `kubernetes_secret` resource or a CI step using the existing `application_insights_connection_string` output).
4. **Image pinned** to `otel/opentelemetry-collector-contrib:0.151.0`.
5. **OTEL endpoint re-added** to the shared configmap so all services can send telemetry to the collector.

## Alternatives Considered

- Hardcoding connection string in ConfigMap — rejected (secret material).
- Helm chart for collector — rejected (project uses Kustomize).
- Deploying in `banking-demo` namespace — rejected (separation of concerns).

## Consequences

- All services can now export OTLP telemetry to the collector.
- Operator must create `appinsights-secret` in `observability` namespace before deploying.
- Future: consider adding a `SealedSecret` or External Secrets Operator for GitOps-friendly secret management.

---

# Decision: Remove Legacy Gateway Directory

**Date:** 2025-07-16
**Author:** Danny (Lead/Architect)
**Status:** Implemented
**Requested by:** Brian

## Context

The `gateway/` directory contained an nginx reverse proxy with njs-based JWT validation (`jwt_validate.js`). This component was superseded by Istio ingress gateway, which now handles ingress routing, mTLS, and authorization policy at the mesh level.

## Decision

Remove the entire `gateway/` directory and all references to it:

- **Deleted:** `gateway/Dockerfile`, `gateway/jwt_validate.js`
- **Cleaned:** `docker-compose.yml` — removed the `gateway` service block (build, ports, env, volumes, depends_on) and the `depends_on: gateway` from `ui-app`
- **Retained:** Root-level `nginx.conf` (still used by docker-compose for local API routing)
- **No action needed:** CI/CD workflows, kustomize manifests, and Taskfile references were already clean (Taskfile.e2e.yml references Istio's `aks-istio-ingressgateway-external`, not the legacy gateway)

## Rationale

- Dead code increases maintenance burden and confuses onboarding
- JWT validation in njs was a local-only workaround; Istio `RequestAuthentication` + `AuthorizationPolicy` is the production path
- Reduces docker-compose surface area and build time

## Risks

- **Local dev without Istio:** The `ui-app` service no longer depends on a gateway. For local docker-compose usage, the root `nginx.conf` still provides routing. If JWT auth is needed locally, it must be added to individual services or a new lightweight proxy.

## Commit

`chore: remove legacy gateway — replaced by Istio ingress`
