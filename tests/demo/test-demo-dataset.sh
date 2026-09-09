#!/usr/bin/env bash
# test-demo-dataset.sh — static guards for the demo dataset (issue #356).
#
# Runs without an environment: no cluster, no compose, no Azure. Everything it asserts is a
# CROSS-FILE agreement, and every expected value is parsed OUT of the file that owns it rather
# than restated here. That is the whole point — a test that repeats the enum it is checking
# passes happily while the two real files drift apart.
#
# Sources of truth consulted:
#   config/authority-policy.yaml                     action types, thresholds, escalators, evidence
#   src/shared/Contracts/Dtos/CreateAccountRequest.cs     the AccountType regex
#   src/shared/Contracts/Dtos/CreateTransactionRequest.cs the Type regex
#   src/ui-app/src/components/copilot/TaskQueuePane.tsx   the queue's status buckets

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

DATASET="${DEMO_DATASET_FILE:-config/demo-dataset.json}"
POLICY="config/authority-policy.yaml"

PASS=0
FAIL=0

ok()   { echo "  ok   — $*"; PASS=$((PASS + 1)); }
bad()  { echo "  FAIL — $*"; FAIL=$((FAIL + 1)); }
group(){ echo; echo "$*"; }

# check <description> <command...>
check() {
  local description="$1"; shift
  local output
  if output=$("$@" 2>&1); then
    ok "$description"
    [[ -n "$output" ]] && echo "$output" | sed 's/^/         /'
  else
    bad "$description"
    [[ -n "$output" ]] && echo "$output" | sed 's/^/         /'
  fi
}

group "Files and syntax"
check "dataset is valid JSON"            bash -c "jq -e . \"\$0\" >/dev/null" "$DATASET"
check "demo.sh parses"                   bash -n scripts/demo/demo.sh
check "demo-lib.sh parses"               bash -n scripts/demo/demo-lib.sh
check "seed-data.sh parses"              bash -n scripts/seed-data.sh

group "No baked-in endpoints"
# A literal host or IP in the scripts is exactly what the charter forbids: endpoints come from
# config or the environment. The dataset file may hold the local compose default; the scripts
# may not hold anything.
if grep -nE '(https?://[A-Za-z0-9.-]|[0-9]{1,3}(\.[0-9]{1,3}){3})' scripts/demo/demo.sh scripts/demo/demo-lib.sh \
   | grep -v '^\S*: *#' >/dev/null 2>&1; then
  bad "scripts/demo/*.sh contain a literal URL or IP address"
  grep -nE '(https?://[A-Za-z0-9.-]|[0-9]{1,3}(\.[0-9]{1,3}){3})' scripts/demo/demo.sh scripts/demo/demo-lib.sh | sed 's/^/         /'
else
  ok "scripts/demo/*.sh contain no literal URL or IP address"
fi

group "Empty-ledger entitlement and PascalCase tolerance"
# Two guards for docs/design/empty-ledger-narrowing-ruling.md, both protecting failures that
# would otherwise PASS silently.
#
# 1. GET /api/transactions/account/{id} derives a non-privileged caller's entitlement from the rows
#    it returns, so an owner reading their own EMPTY ledger gets 403. The seeder must not call it.
# 2. A bare `.accountId` against a PascalCase body matches zero rows. The idempotency pre-check
#    would then report "not yet posted" on every run and every reseed would double-post every
#    transaction — silent data corruption. Every accountId read must be `(.accountId // .AccountId)`.

if grep -nE '/api/transactions/account/' scripts/demo/demo.sh scripts/demo/demo-lib.sh \
   | grep -vE '^[^:]+:[0-9]+: *#' >/dev/null 2>&1; then
  bad "demo scripts call the account-scoped transactions route (403 on an empty ledger — use /api/transactions/my)"
  grep -nE '/api/transactions/account/' scripts/demo/demo.sh scripts/demo/demo-lib.sh \
    | grep -vE '^[^:]+:[0-9]+: *#' | sed 's/^/         /'
