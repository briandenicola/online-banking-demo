# Skill — Driving and measuring an L2 Banker Copilot run end to end

Reusable procedure for anyone who needs to exercise, verify or measure the Phase 3 supervisor
fan-out against a live deployment. Derived from check 4.2, 2026-09-08, branch `332-beta`.

## 1. Get a token that can actually drive the harness

```bash
TOK=$(curl -s -X POST https://onlinebankingdemo.bjdazure.tech/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"banker","password":"..."}' \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("token") or d.get("accessToken"))')
```

`require_banker` gates on the **`effectiveRoles`** claim, not `role`. `supervisor` reaches it
(hierarchy expands supervisor → banker); **`admin` does not** — platform power is deliberately not
banking authority. Decode the token and check `effectiveRoles` before blaming the endpoint.

## 2. The API sequence

```
POST /api/copilot/sessions                      -> { "sessionId": "sess_..." }   # NOT "id"
POST /api/copilot/sessions/{sessionId}/runs     -> 202 { "runId": "run_..." }
GET  /api/copilot/runs/{runId}/trace            -> { "frames": [...] }
```

Run bodies take `{objective, actionId, payload, facts}`. Runs are **async** — poll the trace; a
simple L2 run finishes in about a second, so 20–30s is ample.

Trace frames carry the event name in **`kind`**, not `type`. The supervisor's opinion appears only
in the `approval.updated` frame, at `payload.approval.agentAssessment.supervisor`. It is never
persisted anywhere else — it is evidence for a human, not a signature.

## 3. Find the real L2 surface — do not trust a stated count

The fan-out fires on `requiredRung == "L2"`, the rung **after** escalation. So the L2 surface is
larger than the two actions with `baseRung: L2`:

| action | how it reaches L2 | evidence |
|---|---|---|
| `user.unlock` | base | `get_user`, `list_login_audits` |
| `transaction.score.override` | base | `get_scored_transaction`, `list_account_transactions` |
| `account.balance.adjust` | `direction == credit`, or ≥ $1,000 | `get_account`, `list_account_transactions` |
| `transfer.reverse` | ≥ $10,000, or ≥ 72h old | `get_transfer`, `list_account_transactions` |
| `account_opening.application.review` | `decision == rejected`, or high-risk applicant | `get_account_application`, `get_application_audit` |
| `transaction.flag.review` | ≥ $25,000, or `confirmed_fraud` | `get_flagged_transaction`, `list_account_transactions` |

Re-derive this from `config/authority-policy.yaml` every time — rules change.

## 4. Bind tool arguments by NAME

`ToolEvidenceReader.gather` and the primary both bind arguments by parameter name out of the merged
`session.context` + `payload` + `facts`. `GET /api/copilot/tools` gives the exact names, and they
often differ from the payload's `hashFields` — `transaction.score.override` hashes
`transactionId` but `get_scored_transaction` takes **`txId`**. Put the tool's names in `facts`.

`extract_entity_ids` harvests any key ending in `id` (case-insensitive) with a scalar value.

## 5. Two independent gates stop you before the fan-out (as of 2026-09-08, both open)

**Gate A — unreachable reads.** Six tools point at admin-only or owner-scoped upstreams, and the
copilot calls upstream with the acting *banker's* token: `list_login_audits`,
`get_scored_transaction`, `get_flagged_transaction`, `list_flagged_transactions`,
`get_application_audit` (all `require_admin`), and `get_account_application` (owner-only).
`require_banker` deliberately excludes admin, so granting the role is not the fix. Also note
`get_account` 404s for accounts the token's user does not own — seed test accounts as the *banker*.

**Gate B — the evidence contract does not match the tools.** `PolicyEvaluator.EvidenceComplete`
requires a JSON **object** carrying the `requiredFields` from the policy's `evidence:` block.
`list_account_transactions`, `list_login_audits` and `get_application_audit` return bare **arrays**,
which can never satisfy it under any field-name change; `get_account`/`get_user`/`get_transfer`
return `id`/`isActive` where the contract wants `accountId`/`userId`/`status`/`transferId`.

