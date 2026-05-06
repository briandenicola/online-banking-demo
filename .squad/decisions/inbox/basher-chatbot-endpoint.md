# Decision: Fix chatbot endpoint URL hostname mismatch

**Author:** Basher (Backend Dev)
**Date:** 2025-07-18
**Status:** Proposed
**Scope:** infra/cloud/outputs.tf

## Problem

The chatbot service fails at startup with a DNS resolution error:

```
Failed to resolve 'witty-bluejay-46780-project.services.ai.azure.com'
```

WorkloadIdentity auth succeeds (token acquired), but the endpoint hostname can't be resolved.

## Root Cause

In `infra/cloud/outputs.tf`, the `openai_endpoint` output constructed the URL using `local.project_name` for **both** the hostname and the path:

```hcl
# BEFORE (broken)
"https://${local.project_name}.services.ai.azure.com/api/projects/${local.project_name}"
```

Azure registers the DNS hostname based on the **parent AI Services account's** `customSubDomainName` property (`local.openai_name`, suffix `-foundry`), NOT the child project name (`local.project_name`, suffix `-project`).

So the hostname `*-project.services.ai.azure.com` never existed in DNS. The correct hostname is `*-foundry.services.ai.azure.com`.

## Fix

Changed the hostname portion to use `local.openai_name` while keeping `local.project_name` in the path:

```hcl
# AFTER (fixed)
"https://${local.openai_name}.services.ai.azure.com/api/projects/${local.project_name}"
```

This produces:
- **Hostname:** `{resource_name}-foundry.services.ai.azure.com` ✅ (matches `customSubDomainName`)
- **Path:** `/api/projects/{resource_name}-project` ✅ (matches project resource name)

## Files Changed

- `infra/cloud/outputs.tf` — line 42: hostname changed from `local.project_name` to `local.openai_name`

## Impact

- Chatbot service will resolve the AI Foundry endpoint correctly
- Requires Terraform apply to update the output, then the `banking-secrets` Kubernetes secret must be refreshed with the corrected endpoint value
- No code changes needed in the chatbot service itself; the Python code correctly uses whatever endpoint URL is provided

## Deployment Steps

1. `terraform apply` to regenerate the corrected `openai_endpoint` output
2. Update the `banking-secrets` Kubernetes secret with the new endpoint value
3. Restart the chatbot-service pods to pick up the new secret
