#!/usr/bin/env bash
# demo.sh — demo dataset lifecycle for the Banker Copilot (issue #356).
#
#   demo.sh seed  --target local|cloud     create the dataset (idempotent)
#   demo.sh show  --target local|cloud     print what exists
#   demo.sh reset --target local|cloud     return the environment to a clean state
#
# Normally invoked as `task local:demo:seed` / `task cloud:demo:seed`.
#
# ── Why the ordering in seed() is not negotiable ────────────────────────────────────────────
# user-service has three identity-seeding behaviours that quietly produce a broken environment:
#
#   1. The FIRST account registered into an empty environment is silently promoted to admin,
#      whatever role was intended. So this script registers the admin identity first and lets
#      that rule land where it is harmless, instead of discovering later that `banker` is an
#      admin and therefore barred from the harness it exists to demo.
#   2. Bootstrap role seeding runs at STARTUP only, so it never sees an account created
#      afterwards. This script therefore never relies on it: every role is granted explicitly
#      through POST /api/admin/promote with an admin token.
#   3. The bootstrap's idempotence check is role-wide, not user-wide ("someone already holds
#      banker, skip"), so a half-seeded environment stays half-seeded across restarts. Every
#      check here is per-user, and each grant is VERIFIED by logging in and reading the role
#      back off the issued token — a promote that silently did nothing fails the run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=scripts/demo/demo-lib.sh
source "${SCRIPT_DIR}/demo-lib.sh"

DATASET_FILE="${DEMO_DATASET_FILE:-${REPO_ROOT}/config/demo-dataset.json}"
DEMO_HTTP_TIMEOUT="${DEMO_HTTP_TIMEOUT:-30}"

VERB=""
TARGET="${DEMO_TARGET:-local}"
DO_RESEED="false"
INCLUDE_ADMIN="false"
ALLOW_UNSCORED="false"

DATASET=""
# NOT initialised to "" — DEMO_BASE_URL is one of the documented environment overrides, and
# clearing it here would silently discard the caller's choice of target.
DEMO_BASE_URL="${DEMO_BASE_URL:-}"
PASSWORD=""
EMAIL_DOMAIN=""

declare -A TOKENS=()      # username -> bearer token
declare -A ACCOUNT_IDS=() # "<owner>:<datasetIndex>" -> real account id, claimed or created
EVIDENCE_ACCOUNT=""       # the banker-owned account the propose-path probe reads
EVIDENCE_ACCOUNT_ALT=""   # a second banker-owned account, for approvals that need a distinct one
declare -A LOCKED_NOW=()  # username -> set when the admin list reports the account locked
declare -A USER_IDS=()    # username -> user id
declare -A ROLES=()       # username -> role as the issued token reports it
REFS='{}'                 # runtime-discovered values for {"@ref": ...}
THRESHOLDS='{}'           # live policy thresholds for {"@threshold": ...}

# =============================================================================================
# Arguments
# =============================================================================================
usage() {
  cat <<'EOF'
Usage: demo.sh <seed|show|reset> [options]

  --target local|cloud   Which environment to act on (default: local, or $DEMO_TARGET)
  --reseed               reset only: seed again immediately afterwards
  --include-admin        reset only: also delete the admin identity
                         (a cold re-seed then relies on the first-user-becomes-admin rule)
  --allow-unscored       seed only: continue when ai-service produced no scored transactions,
                         using real transaction ids and a declared placeholder score
  -h, --help             This message

Environment:
  DEMO_BASE_URL          Overrides the target's base URL entirely
  CUSTOM_DOMAIN          Cloud host, when kubectl is not available
  DEMO_SEED_PASSWORD     Seed password (throwaway default in config/demo-dataset.json)
  DEMO_DATASET_FILE      Alternate dataset file
EOF
}

parse_args() {
  [[ $# -gt 0 ]] || { usage; exit 2; }
  VERB="$1"; shift

  case "$VERB" in
    seed|show|reset) ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown command '${VERB}'. Expected seed, show or reset." ;;
  esac

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target) TARGET="${2:-}"; shift 2 ;;
      --target=*) TARGET="${1#*=}"; shift ;;
      --reseed) DO_RESEED="true"; shift ;;
      --include-admin) INCLUDE_ADMIN="true"; shift ;;
      --allow-unscored) ALLOW_UNSCORED="true"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown option '$1'." ;;
    esac
  done

  [[ "$TARGET" == "local" || "$TARGET" == "cloud" ]] \
    || die "--target must be 'local' or 'cloud', got '${TARGET}'."
}

# =============================================================================================
# Bootstrap
# =============================================================================================
load_dataset() {
  require_tools curl jq
  [[ -f "$DATASET_FILE" ]] || die "Dataset not found: ${DATASET_FILE}"
  DATASET=$(cat "$DATASET_FILE")
  jq -e . >/dev/null 2>&1 <<<"$DATASET" || die "Dataset is not valid JSON: ${DATASET_FILE}"

  local pw_env pw_default
  pw_env=$(jget_from "$DATASET" '.credentials.passwordEnv')
  pw_default=$(jget_from "$DATASET" '.credentials.passwordDefault')
  PASSWORD="${!pw_env:-$pw_default}"
  [[ -n "$PASSWORD" ]] || die "No seed password: set ${pw_env}."

  EMAIL_DOMAIN=$(jget_from "$DATASET" '.emailDomain')
  DEMO_BASE_URL=$(resolve_base_url "$TARGET" "$DATASET")
}

email_for() { printf '%s@%s' "$1" "$EMAIL_DOMAIN"; }

identity_field() { jget_from "$DATASET" ".identities[] | select(.username == \"$1\") | .$2"; }

identity_usernames() {
  jq -r '.identities | sort_by(if .registerFirst then 0 else 1 end) | .[].username' <<<"$DATASET"
}

retail_usernames() {
  jq -r '.identities[] | select(.retail == true) | .username' <<<"$DATASET"
}

# Every identity the dataset gives an account to, in declaration order. Derived from the accounts
# list rather than from a role flag, so moving an account to a different owner needs no code
# change — which matters, because get_account is ownership-scoped and the evidence-bearing
# accounts have to belong to the acting banker.
account_owners() {
  jq -r '.accounts[].owner' <<<"$DATASET" | awk '!seen[$0]++'
}

preflight() {
  info "Target        ${TARGET}"
  info "Base URL      ${DEMO_BASE_URL}"
  info "Dataset       ${DATASET_FILE#"$REPO_ROOT"/}"

  http GET /health
  if ! status_in "$HTTP_STATUS" 200 204; then
    # /health is a convenience, not a contract. Try a route that definitely exists instead,
    # so a missing health aggregate does not masquerade as an unreachable environment.
    http GET /api/authority/policy
    status_in "$HTTP_STATUS" 200 401 403 \
      || die "Cannot reach ${DEMO_BASE_URL} (HTTP ${HTTP_STATUS}). Is the environment up?"
  fi
  success "Environment reachable"
}

# =============================================================================================
# Identity
# =============================================================================================
login() {
  local username="$1"
  local body
  body=$(jq -n --arg u "$username" --arg p "$PASSWORD" '{username: $u, password: $p}')

  http_or_die POST /api/auth/login "$body" "" \
    "Login failed for '${username}'. If this environment predates the demo dataset the password may differ — set DEMO_SEED_PASSWORD." \
    200

  local token role uid
  token=$(jget '.token // .Token')
  role=$(jget '.role // .Role')
  uid=$(jget '.userId // .UserId')

  [[ -n "$token" ]] || die "Login for '${username}' returned no token: ${HTTP_BODY}"

  TOKENS["$username"]="$token"
  ROLES["$username"]="$role"
  USER_IDS["$username"]="$uid"
}

