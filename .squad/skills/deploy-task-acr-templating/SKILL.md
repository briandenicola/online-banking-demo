# Skill: Deploy-task ACR / env-value templating via sed-sub

## Rule

**Always source environment-specific values from `terraform output` via sed-sub
at deploy time. Never commit them into kubernetes manifests.**

This applies to any value that changes per Azure environment:
- ACR hostname (`<acr>.azurecr.io`)
- Cosmos endpoint, Storage account, Key Vault name
- Tenant ID, Workload Identity client ID
- Application Insights connection string
- Any other TF-derived resource name or endpoint

## Pattern

In `tasks/Taskfile.cloud.yml`:

1. Source value from TF output as a task var:
   ```yaml
   vars:
     ACR_NAME:
       sh: terraform -chdir=./{{.INFRA_DIR}} output -raw acr_name
   ```

2. Add an internal `_<thing>:update` task that:
   - Sed-substitutes a placeholder (`REPLACE_WITH_FOO`) OR a regex of prior
     values in the manifest
   - `kubectl apply -f` the substituted file (if applied directly)
   - **Restores the manifest with `git checkout <file>`** so the working tree
     stays clean

3. Wire the task into `deploy` BEFORE the relevant `kubectl apply -k` (for
   manifests included via kustomize) or use the apply-then-restore inline
   pattern for files applied directly.

4. For kustomize-managed image refs, use a regex that matches any prior
   environment's ACR hostname:
   ```sh
   sed -i -E "s|[a-z0-9]+acr\.azurecr\.io/|{{.ACR_NAME}}.azurecr.io/|g" \
     deploy/kustomize/base/kustomization.yaml
   ```
   The regex relies on Azure's `[a-z0-9]` ACR naming constraint.

## Anti-patterns (don't do these)

- ❌ Hard-code ACR hostnames in `kustomization.yaml` `newName:` fields
- ❌ Hard-code Cosmos endpoints, KV names, tenant IDs in configmaps
- ❌ Forget to restore manifests after sed-sub (causes accumulating drift in git)
- ❌ Use placeholder substitution without a corresponding `git checkout` cleanup

## Existing examples in this repo

- `tasks/Taskfile.cloud.yml`:
  - `_configmap:update` — placeholder-based sub, applies, restores
  - `_secretproviderclass:update` — placeholder-based sub, applies, restores
  - `_kustomization:update` — regex-based sub on `newName:` lines, restored
    by the parent `deploy` task after `kubectl apply -k`
  - `_images:update` — `kustomize edit set image` for tag/hostname (alternative
    to sed; works if every service has a `kustomize edit` line)

## Sister concern: TF state must contain the role assignments referenced by
the deploy

Sed-sub gets the manifest right, but pods still fail to pull if AKS lacks
`AcrPull` on the registry. Whenever investigating `ImagePullBackOff`, ALSO
check:

```sh
KUBELET_OID=$(az aks show -n <aks> -g <rg> --query identityProfile.kubeletidentity.objectId -o tsv)
az role assignment list --assignee "$KUBELET_OID" --scope "$(az acr show -n <acr> --query id -o tsv)"
```

If empty, check `terraform state list | grep aks_acr_pull` — TF drift can
silently leave the role assignment uncreated.
