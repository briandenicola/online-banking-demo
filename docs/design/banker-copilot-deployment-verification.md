# Banker Copilot — deployment verification checklist

**Status:** nothing in this document has been run. Everything here is a claim the
test suites *cannot* make.

## Why this exists

Phases 1–3 are verified by roughly 1,300 unit and integration tests, and those
tests are genuinely load-bearing — they caught six privilege escalations, a path
traversal, and a fistful of guards that could not fail. But every one of them
runs against stubs. There is no Docker daemon and no Azure subscription in the
development environment, so a specific class of claim has never been checked by
anybody:

- anything that depends on **Cosmos actually returning rows** for a query,
- anything that depends on **a token being accepted by a different service**,
- anything that depends on **bytes surviving a proxy**,
- anything that depends on **a real model choosing a real tool**.

These fail *silently* in the ways this repo has already been bitten by. Cosmos
returns zero rows rather than an error when a field path is wrong. Kubernetes
drops hyphenated ConfigMap keys without complaint. A dead SSE stream can be
byte-for-byte indistinguishable from a clean one.

Each item below is written so it can be executed and produce a yes or a no. The
"a failure here means" column matters more than the command: it says what you
have actually learned, which is usually narrower than it first appears.

## Running the stack

```bash
task build          # images have never been built; expect first-run surprises
docker compose up -d
docker compose ps   # every service healthy before starting
```

Gateway is on **http://localhost:8080**. Services are reachable only through it;
that is deliberate.

Get two tokens, because half this checklist needs two identities:

```bash
BANKER=$(curl -s localhost:8080/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"<banker>","password":"<pw>"}' | jq -r .token)

SUPERVISOR=$(curl -s localhost:8080/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"<supervisor>","password":"<pw>"}' | jq -r .token)
```

---

## 1. The harness cannot write

The single most important property in the epic. It is asserted by unit tests, but
those assert over the in-process registry — not over what the deployed service
exposes.

| # | Check | Command | Pass | A failure here means |
|---|---|---|---|---|
| 1.1 | Harness reports zero write tools | `curl -s localhost:8080/api/copilot/health \| jq '{readTools,writeTools,methods}'` | `writeTools: 0`, `methods: ["GET"]` | The deployed image is not the audited code. Stop and reconcile before anything else. |
| 1.2 | No write verb is routed to the harness | `for m in POST PUT PATCH DELETE; do echo -n "$m "; curl -s -o /dev/null -w '%{http_code}\n' -X $m localhost:8080/api/copilot/tools -H "authorization: Bearer $BANKER"; done` | `405` (or `404`) for all four | A write verb reaching the harness is a bypass of the whole topology. |
| 1.3 | The harness identity cannot reach the executor's write path | From inside the harness container: `docker compose exec banker-copilot-service curl -s -o /dev/null -w '%{http_code}\n' -X POST http://authority-service:8080/approvals/<id>/sign` | `401`/`403` | Network reachability alone is not the control — but if this succeeds, the only thing stopping a write is the harness's own code, which is exactly the assumption the split exists to remove. |

---

## 2. Authority round-trip

Unit-tested end to end in memory; never once against Cosmos.

| # | Check | Pass | A failure here means |
|---|---|---|---|
| 2.1 | `propose_action` creates an approval in `proposed` | Approval id returned; document present in Cosmos | — |
| 2.2 | The JCS payload hash is stable across a service restart | Same hash before and after `docker compose restart authority-service` | Hashing is picking up something process-local. Every signature becomes unverifiable after a deploy. |
| 2.3 | An L1 approval signed by the acting banker executes | `signed` → `executed` | — |
| 2.4 | A tampered payload voids | `denied`, `terminalReason: PAYLOAD_SUPERSEDED`, `supersededByApprovalId` set | — |
| 2.5 | TTL expiry sweeper fires | `denied`, `terminalReason: TTL_EXPIRED` | The sweeper is a `BackgroundService`; it has never run against a real clock and a real store. |
| 2.6 | Policy escalation voids at execution; relaxation honours | Higher rung → void; lower/unchanged → honour, never auto-downgrade | — |

**2.7 — the one most likely to be silently wrong.** Confirm the persisted
document's field paths match what the queries and the composite index expect:

```bash
# The exact document, as stored:
az cosmosdb sql container query ... --query-text "SELECT TOP 1 * FROM c"
```

Compare every path used by a query or index against that output. **Cosmos returns
zero rows, not an error, when a path is wrong** — a supervisor queue that is
simply always empty looks identical to a queue with nothing in it. This has
already bitten this repo once.

---

## 3. Separation of duties, against real tokens

Six privilege escalations were found and fixed here in Phase 1. All of them were
found by reading code and running stubs. None has been retested against a token
actually minted by `user-service` and actually validated by `authority-service`.