register_identity() {
  local username="$1"
  local body
  body=$(jq -n \
    --arg u "$username" \
    --arg e "$(email_for "$username")" \
    --arg p "$PASSWORD" \
    --arg f "$(identity_field "$username" firstName)" \
    --arg l "$(identity_field "$username" lastName)" \
    '{username: $u, email: $e, password: $p, firstName: $f, lastName: $l}')

  http POST /api/auth/register "$body"

  case "$HTTP_STATUS" in
    200|201)
      success "Registered ${username}" ;;
    409)
      # A conflict on register means the username or email is taken, which for this seeder is
      # exactly the re-run case. Do not depend on the wording of the message — that is a string
      # the service is free to change, and matching on it would turn a re-seed into a failure.
      detail "${username} already exists" ;;
    400)
      if grep -qi 'already\|exists\|taken\|duplicate' <<<"$HTTP_BODY"; then
        detail "${username} already exists"
      else
        die "Registration of '${username}' was rejected (HTTP 400): ${HTTP_BODY}
    The payload shape this seeder sends may not match what user-service expects."
      fi ;;
    *)
      die "Registration of '${username}' failed (HTTP ${HTTP_STATUS}): ${HTTP_BODY}" ;;
  esac
}

seed_identities() {
  header "Identities"

  local admin_user
  admin_user=$(jq -r '.identities[] | select(.registerFirst == true) | .username' <<<"$DATASET")
  [[ -n "$admin_user" ]] || die "No identity in the dataset is marked registerFirst."

  # Trap 1 — the first registration into an empty environment becomes admin regardless of the
  # role asked for. Spend that rule on the identity that wants it.
  register_identity "$admin_user"

  local username
  while read -r username; do
    [[ "$username" == "$admin_user" ]] && continue
    register_identity "$username"
  done < <(identity_usernames)

  login "$admin_user"
  local admin_token="${TOKENS[$admin_user]}"

  if [[ "${ROLES[$admin_user]}" != "admin" ]]; then
    die "'${admin_user}' holds role '${ROLES[$admin_user]}', not admin. Nothing else can be
    granted without an admin token. Either this environment already had users before seeding
    (so the first-user rule landed elsewhere), or the account was demoted. Promote it by hand,
    or run 'demo.sh reset --include-admin' against a disposable environment first."
  fi
  success "Admin token acquired (${admin_user})"

  # A previous run deliberately locks one identity so that user.unlock has a real subject. That
  # identity cannot log in, and role verification below depends on logging in — so unlock first
  # and let lock_target_user re-lock at the proper stage. Without this a re-seed dies on step 2.
  unlock_seeded_identities "$admin_token"

  # Trap 2/3 — grant every role explicitly and per user. Never rely on startup bootstrap, and
  # never accept a role-wide "already held" as evidence that THIS user holds it.
  header "Role grants"
  while read -r username; do
    local want
    want=$(identity_field "$username" role)
    [[ -n "$want" ]] || die "Identity '${username}' declares no role."

    if [[ "$username" == "$admin_user" ]]; then
      detail "${username} -> ${want} (first-user rule)"
    else
      local body
      body=$(jq -n --arg e "$(email_for "$username")" --arg r "$want" '{email: $e, role: $r}')
      http_or_die POST /api/admin/promote "$body" "$admin_token" \
        "Could not grant role '${want}' to '${username}'." 200 409
      if [[ "$HTTP_STATUS" == "409" ]]; then
        detail "${username} already holds ${want}"
      else
        success "${username} -> ${want}"
      fi
    fi

    # The grant is not believed until a freshly issued token says so. This is the guard against
    # trap 3: a skipped promote and a successful promote are otherwise indistinguishable.
    login "$username"
    [[ "${ROLES[$username]}" == "$want" ]] || die \
      "Role grant for '${username}' did not take: the issued token reports role '${ROLES[$username]}', expected '${want}'."
  done < <(identity_usernames)

  success "All roles verified from freshly issued tokens"
}

