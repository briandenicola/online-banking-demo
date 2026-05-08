# ADR-001: Istio over Linkerd for Service Mesh

**Status**: Accepted  
**Date**: 2026-05  
**Author**: Brian De Nicola

## Context

The application requires a service mesh for mTLS between pods, traffic routing (VirtualService-based path routing to 10 microservices), and TLS termination at the ingress. AKS supports both Istio (as a managed addon) and Linkerd (self-managed).

## Decision

Use **Istio via the AKS managed addon** (`asm`), not Linkerd.

### Reasons

1. **AKS-managed lifecycle** — Microsoft handles Istio upgrades, patching, and control plane HA. Zero operator maintenance for the mesh itself.
2. **VirtualService routing** — Istio's VirtualService CRD provides path-based routing (`/api/users → user-service`, `/api/accounts → account-service`, etc.) that maps directly to the application's gateway-per-path architecture.
3. **cert-manager integration** — Istio's Gateway resource supports `credentialName` for TLS secrets, integrating cleanly with cert-manager and Let's Encrypt HTTP-01 challenges via an Istio-specific solver.
4. **Ecosystem familiarity** — Brian's eShopOnAKS reference project uses the same Istio addon pattern, enabling direct reuse of gateway, VirtualService, and cert-manager configurations.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Linkerd** | Lower resource overhead, simpler sidecar | Not AKS-managed; self-managed upgrades, no VirtualService CRD (uses HTTPRoute or TrafficSplit), smaller ecosystem |
| **No mesh (plain Ingress)** | Simplest setup | No mTLS, no traffic management, no observability mesh features |
| **NGINX Ingress + Calico** | Familiar Ingress controller | No sidecar mTLS, network policy only (L3/L4), more manual TLS config |

## Consequences

- **Positive**: Zero mesh maintenance, production-grade mTLS, familiar VirtualService routing
- **Negative**: Higher resource overhead than Linkerd (~200MB per sidecar), Istio upgrade tied to AKS addon release cadence
- **Operational**: Gateway and VirtualService configs live in `cluster-config/istio/gateway/`
