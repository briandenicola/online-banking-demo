# Decision: Foundry Agent Provisioning via Init Container

**Author:** Basher  
**Date:** 2026-05-11  
**Status:** Proposed  
**Scope:** ai-service deployment

## Context

`FoundryAgent` from `agent_framework_foundry` connects to pre-registered agents in Azure AI Foundry. The `risk-assessor` and `transaction-categorizer` agents were failing with 404 because they hadn't been provisioned.

## Decision

Added a Kubernetes init container (`provision-agents`) that runs before the main ai-service container. It uses `httpx` + `DefaultAzureCredential` to call the Foundry REST API directly, checking if each agent version exists and creating it if missing.

### Why REST API instead of SDK

- Project directive prohibits `azure-ai-projects` SDK usage
- `agent-framework-foundry` (FoundryAgent) only *connects* to agents — it has no creation API
- The REST API is simple: GET to check, POST to create — `httpx` is already in the Dockerfile

### Why init container instead of startup logic

- Separates provisioning concern from application logic
- Fails fast — pod won't start if agents can't be provisioned
- Runs once per deployment, not on every restart

## Impact

- New file: `src/ai-service/app/init_agents.py`
- Modified: `deploy/kustomize/base/ai-service.yaml` (added initContainers block)
- No changes to Dockerfile (httpx already installed)
