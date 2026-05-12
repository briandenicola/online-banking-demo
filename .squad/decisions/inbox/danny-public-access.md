# Decision Needed: ACR Public Access & Build Strategy

**Author:** Danny (Lead/Architect)
**Date:** 2025-07-16
**Issue:** #39

## Context

Disabling `public_network_access_enabled` on ACR (per #39) locks down the registry to private endpoint traffic only. However, the project uses `az acr build` from Taskfile.build.yml for **all 10 service images**. This command submits source to ACR's build service over the public endpoint — it will fail once public access is disabled.

## Options

1. **Self-hosted build agent inside the VNet** — Run CI builds from an AKS-hosted or VM-based agent that can reach ACR via private endpoint. Most secure, but adds infrastructure.
2. **ACR `network_rule_set` with CI runner IP** — Allowlist the GitHub Actions runner IP range (or a known egress IP) so `az acr build` still works. Partially opens the firewall but limits exposure.
3. **Toggle public access during builds** — Script `az acr update --public-network-access-enabled true` before build and disable after. Simple but creates a window of exposure.
4. **Switch to local `docker build` + `docker push`** — Build locally and push via private endpoint from a VNet-connected agent. Requires Docker daemon on the runner.

## Recommendation

Option 2 (IP allowlist) is the pragmatic first step — it keeps `az acr build` working with minimal blast radius. Long term, option 1 (self-hosted agent) is the most secure path.

## Action Required

Brian: Please decide which approach to adopt before running `terraform apply` on this change. The ACR `public_network_access_enabled = false` change is in `infra/cloud/acr.tf` with a comment noting this risk.
