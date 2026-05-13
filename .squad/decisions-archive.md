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