**Gate B is downstream of and independent of Gate A.** Two of the six L2-reachable actions
(`account.balance.adjust`, `transfer.reverse`) touch no admin endpoint at all and still fail. Prove
this to yourself in one run before accepting any "it's an auth problem" diagnosis: drive
`account.balance.adjust` with `direction: credit` and watch both reads return 200 and the proposal
still come back `evidence_incomplete`.

**Confirm success positively.** The fan-out fired only if you see an `approval.required` frame with
`requiredRung: "L2"` followed by `subagent.spawned`. Absence of errors is not success.

## 6. Measuring the supervisor when the end-to-end path is closed

**This is a fallback, and its output is not an end-to-end agreement rate.** It stubs the whole
fan-out seam. Name the artifacts so the boundary travels with the number (`component-probe-*`), put
the status in the first line of the script's docstring, and have the script print the caveat above
its own summary — a caveat in prose does not survive someone copying a figure out of a terminal.
If the requested measurement is blocked, the deliverable is the blockage and its preconditions, not
a nearby measurement that happens to be reachable.

Run the real decider **inside the pod** — that is where the workload identity, the private-endpoint
route to Foundry and the deployed model actually are. Anything reconstructed outside it measures a
copy.

`kubectl cp` needs `tar`, which the image does not have. Use base64 over stdin:

```bash
POD=$(kubectl -n banking-demo get pods -l app=banker-copilot-service \
      -o jsonpath='{.items[0].metadata.name}')
base64 -w0 probe.py | kubectl -n banking-demo exec -i $POD -c banker-copilot-service -- \
  python -c 'import base64,sys;open("/tmp/probe.py","wb").write(base64.b64decode(sys.stdin.read()))'
kubectl -n banking-demo exec $POD -c banker-copilot-service -- python /tmp/probe.py
```

`kubectl exec` mutates nothing. `kubectl apply`, `rollout restart`, `scale` and
`kubectl apply -k deploy/kustomize/base` (a placeholder template — applying it damages the cluster)
are all out of bounds for a measurement.

## 7. Classify into THREE buckets, never two

`FoundryDecider` fails **closed**. A timeout, a throttle, a content-filter refusal or unparseable
output all return `hold` / `confidence 0.0` / `keyFactors == ("supervisor_unavailable",)`.

**That is a failed model call, not a disagreement.** Counting it as one manufactures the same false
signal the scripted decider used to produce, with the sign flipped. Check the marker *and* the zero
confidence before comparing recommendations:

```python
if "supervisor_unavailable" in opinion.key_factors and opinion.confidence == 0.0:
    return "unavailable"
return "agree" if opinion.recommendation == "proceed" else "disagree"
```

The primary always says `proceed` — it proposed the action. `fanout._primary_recommendation`
defaults to exactly that.

## 8. Corpus design rules

- **≥30 runs.** At a true 10% disagreement rate you need ~29 runs to be ~95% confident of seeing
  one; at 5%, ~59.
- **Both polarities.** Roughly half the cases should be genuinely defensible. A corpus of only
  hostile cases cannot detect a supervisor that withholds on everything — which is the same review
  theatre as one that approves everything.
- **Include byte-identical repeats.** Verdicts flip on identical input. Without a stability probe
  (`--repeat`) a quoted rate implies a determinism that is not there.
- **Count distinct counter-arguments.** Unique-strings-over-sample-size is the cheap, objective
  boilerplate test. A scripted decider scores ~2/34; a reasoning one scores 34/34.
- **Record each case's expected direction before running.** As a prior for interpretation, not as
  an assertion — a corpus that asserts its own answer cannot report a surprise.

## 9. Report the number honestly

`0/30 agreed` and `30/30 agreed` are both findings, not passes. State the sample size, the three
buckets separately, the per-polarity breakdown, and which seam was stubbed.
