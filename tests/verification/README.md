# Check 4.2 — supervisor agreement measurement harness

**Status: BLOCKED. Check 4.2 is UNMEASURED, not passed.**

This directory holds a runnable harness and case corpus for the one question check 4.2 exists to
answer: *when a real model gives the blind second opinion on an L2 banking action, is disagreement
with the primary genuinely reachable?*

It cannot currently be answered end to end. Two independent server-side gaps stop every copilot run
before the fan-out. Both are described below, with the live run ids that prove them. The harness is
committed so that the measurement can be re-run the moment they are fixed, rather than rebuilt.

---

## What is blocking the measurement

The fan-out fires only when a proposal is admitted with `requiredRung == "L2"`
(`app/planner/loop.py:228-237`). A run must clear **both** gates below to get there. No action
clears both. Four of six do not clear either.

### Gate A — read tools pointing at admin-only upstreams

The copilot calls upstream services with the **acting banker's** bearer token. Six read tools are
unreachable for that token:

| toolId | upstream | guard |
|---|---|---|
| `list_login_audits` | `/api/admin/login-audits` | `require_admin` |
| `get_scored_transaction` | `/api/admin/scored-transactions/{txId}` | `require_admin` |
| `get_flagged_transaction` | `/api/admin/flagged-transactions/{txId}` | `require_admin` |
| `list_flagged_transactions` | `/api/admin/flagged-transactions` | `require_admin` |
| `get_application_audit` | `/api/account-opening/applications/{id}/audit` | `require_admin` |
| `get_account_application` | `/api/account-opening/applications/{id}` | owner-only for non-admin |

`require_banker` deliberately excludes `admin` ("platform power is not banking authority"), so this
cannot be resolved by handing bankers the admin role.

Proven live: run `run_bc66286148fc465c` — `list_login_audits` → `upstream returned 403` →
`step.failed` → `run.done status=failed`.

### Gate B — the evidence contract does not match what the tools return

`PolicyEvaluator.EvidenceComplete` (authority-service) requires `evidence[toolId]` to be a JSON
**object** carrying the `requiredFields` named in `config/authority-policy.yaml`'s `evidence:` block.
The tools return different shapes:

| evidence key | contract requires | actually returns | satisfiable? |
|---|---|---|---|
| `list_account_transactions` | object w/ `accountId`, `count` | a bare JSON **array** | **no** — an array is never a `JObject` |
| `list_login_audits` | object w/ `userId`, `count` | a bare JSON **array** | **no** |
| `get_application_audit` | object w/ `applicationId`, `events` | a bare JSON **array** | **no** |
| `get_account` | object w/ `accountId`, `balance` | `id`, `balance` — no `accountId` | not as shipped |
| `get_user` | object w/ `userId`, `status` | `id`, `isActive` — neither field | not as shipped |
| `get_transfer` | object w/ `transferId`, `amount` | `id`, `amount` | not as shipped |
| `get_scored_transaction` | object w/ `transactionId`, `riskScore` | both present | **yes** |

**Gate B is independent of Gate A and downstream of it.** Fixing the authorization gap alone
unblocks nothing.

Proven live: run `run_5855e85caad34c12` — `account.balance.adjust` with `direction: credit`
(escalates to L2), using **only** banker-readable tools. Both evidence reads returned **HTTP 200
with real data**. The propose step still failed:

```
tool.completed  get_account                 200, "object with accountNumber, accountType, balance, createdAt"
tool.completed  list_account_transactions   200, "7 record(s)"
run.error       evidence_incomplete: "...incomplete: get_account, list_account_transactions."
```

### Combined: every L2-reachable action is blocked

The fan-out guards on the rung **after** escalation, so the L2 surface is six actions, not two.

| action | reaches L2 by | Gate A | Gate B |
|---|---|---|---|
| `user.unlock` | base rung | **blocked** | **blocked** |
| `transaction.score.override` | base rung | **blocked** | **blocked** |
| `transaction.flag.review` | ≥ $25k, or `confirmed_fraud` | **blocked** | **blocked** |
| `account_opening.application.review` | `rejected`, or high-risk applicant | **blocked** | **blocked** |
| `account.balance.adjust` | `direction: credit`, or ≥ $1,000 | clear | **blocked** |
| `transfer.reverse` | ≥ $10,000, or ≥ 72h old | clear | **blocked** |

---

## What will unblock it

**Shortest path — `account.balance.adjust` needs no authorization change at all.** It already
clears Gate A. It needs only that `get_account` and `list_account_transactions` satisfy the evidence
contract. Either:

- map tool output to the contract in `loop.py` before calling `propose` (a projection step: wrap
  arrays as `{accountId, count, items}`, alias `id` → `accountId`), or
- change `config/authority-policy.yaml`'s `evidence:` block to the shapes the tools actually return,
  and make `EvidenceComplete` accept arrays.

Whichever is chosen, **add a test that compares the tool manifest's response shapes against the
evidence contract.** Neither side of that seam is tested today, which is how two individually
reviewed config files ended up mutually unsatisfiable.

---

## Preconditions for a valid 4.2 measurement