# =============================================================================================
# Accounts and transactions
# =============================================================================================
seed_accounts() {
  header "Accounts"

  local owner
  while read -r owner; do
    local token="${TOKENS[$owner]}"

    http_or_die GET /api/accounts "" "$token" "Could not list accounts for '${owner}'." 200
    local existing="$HTTP_BODY"

    # The environment may already hold accounts this seeder did not create — hand-made ones from
    # a verification pass, for instance. account-service offers no label or name to key on, so
    # each desired account CLAIMS the first still-unclaimed existing account of the same type,
    # and only creates one when nothing is left to claim. The claim map is what the transaction
    # stage indexes by, so it can never drift from server ordering.
    local claimed="[]"
    local want_total n
    want_total=$(jq --arg o "$owner" '[.accounts[] | select(.owner == $o)] | length' <<<"$DATASET")

    for ((n = 0; n < want_total; n++)); do
      local spec acct_type label pick account_id
      spec=$(jq --arg o "$owner" --argjson i "$n" '[.accounts[] | select(.owner == $o)][$i]' <<<"$DATASET")
      acct_type=$(jget_from "$spec" '.accountType')
      label=$(jget_from "$spec" '.label')

      pick=$(jq -r --arg t "$acct_type" --argjson c "$claimed" \
        'to_entries
         | map(select((.value.accountType // .value.AccountType) == $t))
         | map(select(.key as $k | ($c | index($k)) | not))
         | .[0].key // empty' <<<"$existing")

      if [[ -n "$pick" ]]; then
        claimed=$(jq --argjson k "$pick" '. + [$k]' <<<"$claimed")
        account_id=$(jq -r --argjson k "$pick" '.[$k] | (.id // .Id)' <<<"$existing")
        detail "${owner}: ${acct_type} already present — reusing ${account_id} (${label})"
      else
        local body
        body=$(jq -c '{accountType: .accountType, initialBalance: .initialBalance, currency: .currency}' <<<"$spec")
        http_or_die POST /api/accounts "$body" "$token" \
          "Could not create a ${acct_type} account for '${owner}'." 200 201
        account_id=$(jget '.id // .Id')

        http_or_die GET /api/accounts "" "$token" "Could not re-list accounts for '${owner}'." 200
        existing="$HTTP_BODY"
        if [[ -z "$account_id" ]]; then
          account_id=$(jq -r --arg t "$acct_type" --argjson c "$claimed" \
            'to_entries | map(select((.value.accountType // .value.AccountType) == $t))
             | map(select(.key as $k | ($c | index($k)) | not)) | .[0].value | (.id // .Id) // empty' <<<"$existing")
        fi
        [[ -n "$account_id" ]] || die "Created a ${acct_type} account for '${owner}' but could not read its id back."
        pick=$(jq -r --arg a "$account_id" 'to_entries | map(select((.value.id // .value.Id) == $a)) | .[0].key // empty' <<<"$existing")
        [[ -n "$pick" ]] && claimed=$(jq --argjson k "$pick" '. + [$k]' <<<"$claimed")
        success "${owner}: created ${acct_type} (${label})"
      fi

      ACCOUNT_IDS["${owner}:${n}"]="$account_id"
      [[ "$(jget_from "$spec" '.evidenceSubject')" == "true" ]] && EVIDENCE_ACCOUNT="$account_id"
      [[ "$(jget_from "$spec" '.evidenceSubjectAlt')" == "true" ]] && EVIDENCE_ACCOUNT_ALT="$account_id"
      true
    done
  done < <(account_owners)

  [[ -n "$EVIDENCE_ACCOUNT" ]] || warn "No account is marked evidenceSubject; the propose-path probe has nothing to read."
}

# get_account is ownership-scoped, so every account an approval cites as evidence must belong to
# the acting banker. These references are what the approval payloads resolve against.
resolve_evidence_refs() {
  [[ -n "$EVIDENCE_ACCOUNT" ]] && resolve_account_refs "$EVIDENCE_ACCOUNT" evidence
  [[ -n "$EVIDENCE_ACCOUNT_ALT" ]] && resolve_account_refs "$EVIDENCE_ACCOUNT_ALT" evidenceAlt
  return 0
}

# count_records <json> — transaction-service returns a bare array today. If the evidence-contract
# fix wraps it in an object, count what is inside rather than the wrapper's own keys.
count_records() {
  jq 'if type == "array" then length else (.count // (.items | length) // 0) end' <<<"$1"
}

# account_ids_for <owner> — newline-separated account ids, in server order.
account_ids_for() {
  local owner="$1"
  http_or_die GET /api/accounts "" "${TOKENS[$owner]}" "Could not list accounts for '${owner}'." 200
  jq -r '.[] | (.id // .Id)' <<<"$HTTP_BODY"
}

seed_transactions() {
  header "Transactions"

  local owner
  while read -r owner; do
    local token="${TOKENS[$owner]}"

    local count idx
    count=$(jq --arg o "$owner" '[.transactions[] | select(.owner == $o)] | length' <<<"$DATASET")
    for ((idx = 0; idx < count; idx++)); do
      local spec account_index account_id description
      spec=$(jq --arg o "$owner" --argjson i "$idx" '[.transactions[] | select(.owner == $o)][$i]' <<<"$DATASET")
      account_index=$(jget_from "$spec" '.accountIndex')
      description=$(jget_from "$spec" '.description')
      account_id="${ACCOUNT_IDS[${owner}:${account_index}]:-${ACCOUNT_IDS[${owner}:0]:-}}"
      [[ -n "$account_id" ]] || die "'${owner}' has no account at index ${account_index}; cannot post '${description}'."

      http_or_die GET "/api/transactions/account/${account_id}" "" "$token" \
        "Could not list transactions for account ${account_id}." 200
      if jq -e --arg d "$description" '(if type == "array" then . else (.items // []) end)
          | any(.[]; (.description // .Description) == $d)' >/dev/null <<<"$HTTP_BODY"; then
        detail "${owner}: '${description}' already posted"
        continue
      fi

      local body
      body=$(jq -c --arg a "$account_id" \
        '{accountId: $a, amount: .amount, type: .type, description: .description,
          currency: "USD", category: .category}' <<<"$spec")
      http_or_die POST /api/transactions "$body" "$token" \
        "Could not post transaction '${description}' for '${owner}'." 200 201
      success "${owner}: ${description}"
    done
  done < <(account_owners)
}

# Clears any lock this seeder previously applied, so that a re-seed can still log in as the
# affected identity to verify its role. lock_target_user re-applies the lock afterwards.
unlock_seeded_identities() {
  local admin_token="$1" target uid locked
  target=$(jq -r '.identities[] | select(.locked == true) | .username' <<<"$DATASET")
  [[ -n "$target" ]] || return 0

  http GET /api/admin/users "" "$admin_token"
  [[ "$HTTP_STATUS" == "200" ]] || return 0

  uid=$(jq -r --arg u "$target" '.[] | select((.username // .Username) == $u) | (.id // .Id)' <<<"$HTTP_BODY" | head -1)
  locked=$(jq -r --arg u "$target" \
    '.[] | select((.username // .Username) == $u) | ((.isLocked // .IsLocked) | tostring)' <<<"$HTTP_BODY" | head -1)
  [[ -n "$uid" && "$locked" == "true" ]] || return 0

  http_or_die PUT "/api/admin/users/${uid}/unlock" "" "$admin_token" \
    "Could not clear the previous run's lock on '${target}'." 200 204
  detail "${target} temporarily unlocked so its role can be verified"
}

lock_target_user() {
  header "Lock a customer (subject for user.unlock)"

  local target
  target=$(jq -r '.identities[] | select(.locked == true) | .username' <<<"$DATASET")
  [[ -n "$target" ]] || { warn "No identity is marked locked; user.unlock will have no real subject."; return; }

  local admin_user admin_token uid
  admin_user=$(jq -r '.identities[] | select(.registerFirst == true) | .username' <<<"$DATASET")
  admin_token="${TOKENS[$admin_user]}"

  http_or_die GET /api/admin/users "" "$admin_token" "Could not list users." 200
  uid=$(jq -r --arg u "$target" '.[] | select((.username // .Username) == $u) | (.id // .Id)' <<<"$HTTP_BODY" | head -1)
  [[ -n "$uid" ]] || die "Locked-target identity '${target}' was not found in /api/admin/users."

  local already
  already=$(jq -r --arg u "$target" \
    '.[] | select((.username // .Username) == $u) | ((.isLocked // .IsLocked) | tostring)' <<<"$HTTP_BODY" | head -1)

  if [[ "$already" == "true" ]]; then
    detail "${target} is already locked"
  else
    http_or_die PUT "/api/admin/users/${uid}/lock" "" "$admin_token" \
      "Could not lock '${target}'." 200 204
    success "${target} locked — user.unlock now has a real subject"
  fi

  REFS=$(jq --arg k lockedUserId --arg v "$uid" '.[$k] = $v' <<<"$REFS")

  http GET "/api/admin/login-audits?limit=100" "" "$admin_token"
  local audits=0
  if [[ "$HTTP_STATUS" == "200" ]]; then
    audits=$(jq --arg u "$uid" '[.[] | select((.userId // .UserId) == $u)] | length' <<<"$HTTP_BODY" 2>/dev/null || echo 0)
  fi
  REFS=$(jq --arg k lockedUserLoginAuditCount --argjson v "${audits:-0}" '.[$k] = $v' <<<"$REFS")
}

# =============================================================================================
# AI scoring — real subjects for transaction.score.override and transaction.flag.review
# =============================================================================================
collect_ai_subjects() {
  header "AI-scored subjects"

  local admin_user admin_token
  admin_user=$(jq -r '.identities[] | select(.registerFirst == true) | .username' <<<"$DATASET")
  admin_token="${TOKENS[$admin_user]}"

  local wait_total interval min_required
  wait_total=$(jget_from "$DATASET" '.scoring.pollSeconds')
  interval=$(jget_from "$DATASET" '.scoring.pollIntervalSeconds')
  min_required=$(jget_from "$DATASET" '.scoring.minScoredRequired')

  local waited=0 scored='[]' flagged='[]'
  while (( waited <= wait_total )); do
    http GET /api/admin/transactions "" "$admin_token"
    if [[ "$HTTP_STATUS" == "200" ]]; then
      scored=$(jq 'if type == "array" then . else [] end' <<<"$HTTP_BODY")
    elif [[ "$HTTP_STATUS" == "403" ]]; then
      die "The admin token was refused by ai-service (403). Scored transactions cannot be read."
    fi

    http GET /api/admin/flagged-transactions "" "$admin_token"
    [[ "$HTTP_STATUS" == "200" ]] && flagged=$(jq 'if type == "array" then . else [] end' <<<"$HTTP_BODY")

    if [[ "$(jq 'length' <<<"$scored")" -ge "$min_required" ]]; then
      break
    fi
    detail "waiting for ai-service to score the anomalous transactions (${waited}s/${wait_total}s)"
    sleep "$interval"
    waited=$((waited + interval))
  done

  local n_scored n_flagged
  n_scored=$(jq 'length' <<<"$scored")
  n_flagged=$(jq 'length' <<<"$flagged")
  info "ai-service reports ${n_scored} scored, ${n_flagged} flagged"

  if [[ "$n_scored" -lt "$min_required" ]]; then
    if [[ "$ALLOW_UNSCORED" != "true" ]]; then
      die "ai-service produced no scored transactions within ${wait_total}s.
    The subjects for transaction.score.override and transaction.flag.review would be invented,
    and the Copilot's read tools would 404 on them during the demo.
    Check the ai-service stream consumer and its Foundry connectivity, then re-run.
    To continue anyway with real transaction ids and a placeholder score: --allow-unscored"
    fi
    warn "Continuing without AI scores (--allow-unscored). The score-override subject will be a"
    warn "real transaction id with a PLACEHOLDER risk score; get_scored_transaction will 404."
    build_unscored_fallback_refs
    return
  fi

  # Scored and flagged records outlive the identities that produced them: reset can delete a
  # user but nothing deletes their accounts, transactions or Redis-held scores. So discard any
  # subject whose account no longer belongs to a customer this run seeded, or the demo would be
  # built on a record whose evidence tools cannot be satisfied.
  local owned
  owned=$(seeded_account_ids)

  # Highest risk first — that is what a banker would be looking at.
  local pool flagged_pool
  pool=$(jq --argjson owned "$owned" \
    '[.[] | select(.accountId as $a | $owned | index($a))] | sort_by(-(.riskScore // 0))' <<<"$scored")
  flagged_pool=$(jq --argjson owned "$owned" \
    '[.[] | select(.accountId as $a | $owned | index($a))] | sort_by(-(.riskScore // 0))' <<<"$flagged")

  local n_usable
  n_usable=$(jq 'length' <<<"$pool")
  if [[ "$n_usable" -eq 0 ]]; then
    die "ai-service reported ${n_scored} scored transaction(s), but none belong to an account
    owned by a customer this run seeded. They are almost certainly left over from an earlier
    demo whose identities have since been reset. Post fresh transactions, or rebuild the data
    stores, then re-run."
  fi
  [[ "$(jq 'length' <<<"$flagged_pool")" -eq 0 ]] && flagged_pool="$pool"
  detail "${n_usable} of ${n_scored} scored subject(s) belong to seeded customers"

  set_ref_from  "$pool"        0 scoredTransactionId '.id'
  set_ref_num   "$pool"        0 scoredRiskScore     '.riskScore'
  set_ref_num   "$pool"        0 scoredAmount        '.amount'

  set_ref_from  "$flagged_pool" 0 flaggedTransactionId '.id'
  set_ref_num   "$flagged_pool" 0 flaggedAmount        '.amount'
  local primary_account
  primary_account=$(jq -r '.[0].accountId // empty' <<<"$flagged_pool")

  local second_index=0
  [[ "$(jq 'length' <<<"$flagged_pool")" -gt 1 ]] && second_index=1
  set_ref_from  "$flagged_pool" "$second_index" secondFlaggedTransactionId '.id'
  set_ref_num   "$flagged_pool" "$second_index" secondFlaggedAmount        '.amount'
  local secondary_account
  secondary_account=$(jq -r --argjson i "$second_index" '.[$i].accountId // empty' <<<"$flagged_pool")

  resolve_account_refs "$primary_account" primary
  resolve_account_refs "${secondary_account:-$primary_account}" secondary
}

# The set of account ids reachable by the customers this run seeded, as a JSON array.
seeded_account_ids() {
  local owner
  {
    while read -r owner; do
      [[ -n "${TOKENS[$owner]:-}" ]] || continue
      http GET /api/accounts "" "${TOKENS[$owner]}"
      [[ "$HTTP_STATUS" == "200" ]] && jq -r '.[] | (.id // .Id)' <<<"$HTTP_BODY"
    done < <(account_owners)
  } | jq -R . | jq -s .
}

set_ref_from() {
  local json="$1" index="$2" key="$3" filter="$4" value
  value=$(jq -r --argjson i "$index" ".[\$i] | ${filter} // empty" <<<"$json")
  [[ -n "$value" ]] || die "Could not resolve reference '${key}' from the AI subject list."
  REFS=$(jq --arg k "$key" --arg v "$value" '.[$k] = $v' <<<"$REFS")
}

set_ref_num() {
  local json="$1" index="$2" key="$3" filter="$4" value
  value=$(jq -r --argjson i "$index" ".[\$i] | ${filter} // empty" <<<"$json")
  [[ -n "$value" ]] || die "Could not resolve numeric reference '${key}' from the AI subject list."
  REFS=$(jq --arg k "$key" --argjson v "$value" '.[$k] = $v' <<<"$REFS")
}

# resolve_account_refs <accountId> <prefix> — balance and transaction count, read with the
# OWNER's token, because account-service scopes reads to the owner.
resolve_account_refs() {
  local account_id="$1" prefix="$2"
  [[ -n "$account_id" ]] || die "No account id available for the '${prefix}' references."

  local owner token='' balance='' count=0
  while read -r owner; do
    http GET "/api/accounts/${account_id}" "" "${TOKENS[$owner]}"
    if [[ "$HTTP_STATUS" == "200" ]]; then
      token="${TOKENS[$owner]}"
      balance=$(jget '.balance // .Balance')
      break
    fi
  done < <(account_owners)

  [[ -n "$token" ]] || die "Account ${account_id} could not be read by any seeded customer."

  http_or_die GET "/api/transactions/account/${account_id}" "" "$token" \
    "Could not count transactions on account ${account_id}." 200
  count=$(jq 'if type == "array" then length else (.count // (.items | length) // 0) end' <<<"$HTTP_BODY")

  REFS=$(jq --arg k "${prefix}AccountId"        --arg v "$account_id"  '.[$k] = $v' <<<"$REFS")
  REFS=$(jq --arg k "${prefix}AccountBalance"   --argjson v "${balance:-0}" '.[$k] = $v' <<<"$REFS")
  REFS=$(jq --arg k "${prefix}TransactionCount" --argjson v "${count:-0}"   '.[$k] = $v' <<<"$REFS")
}

build_unscored_fallback_refs() {
  local owner first_account tx_id amount
  owner=$(jq -r '.identities[] | select(.primary == true) | .username' <<<"$DATASET")
  mapfile -t ids < <(account_ids_for "$owner")
  first_account="${ids[0]}"

  http_or_die GET "/api/transactions/account/${first_account}" "" "${TOKENS[$owner]}" \
    "Could not read transactions for the fallback subject." 200
  tx_id=$(jq -r 'sort_by(-((.amount // .Amount) | fabs)) | .[0] | (.id // .Id) // empty' <<<"$HTTP_BODY")
  amount=$(jq -r 'sort_by(-((.amount // .Amount) | fabs)) | .[0] | (.amount // .Amount) // empty' <<<"$HTTP_BODY")
  [[ -n "$tx_id" ]] || die "No transactions found for the fallback subject."

  local key
  for key in scoredTransactionId flaggedTransactionId secondFlaggedTransactionId; do
    REFS=$(jq --arg k "$key" --arg v "$tx_id" '.[$k] = $v' <<<"$REFS")
  done
  for key in scoredAmount flaggedAmount secondFlaggedAmount; do
    REFS=$(jq --arg k "$key" --argjson v "$amount" '.[$k] = $v' <<<"$REFS")
  done
  REFS=$(jq --arg k scoredRiskScore --argjson v 0.5 '.[$k] = $v' <<<"$REFS")

  resolve_account_refs "$first_account" primary
  resolve_account_refs "$first_account" secondary
}

# =============================================================================================
# Approvals
# =============================================================================================
load_thresholds() {
  local any_token
  any_token=$(jq -r '.identities[0].username' <<<"$DATASET")
  http_or_die GET /api/authority/policy "" "${TOKENS[$any_token]}" \
    "Could not read the authority policy. Thresholds cannot be resolved." 200

  # Every number the dataset needs comes from HERE, resolved live. Nothing restates a threshold.
  THRESHOLDS=$(jq '[.thresholds[] | {key: .name, value: (.value | tonumber? // 0)}] | from_entries' <<<"$HTTP_BODY")
  local version
  version=$(jget '.policyVersion')
  info "Policy ${version} — $(jq 'length' <<<"$THRESHOLDS") thresholds resolved live"
}

approval_session_id() { printf 'demo-seed-%s' "$1"; }

# existing_approval_id <sessionId> <token> — echoes the id of a still-OPEN approval for this
# session, if there is one. Terminal records are deliberately ignored: reset closes everything it
# can, and treating a denied card as "already seeded" would leave a re-seeded environment with an
# empty task queue — precisely the failure this whole exercise exists to remove.
existing_approval_id() {
  local session="$1" token="$2"
  http GET "/api/authority/approvals?scope=session&sessionId=${session}&limit=20" "" "$token"
  [[ "$HTTP_STATUS" == "200" ]] || return 0
  jq -r '[.items[] | select((.status // .Status) == "pending")][0].id // empty' <<<"$HTTP_BODY"
}

# Dataset annotations ($comment / _comment keys) document the data for a human reader. They are
# not part of any API contract, so strip them before anything is sent to a service.
strip_annotations() {
  jq -c 'walk(if type == "object" then with_entries(select(.key | test("^[$_]") | not)) else . end)'
}

propose() {
  local proposer="$1" action="$2" session="$3" payload="$4" evidence="$5" facts="$6" supersedes="${7:-}"
  local body
  body=$(jq -n \
    --arg a "$action" --arg s "$session" \
    --argjson p "$(strip_annotations <<<"$payload")" \
    --argjson e "$(strip_annotations <<<"$evidence")" \
    --argjson f "$(strip_annotations <<<"$facts")" \
    --arg sup "$supersedes" \
    '{actionId: $a, sessionId: $s, payload: $p, evidence: $e, facts: $f}
     + (if $sup == "" then {} else {supersedesApprovalId: $sup} end)')

  http_or_die POST /api/authority/approvals "$body" "${TOKENS[$proposer]}" \
    "Proposal of '${action}' by '${proposer}' was refused." 200 201
}

# =============================================================================================
# propose path — the gate diagnostic
#
# The copilot task queue renders approvals, and the ONLY honest way to create one is to drive
# POST /api/authority/approvals. If that path is closed, the truthful state of the environment is
# an empty queue. This section works out whether it is closed, and says which of the two known
# gates is holding it, using nothing but read requests.
# =============================================================================================

# Results of the last probe, one line per tool: "<toolId>\t<verdict>\t<detail>"
PROBE_RESULTS=""
PROBE_VERDICT="unknown"   # open | gate-a | gate-b | unknown

probe_propose_path() {
  PROBE_RESULTS=""
  PROBE_VERDICT="unknown"

  if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import yaml' >/dev/null 2>&1; then
    PROBE_RESULTS=$'-\tunknown\tpython3 with PyYAML is needed to read the evidence contract'
    return
  fi

  local contract action reader token
  contract=$(python3 "${SCRIPT_DIR}/evidence-contract.py" "$REPO_ROOT") || {
    PROBE_RESULTS=$'-\tunknown\tcould not read the evidence contract from config/'
    return
  }

  action=$(jget_from "$DATASET" '.proposePathProbe.actionId')
  reader=$(jget_from "$DATASET" '.proposePathProbe.readAs')
  token="${TOKENS[$reader]:-}"
  if [[ -z "$token" ]]; then
    PROBE_RESULTS=$'-\tunknown\tno token for the acting '"${reader}"
    return
  fi

  local tools
  tools=$(jq -r --arg a "$action" '.actions[$a].evidence[]?' <<<"$contract")
  if [[ -z "$tools" ]]; then
    PROBE_RESULTS=$'-\tunknown\t'"${action} declares no required evidence"
    return
  fi

  local worst="ok" tool
  while read -r tool; do
    [[ -n "$tool" ]] || continue
    local path fields verdict note
    path=$(jq -r --arg t "$tool" '.tools[$t].path // empty' <<<"$contract")
    fields=$(jq -c --arg t "$tool" '.tools[$t].requiredFields // []' <<<"$contract")

    if [[ -z "$path" ]]; then
      verdict="gate-b"; note="no tool in config/copilot-tools.yaml serves this evidence key"
      PROBE_RESULTS+="${tool}"$'\t'"${verdict}"$'\t'"${note}"$'\n'
      worst="gate-b"; continue
    fi

    # Fill the path's parameters from the subjects this run actually created. A parameter with no
    # subject is reported, not guessed — a probe against an invented id proves nothing.
    local resolved="$path" missing="" name ref value
    while read -r name; do
      [[ -n "$name" ]] || continue
      ref=$(jq -r --arg n "$name" '.proposePathProbe.pathParams[$n] // ""' <<<"$DATASET")
      value=""
      [[ -n "$ref" ]] && value=$(jq -r --arg k "$ref" '.[$k] // ""' <<<"$REFS")
      if [[ -z "$value" ]]; then missing="$name"; break; fi
      resolved="${resolved//\{$name\}/$value}"
    done < <(grep -o '{[a-zA-Z]*}' <<<"$path" | tr -d '{}')

    if [[ -n "$missing" ]]; then
      PROBE_RESULTS+="${tool}"$'\t'"skipped"$'\t'"no subject seeded for {${missing}}"$'\n'
      continue
    fi

    http GET "$resolved" "" "$token"
    if ! status_in "$HTTP_STATUS" 200; then
      verdict="gate-a"
      note="HTTP ${HTTP_STATUS} for '${reader}' on ${resolved}"
      [[ "$worst" == "ok" ]] && worst="gate-a"
    elif jq -e 'type == "array"' >/dev/null 2>&1 <<<"$HTTP_BODY"; then
      # EvidenceComplete requires a JObject. A bare array cannot satisfy it under any renaming.
      verdict="gate-b"; note="returns a bare array; the contract requires an object"
      worst="gate-b"
    else
      local absent
      absent=$(jq -r --argjson f "$fields" '. as $o | [$f[] | . as $k | select($o | has($k) | not)] | join(", ")' <<<"$HTTP_BODY")
      if [[ -n "$absent" ]]; then
        verdict="gate-b"; note="200, but the object has no ${absent}"
        worst="gate-b"
      else
        verdict="ok"; note="200, object carries $(jq -r '$f | join(", ")' --argjson f "$fields" -n)"
      fi
    fi
    PROBE_RESULTS+="${tool}"$'\t'"${verdict}"$'\t'"${note}"$'\n'
  done <<<"$tools"

  case "$worst" in
    ok)     PROBE_VERDICT="open" ;;
    gate-a) PROBE_VERDICT="gate-a" ;;
    gate-b) PROBE_VERDICT="gate-b" ;;
  esac
}

report_propose_path() {
  header "Propose path — can an approval be created at all?"
  local action
  action=$(jget_from "$DATASET" '.proposePathProbe.actionId')
  detail "probing ${action} as '$(jget_from "$DATASET" '.proposePathProbe.readAs')' — the evidence a run must gather"

  local tool verdict note
  while IFS=$'\t' read -r tool verdict note; do
    [[ -n "$tool" ]] || continue
    case "$verdict" in
      ok)      success "${tool}: ${note}" ;;
      gate-a)  fail_line "${tool}: ${note}  [GATE A — authorization]" ;;
      gate-b)  fail_line "${tool}: ${note}  [GATE B — evidence contract]" ;;
      skipped) warn "${tool}: ${note}" ;;
      *)       warn "${tool}: ${note}" ;;
    esac
  done <<<"$PROBE_RESULTS"

  echo
  case "$PROBE_VERDICT" in
    open)
      success "The propose path is OPEN. Approvals can be created, so the task queue can be real."
      ;;
    gate-a)
      warn "BLOCKED at GATE A — the acting banker cannot read the evidence a run needs."
      warn "No approval can be created, so the copilot task queue will be EMPTY. That is the"
      warn "environment telling you the truth, not a seeding failure."
      ;;
    gate-b)
      warn "BLOCKED at GATE B — the evidence contract and the read tools disagree."
      warn "PolicyEvaluator.EvidenceComplete wants objects with field names the tools do not"
      warn "return, and some tools return bare arrays, which cannot satisfy it at all. Every"
      warn "proposal is refused 'evidence_incomplete', so NO approval can exist and the copilot"
      warn "task queue will be EMPTY. See tests/verification/README.md."
      ;;
    *)
      warn "Propose-path health UNKNOWN — see the note above. Approvals will not be attempted."
      ;;
  esac
}