| # | Check | Pass | A failure here means |
|---|---|---|---|
| 3.1 | An L2 approval requires two signatures | One signature leaves it `pending` | — |
| 3.2 | The proposer cannot fill both slots | Second signature from the same identity is **rejected** | Separation of duties is theatre and the ladder collapses to L1. **Stop everything.** |
| 3.3 | A retail `user` token cannot fill an L1 banker slot | Rejected | The Phase 1 escalation has regressed. |
| 3.4 | An `admin` token confers no banking authority | Rejected as a signer | `admin` sitting above `supervisor` let one identity fill both L2 slots. |
| 3.5 | `authority-service` fails closed on role-model divergence | Service refuses to start when `role-hierarchy.yaml` diverges | The single-source guarantee is not actually enforced at runtime. |
| 3.6 | A token minted for service A is rejected by service B | `401` | Per-service audience isolation (#334) is not real. |
| 3.7 | An HS256 token is rejected | `401` | The RS256 migration left a symmetric path open — any service could mint a `supervisor` claim. |

---

## 4. Blind construction (Phase 3)

The supervisor agent must not see the proposing agent's reasoning. Tests assert
this structurally over what the supervisor is handed. What tests cannot tell you
is whether a **real model** with a **real context window** leaks it anyway.

| # | Check | Pass | A failure here means |
|---|---|---|---|
| 4.1 | Capture the exact payload sent to the supervisor model | Contains the facts; contains no proposer reasoning, plan, or conclusion | — |
| 4.2 | Supervisor sometimes **disagrees** with the proposer | At least one genuine disagreement across a varied run | **The most important line in this document.** A supervisor that agrees 100% of the time is indistinguishable from a rubber stamp, and it is the failure this design exists to prevent. Agreement rate is the metric to watch; it will look like success. |
| 4.3 | Trace envelope does not carry proposer reasoning into supervisor scope | Inspect persisted `copilot-traces` | Independence leaks through the audit path even if the prompt is clean. |

---

## 5. SSE

Never exercised through nginx. The design deliberately keeps chunked encoding
**on** so that a truncated stream raises a network error instead of looking like
a clean end-of-stream.

```bash
curl -N -H "authorization: Bearer $BANKER" \
  localhost:8080/api/copilot/sessions/<id>/stream
```

| # | Check | Pass | A failure here means |
|---|---|---|---|
| 5.1 | Events arrive incrementally | Events appear as produced, not in one flush at the end | `proxy_buffering off` is not in effect; the trace pane — which *is* the demo — will appear frozen then dump. |
| 5.2 | `Transfer-Encoding: chunked` present | Header present | Without it a dropped connection is indistinguishable from a clean end, the client's reconnect never fires, and a dead stream looks like a working one. |
| 5.3 | Killing the service mid-stream surfaces an **error** | `curl` reports a network error, not a clean EOF | Same as 5.2, observed rather than inferred. |
| 5.4 | Long-idle stream survives | No premature close (`proxy_read_timeout 3600s`) | — |

---

## 6. Audit trail

| # | Check | Pass | A failure here means |
|---|---|---|---|
| 6.1 | Every approval transition publishes to the Redis stream | Events present | — |
| 6.2 | `event-processor` consumes and persists them | Audit rows appear | The Go consumer has only been tested against a stub stream. |
| 6.3 | `InsufficientFundsAttempt` and `UserRegistered` are audited | Present | These were published and never consumed for the entire life of the repo before Phase 1. |
| 6.4 | Traces persist to `copilot-traces` and replay faithfully | Replay reproduces the run | The eval contract shipped with the harness specifically so this would be checkable. |

**Known accepted gap (#337, ruled by Brian):** admin lock/unlock/delete/reset-password
writes through the classic tabs emit **no audit event**. Closed as accepted, not
fixed — the Phase 5 comparison therefore compares an audited surface against a
partially unaudited one. Do not "discover" this Monday and treat it as a bug.

---

## 7. UI, two identities

Phase 3's exit criterion is §1.3 steps 6–7 across **two browser identities** —
banker and supervisor, two sessions by design.

| # | Check | Pass | A failure here means |
|---|---|---|---|
| 7.1 | Banker proposes an L2 action | Card shows the rung and the payload hash | — |
| 7.2 | Supervisor sees it in their queue, in the other session | Appears without a pointer document | Cross-partition query or composite index is wrong — see 2.7. |
| 7.3 | Supervisor co-signs; action executes | `executed` | — |
| 7.4 | Voided-by-policy card does **not** read as a colleague's rejection | Names the policy change; links to the replacement | Requirement O9. A card that blames a banker for a policy edit teaches people to distrust the card — and the card is the one artifact this epic rests on. |
| 7.5 | All four `terminalReason` values render distinguishably | Four visibly different treatments | — |
| 7.6 | Batch approval is offered at L1 and **impossible** at L2 | No L2 batch affordance exists | Batching a second opinion defeats it. |
| 7.7 | Both surfaces coexist behind flags | Classic tabs and `/copilot` both reachable | Phase 5 is coexistence, not retirement — it is the only phase that produces evidence. |

---

## 8. Deployment wiring

Phase 1 shipped `authority-service` without adding it to the image build task. It
was undeployable and 320 passing tests never noticed.

| # | Check | Command |
|---|---|---|
| 8.1 | Every service has an image | `task build && docker compose images` |
| 8.2 | Every service is in the kustomize base | `kubectl kustomize deploy/kustomize/base \| grep -c 'kind: Deployment'` |
| 8.3 | Every service has a gateway route | compare `infra/local/gateway.nginx.conf` against `docker compose ps` |
| 8.4 | ConfigMap keys survive `envFrom` | exec into a pod, `env \| sort` | 
| 8.5 | Workload identity federates per service | no shared identity |

**8.4 is not paranoia.** Kubernetes silently drops ConfigMap keys containing
hyphens. The variable is simply absent, the service falls back to a default, and
nothing logs a complaint.

---

## What to record

For each item: **pass / fail / not run**, and for anything that fails, whether it
is a deployment problem or a design problem. Those want opposite responses, and
the difference is rarely obvious from the symptom.

Anything still "not run" after Monday should be moved into the epic's risk
register with a date rather than left implicitly outstanding — the failure mode
this whole document exists to prevent is a claim that nobody ever checked and
everybody assumed somebody had.