1. **Action.** `account.balance.adjust` with `direction: credit` — it escalates to L2 by rule and is
   the only action free of Gate A. Add `transfer.reverse` as a second shape once transfers exist.
2. **Evidence reachable.** `get_account` and `list_account_transactions` must return HTTP 200 *and*
   satisfy `EvidenceComplete`. Confirm by observing an `approval.required` frame with
   `requiredRung: "L2"` followed by a `subagent.spawned` frame — not by the absence of errors.
3. **Seed data.** Accounts must be owned by the **acting banker**; `get_account` is ownership-scoped
   and 404s otherwise. Minimum one account with transaction history; for a real corpus, ~6 accounts
   with deliberately different histories (clean/routine, near-threshold structuring, empty, closed).
4. **Sample size ≥ 30.** At a true 10% disagreement rate, ~29 runs give ~95% confidence of seeing at
   least one disagreement; at 5%, ~59. Below 30 the measurement cannot distinguish "rare" from
   "never", which is the entire question.
5. **Both polarities in the corpus.** Roughly half the cases genuinely defensible. A corpus of only
   hostile cases cannot detect a supervisor that withholds on everything — the same review theatre
   as one that approves everything, and the failure mode actually observed here.
6. **Byte-identical repeats.** Verdicts flip on identical input (observed: 3 hold / 2 proceed on the
   same bytes). A rate quoted without a stability probe implies a determinism that is not there.
7. **Three outcome categories, never two.** `FoundryDecider` fails **closed**: timeouts, throttling,
   content-filter refusals and unparseable output all return `hold` / `confidence 0.0` /
   `keyFactors == ("supervisor_unavailable",)`. **That is a failed model call, not a disagreement.**
   Counting it as one manufactures the same false signal the scripted decider produced, sign
   flipped. `classify()` in the probe checks the marker *and* the zero confidence before comparing.
8. **`0/30 agreed` and `30/30 agreed` are both findings, not passes.** Report the three buckets
   separately, the per-polarity breakdown, and the sample size.

---

## Files

| file | what it is |
|---|---|
| `supervisor_agreement_probe.py` | The runner. Refuses to run unless `supervisor_mode() == "foundry"`. |
| `supervisor_cases.py` | 34-case corpus across all six L2-reachable action shapes, half built to be defensible and half to be stopped, with each case's expected direction recorded up front. |
| `component-probe-results-2026-09-08.jsonl` | Component-level results — see the warning below. |
| `component-probe-stability-2026-09-08.jsonl` | Byte-identical repeats, same warning. |

## ⚠️ About the committed result files — these are NOT a check 4.2 result

Because the end-to-end path is closed, the probe calls `FoundryDecider` **directly**, in-pod, with
pre-built evidence. That exercises the real deployed model, credentials, prompt, parse path and
fail-closed behaviour — but it **stubs the fan-out seam entirely**: no `ToolEvidenceReader`, no
`build_supervisor_input` from a real request, no approval, no agreement computed by the production
comparison.

So the numbers in those files answer a narrower question — *can this model, on this prompt, produce
a reasoned disagreement at all?* — and they do: 27 of 34 verdicts were disagreements, 0 were failed
model calls, and all 34 counter-arguments were distinct. **They do not answer check 4.2**, which is
about the co-signature working end to end, and they must never be quoted as an agreement rate for
it. The real rate is unknown and will differ, because the real path feeds the supervisor evidence it
gathered itself.

## Running it (once unblocked)

Prefer the end-to-end path via `POST /api/copilot/sessions/{id}/runs` and read
`payload.approval.agentAssessment.supervisor` out of the `approval.updated` trace frame. Use the
in-pod component probe only as a fallback, and say so if you do.

`kubectl cp` does not work against this image — there is no `tar`. Use base64 over `exec -i`:

```bash
POD=$(kubectl -n banking-demo get pods -l app=banker-copilot-service -o jsonpath='{.items[0].metadata.name}')
for f in supervisor_cases.py supervisor_agreement_probe.py; do
  base64 -w0 "$f" | kubectl -n banking-demo exec -i $POD -c banker-copilot-service -- \
    env DST=/tmp/verification/$f python -c 'import base64,sys,os,pathlib;d=os.environ["DST"];pathlib.Path(os.path.dirname(d)).mkdir(parents=True,exist_ok=True);open(d,"wb").write(base64.b64decode(sys.stdin.read()))'
done
kubectl -n banking-demo exec $POD -c banker-copilot-service -- \
  python /tmp/verification/supervisor_agreement_probe.py --out /tmp/results.jsonl
```

**Note on detecting whether the decider ran:** `FoundryDecider` logs `"Supervisor second opinion"` on
every call, but a process started with `kubectl exec` writes to its own stdout, **not** the
container's log stream. Absence of that line in `kubectl logs` proves the *service* never invoked
the decider; it does not prove no decider call happened on the pod.

`kubectl exec` mutates nothing. `kubectl apply`, `rollout restart` and `scale` are out of bounds for
a measurement, and `kubectl apply -k deploy/kustomize/base` is a placeholder template that would
damage the cluster.