else
  ok "demo scripts read transactions via /api/transactions/my, never the account-scoped route"
fi

# Remove every correctly-paired form first; anything left in the helper is a casing-fragile read.
# Scoped to the helper deliberately: it is the ONLY place demo.sh reads accountId off a
# transaction-service body. The bare .accountId reads elsewhere in demo.sh are against
# ai-service's /api/admin/* responses — FastAPI, camelCase only, a different contract.
helper=$(sed -n '/^transactions_on_account() {/,/^}/p' scripts/demo/demo.sh)
if [[ -z "$helper" ]]; then
  bad "transactions_on_account() is missing from demo.sh — the account filter has no guarded home"
elif grep -q '(\.accountId // \.AccountId)' <<<"$helper"; then
  ok "transactions_on_account() filters PascalCase-tolerantly — (.accountId // .AccountId)"
else
  bad "transactions_on_account() uses a bare .accountId — it matches nothing against a PascalCase body and makes every reseed double-post"
  sed 's/^/         /' <<<"$helper"
fi

# Behavioural, not textual: a grep dies on reformatting, this does not. Feed the real helper both
# serializations and require it to find the row either way.
check "transactions_on_account() finds the row in camelCase AND PascalCase bodies" \
  bash -c '
    set -uo pipefail
    eval "$(sed -n "/^transactions_on_account() {/,/^}/p" scripts/demo/demo.sh)"
    camel="[{\"accountId\":\"A1\",\"description\":\"x\"},{\"accountId\":\"A2\"}]"
    pascal="[{\"AccountId\":\"A1\",\"Description\":\"x\"},{\"AccountId\":\"A2\"}]"
    for body in "$camel" "$pascal"; do
      n=$(transactions_on_account "$body" A1 | jq "length")
      [[ "$n" == 1 ]] || { echo "expected 1 row, got ${n} from: ${body}"; exit 1; }
    done
    # An empty ledger and a non-JSON (curl error) body must both degrade to [], not to a crash.
    [[ "$(transactions_on_account "[]" A1)" == "[]" ]] || { echo "empty body did not yield []"; exit 1; }
    [[ "$(transactions_on_account "curl: (7) refused" A1)" == "[]" ]] || { echo "non-JSON body did not yield []"; exit 1; }
  '

# The verify pass counts the OWNER's rows on each account, not the account's ledger (ruling §E5).
# The printed label must say so.
if grep -qE "owner'\"'\"'s transaction\(s\)|owner's transaction\(s\)" scripts/demo/demo.sh; then
  ok "the verify pass labels its per-account count as the owner's transactions"
else
  bad "the verify pass prints an unlabelled transaction count — it counts the owner's rows and must say so (ruling §E5)"
fi

group "Cross-file agreement"
python3 - "$DATASET" "$POLICY" <<'PY'
import json, re, sys, pathlib

dataset_path, policy_path = sys.argv[1], sys.argv[2]
import yaml

dataset = json.loads(pathlib.Path(dataset_path).read_text())
policy  = yaml.safe_load(pathlib.Path(policy_path).read_text())

failures = []
passes   = []
thresholds_all = policy["thresholds"]

def assert_(condition, message):
    (passes if condition else failures).append(message)

# ---- Identities -------------------------------------------------------------------------
first = [i for i in dataset["identities"] if i.get("registerFirst")]
assert_(len(first) == 1,
        "exactly one identity is registered first (the first-user-becomes-admin rule needs a target)")
assert_(bool(first) and first[0]["role"] == "admin",
        "the first-registered identity is the admin identity")

usernames = {i["username"] for i in dataset["identities"]}
assert_(len(usernames) == len(dataset["identities"]), "identity usernames are unique")

username_re = re.compile(r"^[a-zA-Z0-9_.-]+$")   # RegisterUserRequest.Username
assert_(all(username_re.match(u) and 3 <= len(u) <= 50 for u in usernames),
        "every username satisfies the server-side username rule")

