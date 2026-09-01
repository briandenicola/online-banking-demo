#!/usr/bin/env bash
#
# setup-keyvault-secrets.sh — populate the Online Banking Demo Key Vault.
#
# Terraform deliberately does not manage Key Vault secrets. Writing a secret is
# a Key Vault *data-plane* call, and this deployment exposes the vault data
# plane only through a Private Endpoint. A `terraform apply` from outside the
# VNet always races the private endpoint / firewall converging and fails with:
#
#   Status=403 Code="Forbidden" InnerError={"code":"ForbiddenByConnection"}
#
# Run this script from a host with private-network line of sight to the vault —
# the jumpbox created by infra/cloud/jumpbox.tf, reached through Azure Bastion.
#
# Usage:
#   setup-keyvault-secrets.sh <app-name> [--force] [--dry-run]
#
# <app-name> is the Terraform `resource_name` (e.g. settlingfawn-14231); every
# other value is derived from it. Get it with:
#   terraform -chdir=infra/cloud output -raw resource_group_name   # <app-name>-rg
#
# Environment overrides:
#   JWT_KEY          Raw 32-char JWT signing key (base64-encoded before storing).
#                    Defaults to a freshly generated value.
#                    Use `terraform -chdir=infra/cloud output -raw jwt_key` to
#                    reuse the value Terraform holds in state.
#   AZURE_CLIENT_ID  Client ID of a user-assigned managed identity to log in as.
#                    Pre-set on the jumpbox via /etc/profile.d/banking-demo.sh.

set -euo pipefail

readonly SECRET_NAMES=(
  jwt-key
  openai-endpoint
  content-understanding-endpoint
  redis-connection-string
  appinsights-connection-string
)

FORCE=false
DRY_RUN=false
APP_NAME="${BANKING_APP_NAME:-}"

log()  { printf '\033[0;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33mWARN\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[0;31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)   FORCE=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage 0 ;;
    -*)        die "Unknown option: $1" ;;
    *)         APP_NAME="$1"; shift ;;
  esac
done

[[ -n "$APP_NAME" ]] || { warn "Missing <app-name>."; usage 1; }
command -v az >/dev/null 2>&1 || die "Azure CLI (az) is not installed."

#############################################
# Derive every resource name from the app name.
# Must stay in sync with infra/cloud/locals.tf.
#############################################
RESOURCE_GROUP="${APP_NAME}-rg"
# locals.tf: substr("${replace(resource_name, "-", "")}kv", 0, 24)
_kv="${APP_NAME//-/}kv"
KEYVAULT_NAME="${_kv:0:24}"
REDIS_NAME="${APP_NAME}-redis"
APPINSIGHTS_NAME="${APP_NAME}-ai"
FOUNDRY_NAME="${APP_NAME}-foundry"
PROJECT_NAME="${APP_NAME}-project"
CUS_NAME="${APP_NAME}-cus"

log "App name:       ${APP_NAME}"
log "Resource group: ${RESOURCE_GROUP}"
log "Key Vault:      ${KEYVAULT_NAME}"

#############################################
# Authenticate. On the jumpbox this uses the VM's user-assigned identity, which
# Terraform granted "Key Vault Secrets Officer" on the vault and "Reader" on the
# resource group.
#############################################
if ! az account show >/dev/null 2>&1; then
  if [[ -n "${AZURE_CLIENT_ID:-}" ]]; then
    log "Logging in with managed identity ${AZURE_CLIENT_ID}"
    az login --identity --client-id "${AZURE_CLIENT_ID}" --only-show-errors >/dev/null
  else
    log "Logging in with system-assigned managed identity"
    az login --identity --only-show-errors >/dev/null
  fi
fi

az group show --name "${RESOURCE_GROUP}" --only-show-errors >/dev/null \
  || die "Resource group ${RESOURCE_GROUP} not found (wrong app name or subscription?)."

#############################################
# Warn early if the vault resolves to a public address — that means this host is
# not on the private path and every secret write will 403.
#############################################
vault_host="${KEYVAULT_NAME}.vault.azure.net"
if command -v getent >/dev/null 2>&1; then
  vault_ip="$(getent hosts "${vault_host}" | awk 'NR==1{print $1}')" || true
  if [[ -n "${vault_ip:-}" ]]; then
    log "${vault_host} resolves to ${vault_ip}"
    case "${vault_ip}" in
      10.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*|192.168.*) : ;;
      *) warn "${vault_host} resolved to a public address. Run this from the in-VNet jumpbox (infra/cloud/jumpbox.tf) or writes will fail with ForbiddenByConnection." ;;
    esac
  fi
