# Decision: Entra Agent ID Sidecar Activation — Kustomize Manifest

**Author:** Turk  
**Date:** 2026-05-12  
**Issue:** #20  
**Status:** Implemented

## Context

The account-opening-worker deployment needs the Entra Agent ID auth-sidecar to authenticate AI Foundry agent calls using workload identity. The sidecar was stubbed out (commented) in the manifest.

## Decisions

### 1. AGENT_ID_AGENT_IDENTITY via ConfigMap (not inline deployment placeholder)

Placed `AGENT_ID_AGENT_IDENTITY: "REPLACE_WITH_AZURE_CLIENT_ID"` in `banking-demo-config` configmap rather than hardcoding a placeholder in the deployment YAML. This keeps the sed-substitute-apply-restore pattern in one place (`_configmap:update` Taskfile task) and both the worker and sidecar containers receive the value via `envFrom`.

**Tradeoff:** All services sharing the configmap get this env var. They ignore it — same as existing `.NET`-specific keys like `Services__AccountService`.

### 2. AGENT_ID_SIDECAR_URL as explicit worker env var (not configmap)

`AGENT_ID_SIDECAR_URL: "http://localhost:5000"` is set directly on the worker container, not in the configmap. It's pod-topology-specific (localhost), so it shouldn't be in a shared configmap.

### 3. Istio excludeInboundPorts for sidecar (not excludeOutboundPorts)

Added `traffic.sidecar.istio.io/excludeInboundPorts: "5000"` on the worker pod. The sidecar runs on localhost so Istio shouldn't intercept its traffic with mTLS. The existing `excludeOutboundPorts: "10000"` for Redis is unchanged.

### 4. Sidecar gets AZURE_CLIENT_ID from workload identity webhook

The pod has `azure.workload.identity/use: "true"` — the Azure workload identity webhook injects `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_FEDERATED_TOKEN_FILE` into ALL containers in the pod, including the sidecar. No manual wiring needed for these.

## Files Changed

- `deploy/kustomize/base/account-opening-service.yaml` — sidecar container, worker env vars, Istio annotation
- `deploy/kustomize/base/configmap.yaml` — added `AGENT_ID_AGENT_IDENTITY` placeholder
- `tasks/Taskfile.cloud.yml` — sed substitution + var for `AZURE_CLIENT_ID` in `_configmap:update`