retail = {i["username"] for i in dataset["identities"] if i.get("retail")}
assert_(len([i for i in dataset["identities"] if i.get("locked")]) >= 1,
        "at least one identity is locked, so user.unlock has a real subject")
assert_(len([i for i in dataset["identities"] if i["role"] == "banker"]) >= 1,
        "at least one banker exists")
assert_(len([i for i in dataset["identities"] if i["role"] == "supervisor"]) >= 1,
        "at least one supervisor exists, or no L2 approval can ever be co-signed")

# ---- Account / transaction enums, parsed out of the C# DTOs -------------------------------
def regex_from(path, prop):
    text = pathlib.Path(path).read_text()
    # The [RegularExpression("...")] immediately preceding the named property.
    block = text.split(f"public string{'?' if False else ''} {prop}")[0]
    found = re.findall(r'RegularExpression\("([^"]+)"', block)
    return found[-1] if found else None

acct_re = regex_from("src/shared/Contracts/Dtos/CreateAccountRequest.cs", "AccountType")
assert_(acct_re is not None, "AccountType regex was found in CreateAccountRequest.cs")
if acct_re:
    compiled = re.compile(acct_re)
    bad_types = sorted({a["accountType"] for a in dataset["accounts"] if not compiled.match(a["accountType"])})
    assert_(not bad_types,
            f"every accountType satisfies the server regex {acct_re} (offenders: {bad_types})")

tx_re = regex_from("src/shared/Contracts/Dtos/CreateTransactionRequest.cs", "Type")
assert_(tx_re is not None, "transaction Type regex was found in CreateTransactionRequest.cs")
if tx_re:
    compiled = re.compile(tx_re)
    bad_types = sorted({t["type"] for t in dataset["transactions"] if not compiled.match(t["type"])})
    assert_(not bad_types,
            f"every transaction type satisfies the server regex {tx_re} (offenders: {bad_types})")

assert_(all(-1_000_000 < t["amount"] < 1_000_000 and t["amount"] != 0 for t in dataset["transactions"]),
        "every transaction amount is inside the server's accepted range and non-zero")

declared = {i["username"] for i in dataset["identities"]}
owners = {a["owner"] for a in dataset["accounts"]} | {t["owner"] for t in dataset["transactions"]}
assert_(owners <= declared,
        f"every account/transaction owner is a declared identity (stray: {sorted(owners - declared)})")

for t in dataset["transactions"]:
    n = len([a for a in dataset["accounts"] if a["owner"] == t["owner"]])
    assert_(t["accountIndex"] < n,
            f"transaction '{t['description']}' targets an account index that exists for {t['owner']}")

descriptions = [(t["owner"], t["description"]) for t in dataset["transactions"]]
assert_(len(descriptions) == len(set(descriptions)),
        "transaction descriptions are unique per owner — the seeder uses them as its idempotence key")

# ---- Ownership: the customers hold the money, the banker holds none -----------------------
# docs/design/banker-customer-read-ruling.md §B5.7-8. The banker-owned accounts existed only
# because GetAccountTransactions filtered by the CALLER's userId, so a banker reading someone
# else's account got `200 []` — a success asserting a falsehood. The data was shaped so the
# defect would not show. Danny required the shape be GONE, not merely unused, "so nothing can
# quietly fall back", so this asserts absence rather than disuse.
bankers     = {i["username"] for i in dataset["identities"] if i["role"] == "banker"}
supervisors = {i["username"] for i in dataset["identities"] if i["role"] == "supervisor"}
staff       = bankers | supervisors | {i["username"] for i in dataset["identities"] if i["role"] == "admin"}

staff_accounts = sorted({a["owner"] for a in dataset["accounts"] if a["owner"] in staff})
assert_(not staff_accounts,
        "no account is owned by a banker, supervisor or admin — the banker works the CUSTOMER's "
        f"case, and the old shape is absent rather than unused (stray owners: {staff_accounts})")
