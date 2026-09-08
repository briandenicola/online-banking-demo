#!/usr/bin/env bash
# demo-lib.sh — shared helpers for the demo dataset tooling (issue #356).
#
# Sourced by scripts/demo/demo.sh. Contains no dataset knowledge: no identity, no amount, no
# endpoint host. Those live in config/demo-dataset.json or in the environment.
#
# Design note — FAIL LOUDLY. Every request goes through http(), which separates the body from
# the status code and returns the code to the caller. There is no path in here that swallows a
# non-2xx and carries on: a caller must either state which codes it tolerates (idempotence) or
# the run stops. A seeder that half-succeeds silently is worse than one that stops.

set -euo pipefail

# --- Colour helpers (disabled when not a TTY, so logs stay greppable) ---------------------
if [[ -t 1 ]]; then
  C_GREEN=$'\033[0;32m'; C_BLUE=$'\033[0;34m'; C_YELLOW=$'\033[1;33m'
  C_RED=$'\033[0;31m';   C_DIM=$'\033[2m';     C_OFF=$'\033[0m'
else
  C_GREEN=''; C_BLUE=''; C_YELLOW=''; C_RED=''; C_DIM=''; C_OFF=''
fi

info()    { echo "${C_BLUE}·${C_OFF} $*"; }
success() { echo "${C_GREEN}✔${C_OFF} $*"; }
warn()    { echo "${C_YELLOW}⚠${C_OFF} $*" >&2; }
detail()  { echo "${C_DIM}  $*${C_OFF}"; }
header()  { echo; echo "${C_BLUE}━━━ $* ━━━${C_OFF}"; }

die() {
  echo "${C_RED}✖ $*${C_OFF}" >&2
  exit 1
}