fi

#############################################
# Derive secret values from the Azure control plane.
#############################################
arm_property() {
  # arm_property <resource-type> <name> <api-version> <jmespath>
  az resource show \
    --resource-group "${RESOURCE_GROUP}" \
    --resource-type "$1" \
    --name "$2" \
    --api-version "$3" \
    --query "$4" \
    --output tsv \
    --only-show-errors 2>/dev/null || true
}

log "Deriving secret values from the Azure control plane"

redis_host="$(arm_property "Microsoft.Cache/redisEnterprise" "${REDIS_NAME}" "2024-09-01-preview" "properties.hostName")"
[[ -n "${redis_host}" ]] || die "Could not read the hostname of Redis ${REDIS_NAME}."

appinsights_conn="$(arm_property "Microsoft.Insights/components" "${APPINSIGHTS_NAME}" "2020-02-02" "properties.ConnectionString")"
[[ -n "${appinsights_conn}" ]] || die "Could not read the connection string of App Insights ${APPINSIGHTS_NAME}."

cus_endpoint="$(arm_property "Microsoft.CognitiveServices/accounts" "${CUS_NAME}" "2024-10-01" "properties.endpoint")"
[[ -n "${cus_endpoint}" ]] || die "Could not read the endpoint of Content Understanding account ${CUS_NAME}."

# Matches the value Terraform used to compute (base64 of a 32-char alphanumeric).
# `cut` rather than `head -c` on purpose: `head` closes the pipe early, which
# raises SIGPIPE in the upstream process and aborts the script under pipefail.
if [[ -n "${JWT_KEY:-}" ]]; then
  jwt_raw="${JWT_KEY}"
else
  jwt_raw="$(LC_ALL=C head -c 512 /dev/urandom | tr -dc 'A-Za-z0-9' | cut -c1-32)"
fi
[[ ${#jwt_raw} -eq 32 ]] || die "Generated JWT key is ${#jwt_raw} chars, expected 32."
jwt_value="$(printf '%s' "${jwt_raw}" | base64 | tr -d '\n')"

declare -A SECRET_VALUES=(
  [jwt-key]="${jwt_value}"
  [openai-endpoint]="https://${FOUNDRY_NAME}.services.ai.azure.com/api/projects/${PROJECT_NAME}"
  [content-understanding-endpoint]="${cus_endpoint}"
  [redis-connection-string]="${redis_host}:10000,ssl=True,abortConnect=False"
  [appinsights-connection-string]="${appinsights_conn}"
)

#############################################
# Write the secrets. Only secret *names* are printed — never values.
#############################################
created=()
skipped=()

for name in "${SECRET_NAMES[@]}"; do
  value="${SECRET_VALUES[$name]}"

  if [[ "${DRY_RUN}" == true ]]; then
    log "[dry-run] would set ${name}"
    created+=("${name}")
    continue
  fi

  if [[ "${FORCE}" != true ]] \
    && az keyvault secret show --vault-name "${KEYVAULT_NAME}" --name "${name}" \
         --only-show-errors >/dev/null 2>&1; then
    log "${name} already exists — skipping (use --force to overwrite)"
    skipped+=("${name}")
    continue
  fi

  az keyvault secret set \
    --vault-name "${KEYVAULT_NAME}" \
    --name "${name}" \
    --value "${value}" \
    --only-show-errors >/dev/null
  log "Set ${name}"
  created+=("${name}")
done

#############################################
# Summary — names only.
#############################################
echo
if [[ "${DRY_RUN}" == true ]]; then
  log "Would create/update ${#created[@]} secret(s) in ${KEYVAULT_NAME}:"
else
  log "Created/updated ${#created[@]} secret(s) in ${KEYVAULT_NAME}:"
fi
for name in "${created[@]:-}"; do
  [[ -n "${name}" ]] && printf '      %s\n' "${name}"
done

if [[ ${#skipped[@]} -gt 0 ]]; then
  log "Skipped ${#skipped[@]} existing secret(s) (use --force to overwrite):"
  for name in "${skipped[@]}"; do
    printf '      %s\n' "${name}"
  done
fi

if [[ "${DRY_RUN}" != true ]]; then
  echo
  log "Restart the workloads so the CSI driver re-reads the vault:"
  log "  kubectl rollout restart deployment -n banking-demo"
fi