staff_tx = sorted({t["owner"] for t in dataset["transactions"] if t["owner"] in staff})
assert_(not staff_tx,
        f"no transaction is owned by staff either (stray owners: {staff_tx})")

subjects = [a for a in dataset["accounts"] if a.get("evidenceSubject") or a.get("evidenceSubjectAlt")]
assert_(len(subjects) >= 1, "at least one account is marked as an evidence subject")
assert_(all(a["owner"] not in staff for a in subjects),
        "every evidence-subject account is owned by a CUSTOMER — the demo is a banker adjusting "
        "a customer's account, not their own")
assert_(len([a for a in dataset["accounts"] if a.get("evidenceSubject")]) == 1,
        "exactly one account is the primary evidence subject")

# seed_accounts claims the first unclaimed existing account of a type, and demo:show re-derives
# the evidence subject by type alone. Two accounts of one type under one owner would make "which
# one" depend on server ordering — silently, and differently on every environment.
type_pairs = [(a["owner"], a["accountType"]) for a in dataset["accounts"]]
dupes = sorted({p for p in type_pairs if type_pairs.count(p) > 1})
assert_(not dupes,
        f"no owner holds two accounts of the same type (ambiguous: {dupes})")

# The narrative shapes Livingston measured the supervisor reasoning against. Ownership moved;
# these did not, and a reseed that quietly drops them takes the reasoning with it.
assert_(any(a["initialBalance"] == 0 and not [t for t in dataset["transactions"]
            if t["owner"] == a["owner"]
            and t["accountIndex"] == [x for x in dataset["accounts"] if x["owner"] == a["owner"]].index(a)]
            for a in dataset["accounts"]),
        "one account is deliberately empty — zero balance AND zero transactions")

# ---- The propose-path probe DRIVES the path; it does not predict it ------------------------
probe = dataset["proposePathProbe"]
assert_(probe["actionId"] in policy["actionTypes"],
        f"the propose-path probe targets a real action ('{probe['actionId']}')")
assert_(probe["readAs"] in bankers,
        "the propose-path probe acts as a banker — the identity a copilot run actually acts as")
probe_action = policy["actionTypes"].get(probe["actionId"], {})
assert_(probe_action.get("agentMayPropose") is True and probe_action.get("baseRung") != "L3",
        "the probed action is one the agent may actually propose")
assert_(set(probe["payload"]) >= set(probe_action.get("hashFields", [])),
        "the probe payload covers every hashed field of the action it drives (missing: "
        f"{sorted(set(probe_action.get('hashFields', [])) - set(probe['payload']))})")
assert_(probe.get("successFrame") == "approval.required",
        "success is the POSITIVE frame approval.required, not the absence of an error")

# Money is a fixed-scale decimal STRING on this wire; a JSON number in a money position is
# refused payload_not_canonicalizable. The probe therefore may not carry a bare number, and the
# amount it derives is checked against the policy's own threshold rather than a restated one.
money_fields = set(probe_action.get("moneyFields", []))
for field in money_fields & set(probe["payload"]):
    value = probe["payload"][field]
    assert_(isinstance(value, dict) and ("@ref" in value or "@threshold" in value),
            f"the probe's money field '{field}' is resolved at runtime, never a literal JSON "
            "number — Canonicalizer rejects a float in a money position")

amount_node = probe.get("amount", {})
threshold_name = amount_node.get("@threshold")
assert_(threshold_name in thresholds_all,
        f"the probe amount names a real policy threshold ('{threshold_name}')")
if threshold_name in thresholds_all:
    base = float(thresholds_all[threshold_name]["default"])
    value = base + amount_node.get("@delta", 0)
    assert_(value >= base,
            f"the probe amount stays AT OR ABOVE the dual-control line ({value} >= {base}) so "
            "the run reaches L2 and the supervisor fan-out actually runs")

assert_(all(a["label"] for a in dataset["accounts"]),
        "every account carries a label, so demo:show can say what it is for")