require_tools() {
  local missing=()
  local tool
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  [[ ${#missing[@]} -eq 0 ]] || die "Missing required tool(s): ${missing[*]}"
}

# --- HTTP --------------------------------------------------------------------------------
# http <METHOD> <PATH> [BODY_JSON] [BEARER_TOKEN]
#
# Sets HTTP_STATUS and HTTP_BODY. Never exits on a non-2xx — the caller decides. Uses a
# body/status separator that cannot appear in JSON so the split is unambiguous (the previous
# script split on the last line, which corrupts any body whose final line is not the status).
HTTP_STATUS=""
HTTP_BODY=""
http() {
  local method="$1" path="$2" body="${3:-}" token="${4:-}"
  local url="${DEMO_BASE_URL}${path}"
  local sep=$'\x1e'
  local args=(-sS -m "${DEMO_HTTP_TIMEOUT}" -X "$method" -H 'Accept: application/json'
              -w "${sep}%{http_code}" -o - "$url")

  [[ -n "$token" ]] && args+=(-H "Authorization: Bearer ${token}")
  if [[ -n "$body" ]]; then
    args+=(-H 'Content-Type: application/json' --data-binary "$body")
  fi

  local raw
  if ! raw=$(curl "${args[@]}" 2>&1); then
    HTTP_STATUS="000"
    HTTP_BODY="$raw"
    return 0
  fi

  HTTP_STATUS="${raw##*"${sep}"}"
  HTTP_BODY="${raw%"${sep}"*}"
  return 0
}

# status_in <status> <acceptable...> — true when the status matches one of the listed codes.
status_in() {
  local status="$1"; shift
  local candidate
  for candidate in "$@"; do
    [[ "$status" == "$candidate" ]] && return 0
  done
  return 1
}

# http_or_die <METHOD> <PATH> <BODY> <TOKEN> <CONTEXT> <acceptable-status...>
http_or_die() {
  local method="$1" path="$2" body="$3" token="$4" context="$5"; shift 5
  http "$method" "$path" "$body" "$token"
  if ! status_in "$HTTP_STATUS" "$@"; then
    echo "${C_RED}✖ ${context}${C_OFF}" >&2
    echo "${C_RED}  ${method} ${path} -> HTTP ${HTTP_STATUS}${C_OFF}" >&2
    echo "${C_RED}  ${HTTP_BODY}${C_OFF}" >&2
    exit 1
  fi
}

# --- JSON --------------------------------------------------------------------------------
# jget <jq-filter> — read HTTP_BODY. Empty string when absent, never the literal "null".
jget() {
  local value
  value=$(printf '%s' "$HTTP_BODY" | jq -r "$1 // empty" 2>/dev/null) || value=""
  printf '%s' "$value"
}

# jget_from <json> <jq-filter>
jget_from() {
  local value
  value=$(printf '%s' "$1" | jq -r "$2 // empty" 2>/dev/null) || value=""
  printf '%s' "$value"
}

# --- Target resolution -------------------------------------------------------------------
# Endpoints come from configuration or the environment. Nothing is baked into this file.
resolve_base_url() {
  local target="$1" dataset="$2"

  local env_name
  env_name=$(jget_from "$dataset" ".targets[\"${target}\"].baseUrlEnv")
  [[ -n "$env_name" ]] || die "config/demo-dataset.json declares no baseUrlEnv for target '${target}'"

  # 1. Explicit override always wins.
  local override="${!env_name:-}"
  if [[ -n "$override" ]]; then
    printf '%s' "${override%/}"
    return 0
  fi

  # 2. Static default, when the target declares one (local compose gateway).
  local fallback
  fallback=$(jget_from "$dataset" ".targets[\"${target}\"].baseUrlDefault")
  if [[ -n "$fallback" ]]; then
    printf '%s' "${fallback%/}"
    return 0
  fi

  # 3. A host supplied by the environment (CUSTOM_DOMAIN, as the tls tasks already use).
  local scheme host_env host=""
  scheme=$(jget_from "$dataset" ".targets[\"${target}\"].scheme")
  host_env=$(jget_from "$dataset" ".targets[\"${target}\"].hostFromEnv")
  [[ -n "$host_env" ]] && host="${!host_env:-}"

  # 4. Otherwise READ it from the cluster. A read, not a write.
  local name=""
  if [[ -z "$host" ]]; then
    local resource namespace jsonpath
    resource=$(jget_from  "$dataset" ".targets[\"${target}\"].hostFromKubectl.resource")
    name=$(jget_from      "$dataset" ".targets[\"${target}\"].hostFromKubectl.name")
    namespace=$(jget_from "$dataset" ".targets[\"${target}\"].hostFromKubectl.namespace")
    jsonpath=$(jget_from  "$dataset" ".targets[\"${target}\"].hostFromKubectl.jsonpath")

    if [[ -n "$resource" ]] && command -v kubectl >/dev/null 2>&1; then
      host=$(kubectl get "$resource" "$name" -n "$namespace" -o jsonpath="$jsonpath" 2>/dev/null \
             | tr ' ' '\n' | grep -v '^\*\?$' | head -1) || host=""
    fi
  fi

  [[ -n "$host" ]] || die \
    "Could not determine the ${target} base URL. Set ${env_name}, or set ${host_env}, or make the ${name} gateway readable with kubectl."

  printf '%s' "${scheme}://${host}"
}

# --- Placeholder resolution ---------------------------------------------------------------
# Replaces {"@threshold": name, "@delta": n} with the LIVE policy value + n, and {"@ref": key}
# with a value discovered during seeding. An unresolved placeholder is a hard error — a silently
# dropped account id produces an approval whose evidence points at nothing.
#
# resolve_placeholders <json> <thresholds-json> <refs-json>
resolve_placeholders() {
  printf '%s' "$1" | jq \
    --argjson thresholds "$2" \
    --argjson refs "$3" '
    def resolve:
      if type == "object" then
        if has("@threshold") then
          ($thresholds[.["@threshold"]] // error("unknown policy threshold: " + .["@threshold"]))
          + (.["@delta"] // 0)
        elif has("@ref") then
          ($refs[.["@ref"]] // error("unresolved reference: " + .["@ref"]))
        else
          with_entries(select(.key | startswith("$comment") | not) | .value |= resolve)
        end
      elif type == "array" then map(resolve)
      else . end;
    resolve'
}
