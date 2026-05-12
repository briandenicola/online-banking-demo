### Decision: Entra Agent ID Sidecar Credential for Foundry Agents
**Date:** 2026-05-12
**Author:** Basher
**Priority:** P1
**Status:** Implemented

**Context:** The account-opening worker's 3 Foundry agent consumers (identity verification, compliance check, provisioning) need Azure AI tokens. In K8s with Entra Agent ID, a sidecar container provides tokens via HTTP. `DefaultAzureCredential` doesn't know about this sidecar.

**Decision:**
1. Created `SidecarTokenCredential` (`app/sidecar_credential.py`) — conforms to Azure `TokenCredential` protocol, fetches bearer tokens from the auth-sidecar HTTP endpoint with retry/backoff.
2. Worker.py reads `AGENT_ID_SIDECAR_URL` + `AGENT_ID_AGENT_IDENTITY` env vars. If both set, Foundry consumers get `SidecarTokenCredential`; otherwise falls back to `DefaultAzureCredential` (backward compat for local dev).
3. `init_agents.py` keeps `DefaultAzureCredential` — init containers run before sidecars start.
4. Removed silent `DefaultAzureCredential()` fallback inside consumer `__init__` methods — credential is now required from caller. `RuntimeError` on `None`.

**Rationale:** Centralizes credential creation in worker.py (single responsibility). Prevents consumers from silently masking misconfiguration. Sidecar pattern is standard for Entra Agent ID on AKS.

**Impact:** Requires `AGENT_ID_SIDECAR_URL` and `AGENT_ID_AGENT_IDENTITY` env vars in K8s deployment manifests when sidecar is deployed. No breaking change for local dev / docker-compose.