# Set when the approvals stage was skipped because the propose path is closed. cmd_seed turns
# this into a non-zero exit: an environment whose task queue cannot be populated is NOT ready to
# demo, and saying otherwise is the failure this whole exercise exists to avoid.
APPROVALS_DEFERRED=""

seed_approvals() {
  if [[ "$PROBE_VERDICT" != "open" ]]; then
    header "Approvals — DEFERRED"
    warn "Not seeding approvals. The propose path is closed (see above), and the only honest way"
    warn "to create one is to drive POST /api/authority/approvals."
    echo >&2
    warn "  TODO(GATE B — evidence contract): $(jget_from "$DATASET" '._blockedOnEvidenceContract.unblockWhen')"
    echo >&2
    warn "$(jget_from "$DATASET" '._blockedOnEvidenceContract.whyNotSimulated')"
    APPROVALS_DEFERRED=1
    return 0
  fi

  header "Approvals"
  load_thresholds

  local count idx
  count=$(jq '.approvals | length' <<<"$DATASET")

  for ((idx = 0; idx < count; idx++)); do
    local spec key proposer action after session
    spec=$(jq --argjson i "$idx" '.approvals[$i]' <<<"$DATASET")
    key=$(jget_from "$spec" '.key')
    proposer=$(jget_from "$spec" '.proposer')
    action=$(jget_from "$spec" '.actionId')
    after=$(jget_from "$spec" '.after')
    session=$(approval_session_id "$key")

    local existing
    existing=$(existing_approval_id "$session" "${TOKENS[$proposer]}")
    if [[ -n "$existing" ]]; then
      detail "${key}: already seeded (${existing})"
      continue
    fi

    local payload evidence facts
    payload=$(resolve_placeholders "$(jq -c '.payload' <<<"$spec")" "$THRESHOLDS" "$REFS") \
      || die "${key}: could not resolve payload placeholders."
    evidence=$(resolve_placeholders "$(jq -c '.evidence' <<<"$spec")" "$THRESHOLDS" "$REFS") \
      || die "${key}: could not resolve evidence placeholders."
    facts=$(resolve_placeholders "$(jq -c '.facts' <<<"$spec")" "$THRESHOLDS" "$REFS") \
      || die "${key}: could not resolve facts placeholders."

    propose "$proposer" "$action" "$session" "$payload" "$evidence" "$facts"
    local id rung fired
    id=$(jget '.id')
    rung=$(jget '.requiredRung')
    fired=$(jq -r '[(.firedEscalators // .FiredEscalators // [])[] | (.key // .Key // .)] | join(", ")' <<<"$HTTP_BODY")

    # An approval seeded to demonstrate an escalator MUST actually have fired it. Otherwise the
    # demo shows a card that quietly proves the opposite of the point being made.
    local want_escalator
    want_escalator=$(jget_from "$spec" '.escalator')
    if [[ -n "$want_escalator" ]] && ! grep -qw "$want_escalator" <<<"$fired"; then
      die "${key}: expected escalator '${want_escalator}' to fire, but the engine fired [${fired}].
    The dataset and config/authority-policy.yaml have diverged — fix the facts, not this check."
    fi

    local label="${key}: ${rung}"
    [[ -n "$fired" ]] && label="${label} (escalated: ${fired})"
    success "$label"

    case "$after" in
      leave-pending) ;;
      sign-slot0)     sign_approval "$id" "$proposer" "$(jget_from "$spec" '.signComment')" ;;
      sign-full)      sign_to_quorum "$id" "$proposer" "$(jget_from "$spec" '.signComment')" ;;
      deny)           deny_approval "$id" "$(jget_from "$spec" '.denyBy')" "$(jget_from "$spec" '.denyReason')" ;;
      supersede)      supersede_approval "$id" "$spec" "$proposer" "$session" "$action" "$evidence" "$facts" ;;
      *)              die "${key}: unknown 'after' verb '${after}'." ;;
    esac
  done
}

