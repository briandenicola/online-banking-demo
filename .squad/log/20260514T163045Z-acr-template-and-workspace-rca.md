# Session: 2026-05-14T163045Z — ACR template fix + workspace RCA

## Summary

Basher fixed the deploy task's ACR templating. Coordinator discovered the root cause of both ImagePullBackOff + workload-identity 401: TF working tree on wrong workspace.

## Root Cause (Prominent)

### Workspace Context Bug — NOT a Code Bug

**Symptom:** ImagePullBackOff (pods unable to pull from ACR) + workload-identity 401 (AADSTS70025 on old managed identity 51592ddd).

**Root:** TF working tree was on `canadacentral` workspace (`poetic-anemone-22804`) instead of `swedencentral` (`funky-elephant-11797`).

**Impact:** Every TF output the deploy task reads (`terraform output -raw acr_name`, `terraform output json`) returned values from the OLD environment. Deploy task then:
- Templated kustomization.yaml with wrong ACR name
- Templated configmap with wrong endpoints, KV names, storage accounts
- Templated secret-provider-class with wrong tenant/client IDs

**Fix:** `terraform -chdir=./infra/cloud workspace select swedencentral` before running `task cloud:deploy`.

## Basher's Work: ACR Templating Fix

**Status:** ✅ Landed persistently

Added `_kustomization:update` task to `tasks/Taskfile.cloud.yml`:
```sh
sed -i -E "s|[a-z0-9]+acr\.azurecr\.io/|{{.ACR_NAME}}.azurecr.io/|g" \
  deploy/kustomize/base/kustomization.yaml
```

Wired into deploy flow: `_images:update` → `_kustomization:update` → `kubectl apply -k` → restore files.

Also added missing `account-opening-service` line to `_images:update`.

## Decision Artifacts

- `basher-kustomize-acr-template.md` — Decision w/ consequences and fragility analysis
- `deploy-task-acr-templating/SKILL.md` — Reusable pattern for env-specific manifest templating

## New User Directive

Captured in `copilot-directive-20260514T1627Z.md`:

**Agents must NEVER run `task cloud:deploy` themselves.** Brian manages all deploys. Agents may edit deploy task/manifest files and propose redeploys, but the actual invocation is Brian's responsibility.

## Side Work (Wasted)

Basher hardcoded 11 `newName:` entries to `poeticanemone22804acr` (wrong ACR, wrong workspace). Manually created AcrPull assignment in old env. Flagged as "TF drift" but was just noise from the wrong workspace context. Harmless now because sed templating will rewrite on next deploy.

## Lessons

1. **Always check `terraform workspace show`** before running deploy tasks.
2. **Workspace context bugs are invisible** — no error message, just wrong values.
3. **Sed templating pattern works well** for env-specific manifests. Can be generalized.
4. **User directive enforcement** — Some operations (like cloud deploy) must be user-driven, not agent-driven, to maintain oversight and control.