# ---- The probe must drive the real path, and keep saying so --------------------------------
# This is a tamper guard. The previous probe inspected raw response shapes and predicted a
# refusal; the prediction outlived the defect and blocked a real operator on a gate that was
# already open. Driving the path cannot go stale that way, so reverting to shape inspection has
# to fail here rather than quietly pass.
seeder_text = (pathlib.Path(dataset_path).resolve().parent.parent
               / "scripts" / "demo" / "demo.sh").read_text()
for fragment, why in [
    ("/api/copilot/sessions", "opens a real copilot session"),
    ("/runs", "starts a real run"),
    ("/trace", "reads the real trace back"),
    ('.kind == $k', "classifies on the trace's frame kinds"),
    ("run.error", "reports the refusal the service actually gave"),
]:
    assert_(fragment in seeder_text,
            f"the propose-path probe {why} ('{fragment}')")
assert_("approval.required" in seeder_text or probe["successFrame"] in seeder_text,
        "the probe's success condition is the positive approval.required frame")

# ---- Approvals must be PROPOSED, never written ---------------------------------------------
# Writing approval rows straight into the store would populate the task queue while the propose
# path stays dead: failure that looks exactly like success. The seeder must only ever drive the
# public propose/sign/deny API.
seeder = (pathlib.Path(dataset_path).resolve().parent.parent / "scripts" / "demo" / "demo.sh").read_text()
# Comments are allowed to name the data stores — explaining what reset cannot reach is the point.
# Only executable lines are scanned.
code = "\n".join(line for line in seeder.splitlines() if not line.lstrip().startswith("#"))
for forbidden in ("cosmosclient", "az cosmosdb", "mongosh", "kubectl exec", "redis-cli"):
    assert_(forbidden not in code.lower(),
            f"the seeder does not reach past the API to the data store ('{forbidden}')")
assert_("/api/authority/approvals" in seeder,
        "the seeder creates approvals through the public propose API")
assert_("APPROVALS_DEFERRED" in seeder and "PROBE_VERDICT" in seeder,
        "the seeder gates the approvals stage on a live propose-path probe rather than assuming "
        "the path is open")

# ---- Approvals against the authority policy ------------------------------------------------
actions    = policy["actionTypes"]
thresholds = policy["thresholds"]
escalators = {e["id"] for e in policy["escalators"]}
evidence   = policy["evidence"]

def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)

for approval in dataset["approvals"]:
    key = approval["key"]
    action_id = approval["actionId"]

    assert_(action_id in actions, f"{key}: action '{action_id}' exists in the authority policy")
    if action_id not in actions:
        continue
    action = actions[action_id]

    assert_(action.get("agentMayPropose") is True and action["baseRung"] != "L3",
            f"{key}: '{action_id}' is proposable — an L3 action would be refused, leaving no card")

    required = set(action.get("requiredEvidence", []))
    supplied = set(approval["evidence"].keys())
    assert_(required <= supplied,
            f"{key}: supplies every required evidence key (missing: {sorted(required - supplied)})")
    for ev_key in supplied & required:
        want = set(evidence[ev_key]["requiredFields"])
        have = set(approval["evidence"][ev_key].keys())
        assert_(want <= have,
                f"{key}/{ev_key}: supplies every required field (missing: {sorted(want - have)})")

    hash_fields = set(action.get("hashFields", []))
    assert_(hash_fields <= set(approval["payload"].keys()),
            f"{key}: payload covers every hashed field (missing: {sorted(hash_fields - set(approval['payload']))})")

    declared = approval.get("escalator")
    if declared:
        assert_(declared in escalators,
                f"{key}: declared escalator '{declared}' exists in the policy")
        # Escalators use raiseBy, which steps up from the rung the ACTION'S OWN RULES already
        # produced. Demonstrate one on an action that is already L2 and the +1 lands on L3,
        # where the agent may not even propose — the seeder gets a 403 and the card the demo
        # was built around does not exist. So an escalator demo must still be L1 when it fires.
        assert_(action["baseRung"] == "L1",
                f"{key}: an escalator demo starts from baseRung L1 (got {action['baseRung']}); "
                f"raiseBy from L2 lands on L3, which is refused outright")

        def literal(value):
            if isinstance(value, dict) and "@threshold" in value:
                return float(thresholds[value["@threshold"]]["default"]) + value.get("@delta", 0)
            return value

        def fires(rule):
            when = rule["when"]
            actual = literal(approval["payload"].get(when["field"]))
            if actual is None:
                return False
            op = when["op"]
            if op == "eq":
                return actual == when.get("value")
            if op in ("in", "intersects"):
                return actual in when.get("values", [])
            if op in ("gte", "gt", "lte", "lt"):
                try:
                    a_val = abs(float(actual)) if when.get("abs") else float(actual)
                except (TypeError, ValueError):
                    return False
                t_val = float(thresholds[when["threshold"]]["default"])
                return {"gte": a_val >= t_val, "gt": a_val > t_val,
                        "lte": a_val <= t_val, "lt": a_val < t_val}[op]
            return False

        triggered = [r["id"] for r in action.get("rules", []) if fires(r)]
        assert_(not triggered,
                f"{key}: no action-local rule fires on this payload before the escalator does "
                f"(would fire: {triggered}, pushing the result to L3)")