sign_approval() {
  local id="$1" signer="$2" comment="$3" body
  body=$(jq -n --arg c "$comment" '{comment: $c}')
  http_or_die POST "/api/authority/approvals/${id}/sign" "$body" "${TOKENS[$signer]}" \
    "'${signer}' could not sign approval ${id}." 200
  detail "signed by ${signer} — $(jget '.signaturesCollected')/$(jget '.requiredSigners'), status $(jget '.status')"
}

sign_to_quorum() {
  local id="$1" first="$2" comment="$3"
  sign_approval "$id" "$first" "$comment"
  local status
  status=$(jget '.status')
  if [[ "$status" != "signed" ]]; then
    # Needs a co-signer. Anyone senior enough who is not the requester.
    local supervisor
    supervisor=$(jq -r '.identities[] | select(.role == "supervisor") | .username' <<<"$DATASET" | head -1)
    sign_approval "$id" "$supervisor" "Second opinion recorded; the correction matches the fee schedule."
  fi
}

deny_approval() {
  local id="$1" denier="$2" reason="$3" body
  body=$(jq -n --arg r "$reason" '{reason: $r}')
  http_or_die POST "/api/authority/approvals/${id}/deny" "$body" "${TOKENS[$denier]}" \
    "'${denier}' could not deny approval ${id}." 200
  detail "denied by ${denier} — terminalReason $(jget '.terminalReason')"
}

