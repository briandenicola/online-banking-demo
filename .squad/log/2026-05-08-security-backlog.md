# Session Log: 2026-05-08 — Security Backlog Session

**Parallel spawns:** Basher (TLS), Turk (KeyVault CSI)  
**Outcome:** Both DONE  

## Summary

Orchestrated two parallel security features: TLS termination on Istio via cert-manager (Basher) and secrets migration from kubectl to Azure KeyVault + CSI driver (Turk). Both features completed without blocking dependencies.

## Key Decisions Captured

1. **TLS Cert-Manager**: Helm-based install, HTTP-01 challenge, ClusterIssuer, CUSTOM_DOMAIN env pattern
2. **KeyVault CSI**: Terraform-managed secrets, stable JWT key, kubelet identity RBAC, placeholder substitution pattern

## Follow-Up Tasks

- Users must set `CUSTOM_DOMAIN` in `.env` and create DNS A record for TLS setup
- Run `tls:install-cert-manager` once before `tls:setup`
- Verify CSI driver syncs secrets correctly in next deploy