for node in walk(dataset["approvals"]):
    if "@threshold" in node:
        name = node["@threshold"]
        assert_(name in thresholds,
                f"threshold reference '{name}' exists in {policy_path}")
        if name in thresholds:
            base  = float(thresholds[name]["default"])
            value = base + node.get("@delta", 0)
            assert_(value > 0, f"threshold '{name}' + delta stays positive ({value})")
            if name.endswith("_dual_control_amount"):
                assert_(value < base,
                        f"an amount derived from '{name}' stays BELOW the dual-control line "
                        f"({value} < {base}) so the approval demonstrates L1, not L2")

# ---- Lifecycle coverage --------------------------------------------------------------------
afters = {a["after"] for a in dataset["approvals"]}
for verb in ("leave-pending", "sign-slot0", "sign-full", "deny", "supersede"):
    assert_(verb in afters, f"the dataset produces an approval in the '{verb}' state")

l2_cosign = [a for a in dataset["approvals"]
             if a["after"] == "sign-slot0" and actions.get(a["actionId"], {}).get("baseRung") == "L2"]
assert_(bool(l2_cosign),
        "the co-signature story exists: an L2 approval with slot 0 already filled")

# ---- Queue buckets, parsed out of the UI ----------------------------------------------------
pane = pathlib.Path("src/ui-app/src/components/copilot/TaskQueuePane.tsx").read_text()
ui_statuses = set(re.findall(r"status === '([a-z]+)'", pane))
assert_(ui_statuses,
        "the queue pane's status buckets were readable from the UI source")

# Every state the dataset can leave an approval in must land in a bucket the queue renders.
produced = set()
for a in dataset["approvals"]:
    produced |= {
        "leave-pending": {"pending"},
        "sign-slot0":    {"pending"},
        "sign-full":     {"signed"},
        "deny":          {"denied"},
        "supersede":     {"denied", "pending"},
    }[a["after"]]
assert_(produced <= ui_statuses,
        f"every seeded approval state is rendered by the task queue (orphans: {sorted(produced - ui_statuses)})")

for message in passes:
    print(f"  ok   — {message}")
for message in failures:
    print(f"  FAIL — {message}")

sys.exit(1 if failures else 0)
PY

if [[ $? -eq 0 ]]; then
  PASS=$((PASS + 1))
else
  FAIL=$((FAIL + 1))
fi

echo
if [[ $FAIL -gt 0 ]]; then
  echo "FAILED — ${FAIL} check group(s) failed."
  exit 1
fi
echo "PASSED — ${PASS} check group(s)."
