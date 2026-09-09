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
ALLOW_UNESCALATED="false"
DO_PROBE="false"

DATASET=""
# NOT initialised to "" — DEMO_BASE_URL is one of the documented environment overrides, and
# clearing it here would silently discard the caller's choice of target.
DEMO_BASE_URL="${DEMO_BASE_URL:-}"
PASSWORD=""
EMAIL_DOMAIN=""

declare -A TOKENS=()      # username -> bearer token
declare -A ACCOUNT_IDS=() # "<owner>:<datasetIndex>" -> real account id, claimed or created
EVIDENCE_ACCOUNT=""       # the CUSTOMER account the propose-path probe drives a run against
EVIDENCE_ACCOUNT_ALT=""   # a second customer account, for approvals that need a distinct one
declare -A LOCKED_NOW=()  # username -> set when the admin list reports the account locked
declare -A USER_IDS=()    # username -> user id
declare -A ROLES=()       # username -> role as the issued token reports it
REFS='{}'                 # runtime-discovered values for {"@ref": ...}
THRESHOLDS='{}'           # live policy thresholds for {"@threshold": ...}
THRESHOLDS_RAW='{}'       # the same thresholds as PUBLISHED strings, so money keeps its scale

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
  --allow-unescalated    seed only: continue when no flagged transaction reaches the
                         dual-control line. flag-review-denied then seeds as an L1 card
                         instead of L2, and the run is NOT measurement-grade.
  --probe                show only: drive a REAL copilot run to prove an approval can be
                         created. This WRITES — it creates an approval, because that is the
                         only honest answer to the question. Exits 3 if the run does not
                         reach its success frame.
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
      --allow-unescalated) ALLOW_UNESCALATED="true"; shift ;;
      --probe) DO_PROBE="true"; shift ;;
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
# change — which is exactly what banker-customer-read-ruling.md §B6 required: the accounts moved
# from the banker to the customers and this function did not have to know.
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

# The accounts an approval cites as evidence belong to CUSTOMERS (Casey and Dana), and the
# banker reads them by holding the banker role — banker-customer-read-ruling.md §B1. They are
# read here with the owner's token because the owner can always read their own; what the ruling
# changed is that the banker can too, which is what the copilot run depends on.
# These references are what the approval payloads resolve against.
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

# owner_transactions <owner> — the owner's OWN transaction rows, across all their accounts, via
# GET /api/transactions/my.
#
# Why not GET /api/transactions/account/{id}: that route derives a non-privileged caller's
# entitlement from the rows it is about to return, so an account with zero rows proves nothing and
# answers 403 — an owner cannot read their own empty ledger. On a fresh reseed every ledger is
# empty. /my is scoped to the caller's userId, so it asks a question the caller's own token is the
# proof of: "what have I posted". See docs/design/empty-ledger-narrowing-ruling.md §E4.
owner_transactions() {
  local owner="$1"
  http_or_die GET /api/transactions/my "" "${TOKENS[$owner]}" \
    "Could not list transactions for '${owner}'." 200
  printf '%s' "$HTTP_BODY"
}

