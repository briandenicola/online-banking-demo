# Session: account-opening sidecar revert (issue #134)

**Date:** 2026-05-13  
**Agent:** Basher  
**Issue:** #134  
**Status:** ✅ Implemented (awaiting deploy)

## Summary

Reverted account-opening-service from Entra Agent ID sidecar auth back to plain workload-identity pattern. Production logs showed sidecar token acquisition failing (`Failed to acquire token from sidecar after 3 attempts`), blocking document extraction pipeline.

## Changes

- 4 files modified: worker.py, sidecar_credential.py (deprecation comment), README.md, kustomize deployment manifest
- Pod spec now mirrors ai-service.yaml (init + main + istio, no app sidecar)
- DefaultAzureCredential handles Foundry agent auth; no sidecar container required

## Reference Pattern

ai-service.yaml demonstrates working workload-identity auth for Foundry agents in this project.

## Next Steps

Brian: Review, build, deploy. No RBAC changes needed.