supersede_approval() {
  local id="$1" spec="$2" proposer="$3" session="$4" action="$5" evidence="$6" facts="$7"
  local revised
  revised=$(resolve_placeholders "$(jq -c '.revisedPayload' <<<"$spec")" "$THRESHOLDS" "$REFS")

  propose "$proposer" "$action" "$session" "$revised" "$evidence" "$facts" "$id"
  local replacement
  replacement=$(jget '.id')

  http_or_die GET "/api/authority/approvals/${id}" "" "${TOKENS[$proposer]}" \
    "Could not re-read the superseded approval ${id}." 200
  local terminal
  terminal=$(jget '.terminalReason')
  [[ "$terminal" == "PAYLOAD_SUPERSEDED" ]] || die \
    "Expected the replaced approval to carry terminalReason PAYLOAD_SUPERSEDED, got '${terminal}'."
  detail "superseded by ${replacement} — terminalReason PAYLOAD_SUPERSEDED"
}

# =============================================================================================
# seed
# =============================================================================================
cmd_seed() {
  preflight
  seed_identities
  seed_accounts
  seed_transactions
  resolve_evidence_refs
  lock_target_user
  collect_ai_subjects
  probe_propose_path
  report_propose_path
  seed_approvals

  header "Seed complete"
  cmd_show_summary
  echo
  local primary_banker
  primary_banker="$(jq -r '[.identities[] | select(.role == "banker")][0].username' <<<"$DATASET")"
  info "Sign in at ${DEMO_BASE_URL} as '${primary_banker}' and open /copilot."
  info "Every seeded identity uses the value of \$DEMO_SEED_PASSWORD."

  if [[ -n "$APPROVALS_DEFERRED" ]]; then
    echo >&2
    fail_line "SEEDED, BUT NOT DEMO-READY."
    fail_line "Identities, accounts and transactions are in place. The copilot task queue is EMPTY"
    fail_line "and will stay empty until the propose path above is open. Exiting non-zero so this"
    fail_line "cannot be mistaken for a working environment."
    fail_line "Re-run demo:seed once it is fixed — the approvals are seeded automatically then."
    return 3
  fi
}