# transactions_on_account <json> <accountId> — the subset of <json> posted to <accountId>.
#
# The (.accountId // .AccountId) pair is load-bearing, not decorative. The API may serialize
# PascalCase; a bare .accountId would then match zero rows, every idempotency check would report
# "not yet posted", and every reseed would double-post every transaction — a failure that PASSES.
# Guarded by tests/demo/test-demo-dataset.sh, group "Empty-ledger entitlement and PascalCase
# tolerance" — both textually and behaviourally against a PascalCase fixture.
transactions_on_account() {
  local json="$1" account_id="$2" out
  out=$(jq -c --arg a "$account_id" \
    '[ (if type == "array" then . else (.items // []) end)[]
       | select((.accountId // .AccountId) == $a) ]' <<<"$json" 2>/dev/null) || out='[]'
  printf '%s' "${out:-[]}"
}

seed_transactions() {
  header "Transactions"

  local owner
  while read -r owner; do
    local token="${TOKENS[$owner]}"

    # One read of the owner's ledger per owner, taken before anything is posted. Rows this run
    # posts are tracked in posted_now so a repeated description inside one run is still caught.
    local existing posted_now=$'\n'
    existing=$(owner_transactions "$owner")

    local count idx
    count=$(jq --arg o "$owner" '[.transactions[] | select(.owner == $o)] | length' <<<"$DATASET")
    for ((idx = 0; idx < count; idx++)); do
      local spec account_index account_id description
      spec=$(jq --arg o "$owner" --argjson i "$idx" '[.transactions[] | select(.owner == $o)][$i]' <<<"$DATASET")
      account_index=$(jget_from "$spec" '.accountIndex')
      description=$(jget_from "$spec" '.description')
      account_id="${ACCOUNT_IDS[${owner}:${account_index}]:-${ACCOUNT_IDS[${owner}:0]:-}}"
      [[ -n "$account_id" ]] || die "'${owner}' has no account at index ${account_index}; cannot post '${description}'."

      local on_account
      on_account=$(transactions_on_account "$existing" "$account_id")
      if [[ "$posted_now" == *$'\n'"${account_id}|${description}"$'\n'* ]] ||
         jq -e --arg d "$description" \
           'any(.[]; (.description // .Description) == $d)' >/dev/null <<<"$on_account"; then
        detail "${owner}: '${description}' already posted"
        continue
      fi

      local body
      body=$(jq -c --arg a "$account_id" \
        '{accountId: $a, amount: .amount, type: .type, description: .description,
          currency: "USD", category: .category}' <<<"$spec")
      http_or_die POST /api/transactions "$body" "$token" \
        "Could not post transaction '${description}' for '${owner}'." 200 201
      posted_now+="${account_id}|${description}"$'\n'
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
# qualifying_flagged_pool <flaggedJson> <ownedAccountIdsJson> <dualControlAmount>
#
# The flagged rows on accounts THIS RUN seeded whose amount is at or above the live
# dual-control line, sorted -amount then -riskScore as tie-break, so the choice between two
# qualifiers is total rather than incidental.
#
# This one function is called from BOTH the poll's break condition and the selection below,
# deliberately. See docs/design/seeded-approval-rung-nondeterminism-ruling.md §R10: a seeder
# must wait for the thing it will later require, and any predicate used to SELECT a subject
# must be the same predicate that TERMINATES the wait. A filter applied after a poll that
# waited for something else is not a filter, it is a race with an assertion bolted on the end.
#
# .amount goes through tonumber because jq sorts and compares a STRING above every number:
# an untyped "9350" >= 25000 is true, which would let a below-the-line row qualify silently
# and re-create the exact defect this function exists to close.
qualifying_flagged_pool() {
  local flagged="$1" owned="$2" line="$3"
  jq --argjson owned "$owned" --argjson line "$line" '
    [ .[]
      | select(.accountId as $a | $owned | index($a))
      | select(((.amount // 0) | tonumber? // -1) >= $line)
    ]
    | sort_by(-((.amount // 0) | tonumber? // 0), -((.riskScore // 0) | tonumber? // 0))
  ' <<<"$flagged"
}

collect_ai_subjects() {
  header "AI-scored subjects"

  local admin_user admin_token
  admin_user=$(jq -r '.identities[] | select(.registerFirst == true) | .username' <<<"$DATASET")
  admin_token="${TOKENS[$admin_user]}"

  local wait_total interval min_required
  wait_total=$(jget_from "$DATASET" '.scoring.pollSeconds')
  interval=$(jget_from "$DATASET" '.scoring.pollIntervalSeconds')
  min_required=$(jget_from "$DATASET" '.scoring.minScoredRequired')

  # The dual-control line is a POLICY value and is read live, never restated here.
  # load_thresholds is idempotent and the approvals stage calls it again for free.
  load_thresholds
  local dual_control
  dual_control=$(jq -r '.flagged_transaction_dual_control_amount // empty' <<<"$THRESHOLDS")
  [[ -n "$dual_control" ]] || die \
    "The authority policy publishes no 'flagged_transaction_dual_control_amount' threshold, so
    no qualifying flagged subject can be identified and flag-review-denied's rung cannot be
    pinned. config/authority-policy.yaml and this seeder have diverged."

  # The set of accounts this run's customers actually own, resolved ONCE before the wait.
  #
  # Scored and flagged records outlive the identities that produced them: reset deletes a user
  # but nothing deletes their accounts, transactions or Redis-held scores. So the only count
  # worth waiting on is the count of subjects OWNED BY THIS RUN. Waiting on the total is the
  # same defect as the old propose-path probe — waiting for anything instead of the thing you
  # need — and it fails in exactly the way that hurts most: fifty orphans clear the threshold
  # instantly, the loop breaks before the fresh transactions have been scored at all, and the
  # run dies three lines later on an ownership check that reads like a data-store problem.
  local owned
  owned=$(seeded_account_ids)

  local waited=0 scored='[]' flagged='[]' n_usable=0 qualifying='[]' n_qualifying=0
  while (( waited <= wait_total )); do
    http GET /api/admin/transactions "" "$admin_token"
    if [[ "$HTTP_STATUS" == "200" ]]; then
      scored=$(jq 'if type == "array" then . else [] end' <<<"$HTTP_BODY")
    elif [[ "$HTTP_STATUS" == "403" ]]; then
      die "The admin token was refused by ai-service (403). Scored transactions cannot be read."
    fi

    http GET /api/admin/flagged-transactions "" "$admin_token"
    [[ "$HTTP_STATUS" == "200" ]] && flagged=$(jq 'if type == "array" then . else [] end' <<<"$HTTP_BODY")

    n_usable=$(jq --argjson owned "$owned" \
      '[.[] | select(.accountId as $a | $owned | index($a))] | length' <<<"$scored")
    qualifying=$(qualifying_flagged_pool "$flagged" "$owned" "$dual_control")
    n_qualifying=$(jq 'length' <<<"$qualifying")

    # BOTH conditions, never either. n_usable governs scoredTransactionId; the qualifying
    # subject governs flag-review-denied's RUNG, and the old break condition waited only for
    # the first — so the subject was whichever flagged row happened to exist at that instant,
    # and the card landed on L1 or L2 by luck. Waiting for the first N scored rows and then
    # filtering for a large one is the race §R10 names.
    #
    # --allow-unescalated is the operator's deliberate opt-out: they have already accepted an
    # L1 card, so making them sit out the full poll for a qualifier they have agreed to do
    # without would only cost them time on the morning of a demo.
    if (( n_usable >= min_required )) \
       && { (( n_qualifying > 0 )) || [[ "$ALLOW_UNESCALATED" == "true" ]]; }; then
      break
    fi
    detail "waiting for ai-service to score this run's transactions — ${n_usable}/${min_required} on seeded accounts, ${n_qualifying} flagged at or above the ${dual_control} dual-control line, $(jq 'length' <<<"$scored") scored in total (${waited}s/${wait_total}s)"
    sleep "$interval"
    waited=$((waited + interval))
  done

  local n_scored n_flagged
  n_scored=$(jq 'length' <<<"$scored")
  n_flagged=$(jq 'length' <<<"$flagged")
  info "ai-service reports ${n_scored} scored, ${n_flagged} flagged — ${n_usable} scored on accounts this run seeded"

  if (( n_usable < min_required )); then
    if [[ "$ALLOW_UNSCORED" != "true" ]]; then
      if (( n_scored == 0 )); then
        die "ai-service produced no scored transactions at all within ${wait_total}s.
    The subjects for transaction.score.override and transaction.flag.review would be invented,
    and the Copilot's read tools would 404 on them during the demo.
    Check the ai-service stream consumer and its Foundry connectivity, then re-run.
    To continue anyway with real transaction ids and a placeholder score: --allow-unscored"
      fi
      die "ai-service scored ${n_scored} transaction(s) within ${wait_total}s, but only ${n_usable}
    belong to an account owned by a customer this run seeded, and ${min_required} are required.
    The rest are almost certainly left over from an earlier demo whose identities have since
    been reset — scores outlive the identities that produced them.
    Either ai-service has not yet consumed this run's transactions (raise scoring.pollSeconds),
    or its stream consumer is not running. Rebuild the data stores for a clean count.
    To continue anyway with real transaction ids and a placeholder score: --allow-unscored"
    fi
    warn "Continuing without usable AI scores (--allow-unscored). The score-override subject will"
    warn "be a real transaction id with a PLACEHOLDER risk score; get_scored_transaction will 404."
    build_unscored_fallback_refs
    return
  fi

  # Highest risk first — that is what a banker would be looking at.
  local pool flagged_pool
  pool=$(jq --argjson owned "$owned" \
    '[.[] | select(.accountId as $a | $owned | index($a))] | sort_by(-(.riskScore // 0))' <<<"$scored")
  flagged_pool=$(jq --argjson owned "$owned" \
    '[.[] | select(.accountId as $a | $owned | index($a))] | sort_by(-(.riskScore // 0))' <<<"$flagged")

  # The fallback that used to stand here — flagged_pool="$pool" when nothing was flagged — is
  # deliberately gone (§R10). A merely-scored row is not a flagged row, and substituting one
  # produced a subject that get_flagged_transaction 404s on, live, in front of the audience.
  if [[ "$(jq 'length' <<<"$flagged_pool")" -eq 0 ]]; then
    die "ai-service flagged no transaction at all on an account this run seeded within ${wait_total}s.
    The subject for transaction.flag.review would not be a flagged transaction, and
    get_flagged_transaction would 404 on it live during the demo.
    Check the ai-service stream consumer and its FLAGGING_THRESHOLD, then re-run.
    To continue anyway with real transaction ids and a placeholder score: --allow-unscored"
  fi

  # The subject flag-review-denied is built on. It must clear the dual-control line or the card
  # seeds L1 and quietly demonstrates the opposite of the point being made.
  local subject_pool="$qualifying"
  if (( n_qualifying == 0 )); then
    if [[ "$ALLOW_UNESCALATED" != "true" ]]; then
      die "ai-service flagged $(jq 'length' <<<"$flagged_pool") transaction(s) on accounts this run seeded
    within ${wait_total}s, but none of them reaches the ${dual_control} dual-control line.
    flag-review-denied would seed as an L1 card, and the large-flagged-amount escalator the
    demo is built around would not fire — the card would prove the opposite of the point.
    Either the model scored the large wires below ai-service's FLAGGING_THRESHOLD, or
    scoring.pollSeconds is too low for the current transaction count.
    To continue anyway with the largest flagged subject available, as an L1 card: --allow-unescalated"
    fi
    warn "Continuing without a qualifying flagged subject (--allow-unescalated). No flagged"
    warn "transaction on a seeded account reaches the ${dual_control} dual-control line, so"
    warn "flag-review-denied will seed as L1, NOT the L2 the demo narrates."
    warn "This run is therefore NOT measurement-grade: do not baseline a rung off it."
    subject_pool=$(jq \
      'sort_by(-((.amount // 0) | tonumber? // 0), -((.riskScore // 0) | tonumber? // 0))' \
      <<<"$flagged_pool")
  fi

  # '.id', NOT '.transactionId', and this is not a bug. A flagged row carries both, and they
  # are different things: '.id' is the SCORING EVENT's uuid and is the Redis key suffix
  # ai-service resolves get_flagged_transaction / get_scored_transaction on
  # (src/ai-service/app/routes/api.py:244). '.transactionId' is the banking transaction's own
  # id, is empty on most rows, and 404s on both read tools. Changing this to '.transactionId'
  # breaks every evidence read in the demo. See the ruling §R11.
  set_ref_from  "$pool"        0 scoredTransactionId '.id'
  set_ref_num   "$pool"        0 scoredRiskScore     '.riskScore'
  set_ref_num   "$pool"        0 scoredAmount        '.amount'

  set_ref_from  "$flagged_pool" 0 flaggedTransactionId '.id'
  set_ref_num   "$flagged_pool" 0 flaggedAmount        '.amount'
  local primary_account
  primary_account=$(jq -r '.[0].accountId // empty' <<<"$flagged_pool")

  set_ref_from  "$subject_pool" 0 secondFlaggedTransactionId '.id'
  set_ref_num   "$subject_pool" 0 secondFlaggedAmount        '.amount'
  local secondary_account
  secondary_account=$(jq -r '.[0].accountId // empty' <<<"$subject_pool")

  info "flag-review-denied subject: $(jq -r '.[0].amount' <<<"$subject_pool") against the ${dual_control} dual-control line"

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

# resolve_account_refs <accountId> <prefix> [owner] — balance and transaction count, read with the
# OWNER's token, because account-service scopes reads to the owner. Pass <owner> when the caller
# already knows it, to skip the probe loop and reuse the identity.
#
# <prefix>TransactionCount counts the OWNER's rows on that account, not the account's ledger. Under
# single ownership (every account in config/demo-dataset.json has exactly one owner, and
# Account.UserId is single-valued) those are the same set. Joint accounts would make this an
# under-count. See docs/design/empty-ledger-narrowing-ruling.md §E5.
resolve_account_refs() {
  local account_id="$1" prefix="$2" known_owner="${3:-}"
  [[ -n "$account_id" ]] || die "No account id available for the '${prefix}' references."

  local owner owner_name='' balance='' count=0
  while read -r owner; do
    [[ -n "$known_owner" && "$owner" != "$known_owner" ]] && continue
    http GET "/api/accounts/${account_id}" "" "${TOKENS[$owner]}"
    if [[ "$HTTP_STATUS" == "200" ]]; then
      owner_name="$owner"
      balance=$(jget '.balance // .Balance')
      break
    fi
  done < <(account_owners)

  [[ -n "$owner_name" ]] || die "Account ${account_id} could not be read by any seeded customer."

  count=$(transactions_on_account "$(owner_transactions "$owner_name")" "$account_id" | jq 'length')

  REFS=$(jq --arg k "${prefix}AccountId"        --arg v "$account_id"  '.[$k] = $v' <<<"$REFS")
  REFS=$(jq --arg k "${prefix}AccountBalance"   --argjson v "${balance:-0}" '.[$k] = $v' <<<"$REFS")
  REFS=$(jq --arg k "${prefix}TransactionCount" --argjson v "${count:-0}"   '.[$k] = $v' <<<"$REFS")
}

build_unscored_fallback_refs() {
  local owner first_account tx_id amount rows
  owner=$(jq -r '.identities[] | select(.primary == true) | .username' <<<"$DATASET")
  mapfile -t ids < <(account_ids_for "$owner")
  first_account="${ids[0]}"

  rows=$(transactions_on_account "$(owner_transactions "$owner")" "$first_account")
  tx_id=$(jq -r 'sort_by(-((.amount // .Amount) | fabs)) | .[0] | (.id // .Id) // empty' <<<"$rows")
  amount=$(jq -r 'sort_by(-((.amount // .Amount) | fabs)) | .[0] | (.amount // .Amount) // empty' <<<"$rows")
  [[ -n "$tx_id" ]] || die "No transactions found for the fallback subject."

  local key
  for key in scoredTransactionId flaggedTransactionId secondFlaggedTransactionId; do
    REFS=$(jq --arg k "$key" --arg v "$tx_id" '.[$k] = $v' <<<"$REFS")
  done
  for key in scoredAmount flaggedAmount secondFlaggedAmount; do
    REFS=$(jq --arg k "$key" --argjson v "$amount" '.[$k] = $v' <<<"$REFS")
  done
  REFS=$(jq --arg k scoredRiskScore --argjson v 0.5 '.[$k] = $v' <<<"$REFS")

  resolve_account_refs "$first_account" primary   "$owner"
  resolve_account_refs "$first_account" secondary "$owner"
}

# =============================================================================================
# Approvals
# =============================================================================================
load_thresholds() {
  # Idempotent: the propose-path probe needs the thresholds before the approvals stage does,
  # and reading the policy twice would print the banner twice for no gain.
  [[ "$THRESHOLDS" == "{}" ]] || return 0

  local any_user any_token
  any_user=$(jq -r '.identities[0].username' <<<"$DATASET")
  any_token="${TOKENS[$any_user]:-}"
  [[ -n "$any_token" ]] || die \
    "No token for '${any_user}', so the authority policy cannot be read and no threshold can be
    resolved. Has this environment been seeded? Run demo:seed."
  http_or_die GET /api/authority/policy "" "$any_token" \
    "Could not read the authority policy. Thresholds cannot be resolved." 200

  # Every number the dataset needs comes from HERE, resolved live. Nothing restates a threshold.
  THRESHOLDS=$(jq '[.thresholds[] | {key: .name, value: (.value | tonumber? // 0)}] | from_entries' <<<"$HTTP_BODY")
  # The RAW published strings too. A money threshold publishes its own scale in its decimals
  # ("1000.00" -> 2), and money must be sent as a fixed-scale decimal string. Deriving the scale
  # from the policy is the difference between following the policy and restating it.
  THRESHOLDS_RAW=$(jq '[.thresholds[] | {key: .name, value: (.value | tostring)}] | from_entries' <<<"$HTTP_BODY")
  local version
  version=$(jget '.policyVersion')
  info "Policy ${version} — $(jq 'length' <<<"$THRESHOLDS") thresholds resolved live"
}

# money_from_threshold <thresholdName> <delta> — the live threshold plus delta, rendered as a
# fixed-scale decimal STRING at the scale the policy publishes.
#
# Money is a decimal string on this wire, never an ES6 double: Canonicalizer rejects a JSON
# float in a money position outright (payload_not_canonicalizable), so a number here is refused
# before it reaches authority-service at all.
money_from_threshold() {
  local name="$1" delta="${2:-0}" raw scale=0 frac
  raw=$(jq -r --arg n "$name" '.[$n] // empty' <<<"$THRESHOLDS_RAW")
  [[ -n "$raw" ]] || die "The authority policy publishes no threshold named '${name}'."
  if [[ "$raw" == *.* ]]; then frac="${raw#*.}"; scale="${#frac}"; fi
  # LC_ALL=C so a comma decimal separator cannot be emitted into a JSON money field.
  LC_ALL=C printf '%.*f' "$scale" "$(jq -n --argjson a "$raw" --argjson d "$delta" '$a + $d')"
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
# propose path — drive it, do not predict it
#
# The copilot task queue renders approvals, and the only honest probe of "can an approval be
# created" is TO CREATE ONE. So this drives the real path a banker drives: log in, open a
# copilot session, start a run against a real action on a real seeded account, and read the
# trace back.
#
# It used to inspect the RAW upstream response shape and predict a refusal from a config file.
# That prediction outlived the defect — the declared evidenceProjection now reshapes both reads
# INSIDE the executor, so the raw shape has not needed to satisfy EvidenceComplete since
# 0e19c15 — and the probe went on naming a gate that was open, refused to seed, and handed an
# operator a false blocker. A guard that shouts about the wrong thing is the same defect class
# as the fake success it exists to prevent: a signal that is not specific to what failed.
#
# Success is the POSITIVE frame `approval.required`. Not the absence of an error, and not the
# terminal status field: a run that dies before emitting anything has no errors either.
#
# SIDE EFFECT, stated rather than discovered: a successful probe creates a REAL approval. That
# is the point — it is the first genuine card in the queue. `demo:show` therefore does not probe
# unless asked (--probe), because a verb named "show" must not write.
# =============================================================================================

# Results of the last probe, one line per observation: "<label>\t<verdict>\t<detail>"
PROBE_RESULTS=""
PROBE_VERDICT="unknown"   # open | gate-a | gate-b | refused | unknown
PROBE_RUN_ID=""
PROBE_APPROVAL_ID=""

probe_record() { PROBE_RESULTS+="${1}"$'\t'"${2}"$'\t'"${3}"$'\n'; }

# Classify a failed read by the status the upstream actually returned. `tool.failed` carries
# "<code>: <toolId>: upstream returned <status>", so the status is a FACT from this run rather
# than a guess about which endpoint the acting role can reach.
probe_gate_for_status() {
  case "$1" in
    401|403|404) echo "gate-a" ;;
    *)           echo "refused" ;;
  esac
}

probe_propose_path() {
  PROBE_RESULTS=""
  PROBE_VERDICT="unknown"
  PROBE_RUN_ID=""
  PROBE_APPROVAL_ID=""

  local action reader token objective
  action=$(jget_from   "$DATASET" '.proposePathProbe.actionId')
  reader=$(jget_from   "$DATASET" '.proposePathProbe.readAs')
  objective=$(jget_from "$DATASET" '.proposePathProbe.objective')
  token="${TOKENS[$reader]:-}"
  if [[ -z "$token" ]]; then
    probe_record "login" "unknown" "no token for the acting '${reader}' — the run cannot be driven"
    return 0
  fi

  load_thresholds

  # The money value, live from the policy and rendered at the policy's own scale.
  local t_name t_delta amount
  t_name=$(jget_from "$DATASET" '.proposePathProbe.amount["@threshold"]')
  t_delta=$(jq -r '.proposePathProbe.amount["@delta"] // 0' <<<"$DATASET")
  amount=$(money_from_threshold "$t_name" "$t_delta")
  REFS=$(jq --arg k probeAmount --arg v "$amount" '.[$k] = $v' <<<"$REFS")

  local payload
  if ! payload=$(resolve_placeholders "$(jq -c '.proposePathProbe.payload' <<<"$DATASET")" \
                   "$THRESHOLDS" "$REFS" 2>/dev/null); then
    probe_record "payload" "unknown" \
      "the probe payload has an unresolved reference — no seeded account for it to act on"
    return 0
  fi

  # ---- 1. open a session -------------------------------------------------------------------
  http POST /api/copilot/sessions "$(jq -n --arg o "$objective" '{objective: $o}')" "$token"
  if ! status_in "$HTTP_STATUS" 200 201; then
    probe_record "copilot session" "$(probe_gate_for_status "$HTTP_STATUS")" \
      "POST /api/copilot/sessions -> HTTP ${HTTP_STATUS} for '${reader}': ${HTTP_BODY}"
    PROBE_VERDICT="$(probe_gate_for_status "$HTTP_STATUS")"
    return 0
  fi
  local sid
  sid=$(jget '.sessionId')
  if [[ -z "$sid" ]]; then
    probe_record "copilot session" "unknown" \
      "POST /api/copilot/sessions returned ${HTTP_STATUS} but no sessionId"
    return 0
  fi
  probe_record "copilot session" "ok" "${sid} — objective accepted"

  # ---- 2. start the run --------------------------------------------------------------------
  local run_body
  run_body=$(jq -n --arg a "$action" --argjson p "$payload" '{actionId: $a, payload: $p}')
  http POST "/api/copilot/sessions/${sid}/runs" "$run_body" "$token"
  if ! status_in "$HTTP_STATUS" 200 201 202; then
    probe_record "run start" "$(probe_gate_for_status "$HTTP_STATUS")" \
      "POST /api/copilot/sessions/{id}/runs -> HTTP ${HTTP_STATUS}: ${HTTP_BODY}"
    PROBE_VERDICT="$(probe_gate_for_status "$HTTP_STATUS")"
    return 0
  fi
  local rid
  rid=$(jget '.runId')
  if [[ -z "$rid" ]]; then
    probe_record "run start" "unknown" "the run was accepted (${HTTP_STATUS}) but reported no runId"
    return 0
  fi
  PROBE_RUN_ID="$rid"
  probe_record "run start" "ok" "${rid} — ${action}, amount ${amount} (>= ${t_name})"

  # ---- 3. read the trace back until it terminates ------------------------------------------
  local timeout interval waited=0 frames='[]' terminal=""
  timeout=$(jget_from "$DATASET" '.proposePathProbe.runTimeoutSeconds')
  interval=$(jget_from "$DATASET" '.proposePathProbe.pollIntervalSeconds')
  local success_frame
  success_frame=$(jget_from "$DATASET" '.proposePathProbe.successFrame')

  while (( waited <= timeout )); do
    http GET "/api/copilot/runs/${rid}/trace" "" "$token"
    if [[ "$HTTP_STATUS" == "200" ]]; then
      frames=$(jq '.frames // []' <<<"$HTTP_BODY")
      # Classify on the positive frames, never on the run's status field.
      if jq -e --arg k "$success_frame" 'any(.[]; .kind == $k)' >/dev/null <<<"$frames"; then
        terminal="success"; break
      fi
      if jq -e 'any(.[]; .kind == "run.done")' >/dev/null <<<"$frames"; then
        terminal="done"; break
      fi
    fi
    detail "waiting for run ${rid} to finish (${waited}s/${timeout}s)"
    sleep "$interval"
    waited=$((waited + interval))
  done

  # ---- 4. report what the run actually did --------------------------------------------------
  local line
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    probe_record "$(cut -f1 <<<"$line")" "$(cut -f2 <<<"$line")" "$(cut -f3- <<<"$line")"
  done < <(probe_tool_lines "$frames")

  if [[ "$terminal" == "success" ]]; then
    PROBE_APPROVAL_ID=$(jq -r --arg k "$success_frame" \
      'map(select(.kind == $k)) | .[0].payload.approval.id // empty' <<<"$frames")
    local rung
    rung=$(jq -r --arg k "$success_frame" \
      'map(select(.kind == $k)) | .[0].payload.requiredRung // "?"' <<<"$frames")
    probe_record "$success_frame" "ok" \
      "approval ${PROBE_APPROVAL_ID:-<unnamed>} required at ${rung} — the path is open"
    PROBE_VERDICT="open"
    return 0
  fi

  # No success frame. Report the REFUSAL the environment produced, which is a better diagnostic
  # than any prediction: it is the real reason, from this run, named by the service that made it.
  local errors read_failed="no"
  errors=$(jq -c '[.[] | select(.kind == "run.error") | .payload]' <<<"$frames")
  jq -e 'any(.[]; .kind == "tool.failed")' >/dev/null <<<"$frames" && read_failed="yes"

  if [[ "$(jq 'length' <<<"$errors")" -gt 0 ]]; then
    local code message worst=""
    while IFS=$'\t' read -r code message; do
      [[ -n "$code" ]] || continue
      local verdict="refused"
      # GATE B means the reads WORKED and the evidence contract still refused the proposal. If a
      # read failed, every error after it is a CONSEQUENCE, and naming a consequence as the cause
      # is the whole defect this probe was rewritten to stop committing. Such a line keeps its own
      # code and says nothing it has not observed.
      [[ "$read_failed" == "no" && "$code" == "evidence_incomplete" ]] && verdict="gate-b"
      probe_record "run.error" "$verdict" "${code}: ${message}"
      [[ -z "$worst" ]] && worst="$verdict"
    done < <(jq -r '.[] | [(.code // "?"), (.message // "")] | @tsv' <<<"$errors")

    # A read refused upstream outranks whatever the propose step then said about it: the propose
    # could not have succeeded without the evidence that read never returned.
    if [[ "$read_failed" == "yes" ]]; then
      PROBE_VERDICT="gate-a"
    else
      PROBE_VERDICT="${worst:-refused}"
    fi
    return 0
  fi

  if [[ -z "$terminal" ]]; then
    probe_record "run ${rid}" "unknown" \
      "no terminal frame within ${timeout}s. The run neither produced an approval nor said why."
  else
    probe_record "run ${rid}" "unknown" \
      "the run finished without emitting ${success_frame} and without a run.error frame. \
There is no recorded reason, which is itself the finding."
  fi
  return 0
}

# One line per tool the run actually attempted, read out of the trace. `tool.failed` carries the
# upstream status, which is the real refusal rather than a prediction of one.
probe_tool_lines() {
  jq -r '
    (map(select(.kind == "tool.started")) | map({key: .payload.toolCallId, value: .payload.name}) | from_entries) as $names
    | map(select(.kind == "tool.completed" or .kind == "tool.failed"))
    | .[]
    | ($names[.payload.toolCallId] // .payload.toolCallId // "tool") as $tool
    | if .kind == "tool.completed"
      then [$tool, "ok", ("read ok — " + ((.payload.resultSummary // "no summary") | tostring))]
      else [$tool, "gate-a", ((.payload.error // "failed") | tostring)]
      end
    | @tsv' <<<"$1"
}

report_propose_path() {
  header "Propose path — can an approval be created at all?"
  local action
  action=$(jget_from "$DATASET" '.proposePathProbe.actionId')
  detail "drove ${action} as '$(jget_from "$DATASET" '.proposePathProbe.readAs')' through a real copilot run"

  local label verdict note
  while IFS=$'\t' read -r label verdict note; do
    [[ -n "$label" ]] || continue
    case "$verdict" in
      ok)      success "${label}: ${note}" ;;
      gate-a)  fail_line "${label}: ${note}  [GATE A — authorization]" ;;
      gate-b)  fail_line "${label}: ${note}  [GATE B — evidence contract]" ;;
      refused) fail_line "${label}: ${note}  [REFUSED — see the code above]" ;;
      *)       warn "${label}: ${note}" ;;
    esac
  done <<<"$PROBE_RESULTS"

  echo
  case "$PROBE_VERDICT" in
    open)
      success "The propose path is OPEN — this probe just drove it end to end and an approval exists."
      [[ -n "$PROBE_RUN_ID" ]] && detail "run ${PROBE_RUN_ID}, approval ${PROBE_APPROVAL_ID:-<unnamed>}"
      ;;
    gate-a)
      warn "BLOCKED at GATE A — a read the run needed was refused upstream (see the status above)."
      warn "The propose could not have succeeded without evidence the read never returned, so NO"
      warn "approval can be created and the copilot task queue will be EMPTY. That is the"
      warn "environment telling you the truth, not a seeding failure."
      ;;
    gate-b)
      warn "BLOCKED at GATE B — the reads succeeded and authority-service still refused the"
      warn "proposal on evidence. The code and message above are the real refusal, from this run."
      warn "No approval can exist, so the copilot task queue will be EMPTY."
      ;;
    refused)
      warn "The run was REFUSED — and it said why. The run.error code above is the reason the"
      warn "service gave, not a prediction: fix that, then re-run demo:seed."
      ;;
    *)
      warn "Propose-path health UNKNOWN — see the note above. Approvals will not be attempted."
      warn "An unknown verdict is NOT a pass: nothing here observed an approval being created."
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
    warn "Not seeding approvals. The probe run above did not reach '$(jget_from "$DATASET" '.proposePathProbe.successFrame')',"
    warn "and the only honest way to create an approval is to drive the real path."
    echo >&2
    warn "  UNBLOCK WHEN: $(jget_from "$DATASET" '._proposePathDeferral.unblockWhen')"
    echo >&2
    warn "$(jget_from "$DATASET" '._proposePathDeferral.whyNotSimulated')"
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

  # The only honest probe of the propose path CREATES an approval. A verb named `show` must not
  # write, so it is opt-in — and its absence is reported as an absence, never as a pass.
  if [[ "$DO_PROBE" != "true" ]]; then
    header "Propose path — not probed"
    warn "This run did not check whether an approval can be created, because the only honest"
    warn "check is to create one and 'show' does not write. Nothing above is evidence that the"
    warn "propose path is open."
    warn "Run 'demo:show -- --probe' (or demo:seed) to drive a real run and find out."
    return 0
  fi

  probe_propose_path
  report_propose_path
  [[ "$PROBE_VERDICT" == "open" ]] || return 3
}

# show must not write, so it cannot rely on seed_accounts having run. Re-derive the evidence
# account by matching the dataset's declared subject against what the owner can actually see.
discover_evidence_account() {
  # Matching on accountType alone is only unambiguous because no owner holds two accounts of
  # the same type. That is not a hope: tests/demo/test-demo-dataset.sh fails the dataset if it
  # ever stops being true, because otherwise "which account" would depend on server ordering.
  local owner atype
  owner=$(jq -r '[.accounts[] | select(.evidenceSubject == true)][0].owner // empty' <<<"$DATASET")
  atype=$(jq -r '[.accounts[] | select(.evidenceSubject == true)][0].accountType // empty' <<<"$DATASET")
  [[ -n "$owner" && -n "${TOKENS[$owner]:-}" ]] || return 0

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
    local n_accounts=0 n_tx=0 accounts_body='[]' my_tx='[]'
    if [[ "$HTTP_STATUS" == "200" ]]; then
      accounts_body="$HTTP_BODY"
      n_accounts=$(jq 'length' <<<"$accounts_body")
      # One userId-scoped read per owner. Counted per account by filtering the owner's own rows,
      # NOT by counting the whole /my body against each account — that would report the owner's
      # full row count once per account and silently inflate the total.
      http GET /api/transactions/my "" "${TOKENS[$owner]}"
      [[ "$HTTP_STATUS" == "200" ]] && my_tx="$HTTP_BODY"
      local aid
      while read -r aid; do
        [[ -n "$aid" ]] || continue
        n_tx=$((n_tx + $(count_records "$(transactions_on_account "$my_tx" "$aid")")))
      done < <(jq -r '.[] | (.id // .Id)' <<<"$accounts_body")
    fi
    # "owner's transaction(s)", not "transaction(s)": this counts the OWNER's rows on each account,
    # which under single ownership is the account's ledger. Ruling §E5 — a verify pass that changes
    # what it counts without saying so is the worst possible place for an unlabelled meaning change.
    printf '  %-16s %s account(s), %s owner'"'"'s transaction(s)\n' "$owner" "$n_accounts" "$n_tx"
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
