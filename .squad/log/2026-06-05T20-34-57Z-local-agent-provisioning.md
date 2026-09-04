# Session Log: Local Agent Provisioning

**Date:** 2026-06-05  
**Time:** 2026-06-05T20:34:57Z  
**Topic:** Mirroring AKS Foundry agent initContainer provisioning to local docker-compose

## Summary

Resolved how to run Foundry agent initialization on local development stack when AKS uses initContainers.

**Approach:** One-shot init services in compose that mirror AKS pattern with graceful fallbacks (skip if no Azure endpoint, soft-fail on errors).

**Key Design:** Added `is_local_redis` guard to prevent local Azure credentials from triggering managed auth on local redis container.

## Outcome

- Local compose stack maintains parity with AKS provisioning pattern
- Developers without Azure AI access still get working local stack
- No AKS manifest changes needed
- Verified: compose config valid, health checks pass, login works