# =============================================================================================
# show
# =============================================================================================
login_all_present() {
  local username
  while read -r username; do
    http POST /api/auth/login \
      "$(jq -n --arg u "$username" --arg p "$PASSWORD" '{username: $u, password: $p}')"
    if [[ "$HTTP_STATUS" == "200" ]]; then
      TOKENS["$username"]=$(jget '.token // .Token')
      ROLES["$username"]=$(jget '.role // .Role')
      USER_IDS["$username"]=$(jget '.userId // .UserId')
    fi
  done < <(identity_usernames)
}

cmd_show() {
  preflight
  login_all_present
  discover_evidence_account
  cmd_show_summary
  probe_propose_path
  report_propose_path
  [[ "$PROBE_VERDICT" == "open" ]] || return 3
}

# show must not write, so it cannot rely on seed_accounts having run. Re-derive the evidence
# account by matching the dataset's declared subject against what the owner can actually see.
discover_evidence_account() {
  local owner atype ordinal
  owner=$(jq -r '[.accounts[] | select(.evidenceSubject == true)][0].owner // empty' <<<"$DATASET")
  atype=$(jq -r '[.accounts[] | select(.evidenceSubject == true)][0].accountType // empty' <<<"$DATASET")
  [[ -n "$owner" && -n "${TOKENS[$owner]:-}" ]] || return 0

  ordinal=$(jq -r --arg o "$owner" --arg t "$atype" \
    '[.accounts[] | select(.owner == $o)] | map(.accountType) | index($t) // 0' <<<"$DATASET")

  http GET /api/accounts "" "${TOKENS[$owner]}"
  [[ "$HTTP_STATUS" == "200" ]] || return 0
  local id
  id=$(jq -r --arg t "$atype" '[.[] | select((.accountType // .AccountType) == $t)][0] | (.id // .Id) // empty' <<<"$HTTP_BODY")
  [[ -n "$id" ]] || return 0
  EVIDENCE_ACCOUNT="$id"
  REFS=$(jq --arg k evidenceAccountId --arg v "$id" '.[$k] = $v' <<<"$REFS")

  # The locked-user subject too, so get_user can be probed where the action needs it.
  local admin_user target uid
  admin_user=$(jq -r '.identities[] | select(.registerFirst == true) | .username' <<<"$DATASET")
  target=$(jq -r '.identities[] | select(.locked == true) | .username' <<<"$DATASET")
  if [[ -n "${TOKENS[$admin_user]:-}" && -n "$target" ]]; then
    http GET /api/admin/users "" "${TOKENS[$admin_user]}"
    if [[ "$HTTP_STATUS" == "200" ]]; then
      uid=$(jq -r --arg u "$target" '.[] | select((.username // .Username) == $u) | (.id // .Id)' <<<"$HTTP_BODY" | head -1)
      [[ -n "$uid" ]] && REFS=$(jq --arg k lockedUserId --arg v "$uid" '.[$k] = $v' <<<"$REFS")
    fi
  fi
}

cmd_show_summary() {
  local admin_user admin_token
  admin_user=$(jq -r '.identities[] | select(.registerFirst == true) | .username' <<<"$DATASET")
  admin_token="${TOKENS[$admin_user]:-}"

  header "Identities"
  if [[ -z "$admin_token" ]]; then
    warn "No admin token — identity detail unavailable. Has the environment been seeded?"
  else
    http_or_die GET /api/admin/users "" "$admin_token" "Could not list users." 200
    local all="$HTTP_BODY"
    printf '  %-16s %-12s %-10s %s\n' USERNAME ROLE LOCKED PRESENT
    local username
    while read -r username; do
      local row role locked present
      row=$(jq -c --arg u "$username" '[.[] | select((.username // .Username) == $u)][0] // empty' <<<"$all")
      if [[ -z "$row" ]]; then
        present="no"; role="-"; locked="-"
      else
        present="yes"
        role=$(jget_from "$row" '(.role // .Role)')
        locked=$(jget_from "$row" '((.isLocked // .IsLocked) | tostring)')
        case "$locked" in yes|true) locked="yes"; LOCKED_NOW[$username]=1 ;; *) locked="no" ;; esac
      fi
      printf '  %-16s %-12s %-10s %s\n' "$username" "${role:--}" "${locked:--}" "$present"
    done < <(identity_usernames)
  fi

  header "Accounts and transactions"
  local owner
  while read -r owner; do
    if [[ -z "${TOKENS[$owner]:-}" ]]; then
      # A locked identity cannot log in, and account-service scopes reads to the owner. That is
      # expected for the user.unlock subject, so say so rather than implying the data is missing.
      if [[ -n "${LOCKED_NOW[$owner]:-}" ]]; then
        printf '  %-16s (locked — owner-scoped reads unavailable)\n' "$owner"
      else
        printf '  %-16s (not present)\n' "$owner"
      fi
      continue
    fi
    http GET /api/accounts "" "${TOKENS[$owner]}"
    local n_accounts=0 n_tx=0
    if [[ "$HTTP_STATUS" == "200" ]]; then
      n_accounts=$(jq 'length' <<<"$HTTP_BODY")
      local aid
      while read -r aid; do
        [[ -n "$aid" ]] || continue
        http GET "/api/transactions/account/${aid}" "" "${TOKENS[$owner]}"
        [[ "$HTTP_STATUS" == "200" ]] && n_tx=$((n_tx + $(count_records "$HTTP_BODY")))
      done < <(jq -r '.[] | (.id // .Id)' <<<"$HTTP_BODY")
    fi
    printf '  %-16s %s account(s), %s transaction(s)\n' "$owner" "$n_accounts" "$n_tx"
  done < <(account_owners)

  header "AI scoring"
  if [[ -n "$admin_token" ]]; then
    http GET /api/admin/transactions "" "$admin_token"
    local scored='[]'
    [[ "$HTTP_STATUS" == "200" ]] && scored="$HTTP_BODY"
    http GET /api/admin/flagged-transactions "" "$admin_token"
    local flagged='[]'
    [[ "$HTTP_STATUS" == "200" ]] && flagged="$HTTP_BODY"
    printf '  %s scored, %s flagged\n' \
      "$(jq 'if type=="array" then length else 0 end' <<<"$scored")" \
      "$(jq 'if type=="array" then length else 0 end' <<<"$flagged")"
  else
    warn "No admin token — AI scoring detail unavailable."
  fi

  header "Approvals"
  local reader
  reader=$(jq -r '.identities[] | select(.role == "supervisor") | .username' <<<"$DATASET" | head -1)
  if [[ -z "${TOKENS[$reader]:-}" ]]; then
    warn "No supervisor token — approval detail unavailable."
    return
  fi

  http_or_die GET "/api/authority/approvals?scope=all&limit=200" "" "${TOKENS[$reader]}" \
    "Could not list approvals." 200
  local approvals="$HTTP_BODY"

  jq -r '
    .items
    | group_by(.status)
    | map({status: .[0].status, n: length})
    | .[]
    | "  \(.status): \(.n)"' <<<"$approvals"

  echo
  printf '  %-30s %-10s %-9s %-8s %s\n' ACTION STATUS RUNG SIGS ESCALATORS/TERMINAL
  jq -r '
    .items
    | sort_by(.createdAt)
    | .[]
    | [ .actionId,
        .status,
        .requiredRung,
        "\(.signaturesCollected)/\(.requiredSigners)",
        ((.firedEscalators // [] | map(.key) | join(",")) as $e
          | if (.terminalReason // "") != "" then .terminalReason
            elif $e != "" then $e
            else "-" end)
      ] | @tsv' <<<"$approvals" \
  | while IFS=$'\t' read -r a s r g e; do
      printf '  %-30s %-10s %-9s %-8s %s\n' "$a" "$s" "$r" "$g" "$e"
    done

  header "Copilot task queue, as each role sees it"
  local banker
  banker=$(jq -r '.identities[] | select(.role == "banker") | .username' <<<"$DATASET" | head -1)
  queue_view "$banker" mine "banker '${banker}' — own requests"
  queue_view "$reader" awaiting-me "supervisor '${reader}' — co-sign queue"
}

queue_view() {
  local username="$1" scope="$2" label="$3"
  if [[ -z "${TOKENS[$username]:-}" ]]; then
    warn "${label}: no token"
    return
  fi
  http GET "/api/authority/approvals?scope=${scope}&limit=200" "" "${TOKENS[$username]}"
  if [[ "$HTTP_STATUS" != "200" ]]; then
    warn "${label}: HTTP ${HTTP_STATUS}"
    return
  fi
  # Same bucketing as src/ui-app/src/components/copilot/TaskQueuePane.tsx groupApprovals().
  jq -r --arg l "$label" '
    (.items | map(select(.status == "proposed" or .status == "pending"))) as $open
    | "  \($l)
      NEEDS YOU              \($open | map(select(.callerMaySign)) | length)
      WAITING ON A CO-SIGNER \($open | map(select(.callerMaySign | not)) | length)
      RUNNING                \(.items | map(select(.status == "signed")) | length)
      DONE TODAY             \(.items | map(select(.status == "executed" or .status == "denied")) | length)"
  ' <<<"$HTTP_BODY"
}

# =============================================================================================
# reset
# =============================================================================================
cmd_reset() {
  preflight
  login_all_present

  local admin_user admin_token supervisor
  admin_user=$(jq -r '.identities[] | select(.registerFirst == true) | .username' <<<"$DATASET")
  admin_token="${TOKENS[$admin_user]:-}"
  supervisor=$(jq -r '.identities[] | select(.role == "supervisor") | .username' <<<"$DATASET" | head -1)

  header "Closing open approvals"
  if [[ -z "${TOKENS[$supervisor]:-}" ]]; then
    warn "No supervisor token — open approvals cannot be closed. A supervisor is required:"
    warn "admin carries banking seniority 0 and is not an eligible approver by design."
  else
    http_or_die GET "/api/authority/approvals?scope=all&limit=200" "" "${TOKENS[$supervisor]}" \
      "Could not list approvals." 200
    local open_ids
    open_ids=$(jq -r '.items[] | select(.status == "pending" or .status == "proposed") | .id' <<<"$HTTP_BODY")
    if [[ -z "$open_ids" ]]; then
      detail "no open approvals"
    else
      local id
      while read -r id; do
        [[ -n "$id" ]] || continue
        http POST "/api/authority/approvals/${id}/deny" \
          "$(jq -n '{reason: "Demo environment reset requested by the operator; this request is being withdrawn rather than left to expire in the queue."}')" \
          "${TOKENS[$supervisor]}"
        if status_in "$HTTP_STATUS" 200; then
          success "closed ${id}"
        else
          warn "could not close ${id} (HTTP ${HTTP_STATUS})"
        fi
      done <<<"$open_ids"
    fi
  fi

  header "Removing demo identities"
  if [[ -z "$admin_token" ]]; then
    warn "No admin token — identities cannot be removed."
  else
    http_or_die GET /api/admin/users "" "$admin_token" "Could not list users." 200
    local all="$HTTP_BODY" username
    while read -r username; do
      if [[ "$username" == "$admin_user" && "$INCLUDE_ADMIN" != "true" ]]; then
        detail "keeping ${username} (needed to re-seed; use --include-admin to remove it)"
        continue
      fi
      local uid
      uid=$(jq -r --arg u "$username" '.[] | select((.username // .Username) == $u) | (.id // .Id)' <<<"$all" | head -1)
      if [[ -z "$uid" ]]; then
        detail "${username} not present"
        continue
      fi
      http DELETE "/api/admin/users/${uid}" "" "$admin_token"
      if status_in "$HTTP_STATUS" 200 204; then
        success "deleted ${username}"
      else
        warn "could not delete ${username} (HTTP ${HTTP_STATUS}): ${HTTP_BODY}"
      fi
    done < <(identity_usernames)
  fi

  header "What reset does NOT remove"
  cat <<'EOF'
  · Accounts and transactions — neither account-service nor transaction-service exposes a
    delete endpoint, so records belonging to deleted identities are orphaned, not erased.
  · Scored and flagged transactions — held in Redis under their own TTL.
  · Terminal approvals — the approval store has no delete verb by design; they age out under
    the Cosmos TTL named by the `retention_seconds` threshold.
  For a genuinely empty environment, rebuild the data stores.
EOF

  if [[ "$DO_RESEED" == "true" ]]; then
    TOKENS=(); ROLES=(); USER_IDS=(); REFS='{}'
    cmd_seed
  fi
}

# =============================================================================================
main() {
  parse_args "$@"
  load_dataset
  case "$VERB" in
    seed)  cmd_seed ;;
    show)  cmd_show ;;
    reset) cmd_reset ;;
  esac
}

main "$@"
