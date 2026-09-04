---
name: "agent-authority-ladder"
description: "Design a human-signature authority ladder for agentic systems that perform state-changing actions — rung escalation from config, payload-hash signing, structural bypass prevention, and genuinely independent second opinions."
domain: "architecture, agent-safety, api-design"
confidence: "medium"
source: "earned — Banker Copilot epic design (#332), online-banking-demo, 2026-09-04"
---

## Context

Applies whenever an LLM agent can trigger a **state-changing action** in a system with real
consequences (money movement, account status, adverse customer decisions, infrastructure
changes). The naive design — "let the agent act, log it, add a confidence threshold for
auto-approve" — collapses the moment anyone asks *who is accountable for this write*.

Use this when the requirement is: **agents propose, humans dispose**, and severity must
change *how many humans sign* rather than *whether* one does.

Do not use this for read-only agents, or for agents whose writes are trivially reversible and
non-consequential.

## Patterns

### 1. The ladder is a total order, and escalators only go up

```
L1 = 1 signature, acting operator
L2 = 2 signatures, 2 distinct identities, one senior + independent second opinion
L3 = not proposable — the agent may not even ask
```

Evaluation is `rung = max(baseRung, matched thresholds…, rung + escalator raises…)` over the
total order `L1 < L2 < L3`. There is **no code path that decreases a rung**. Make that an
executable invariant with a property-based test: *"for all policies and payloads, adding an
escalator match never lowers the returned rung."*

### 2. Thresholds live in versioned config, never in code

Application code contains a rung-comparison function and an escalator evaluator. Nothing else.
Every dollar amount, count, and rung assignment is in a declarative policy file. Enforce with a
CI grep gate — otherwise "config-driven" degrades to "config-driven except for the three places
we were in a hurry."

Stamp `policyVersion` on every proposal so a past decision can be re-explained under the policy
**in force at the time**. Auditors ask this. "We changed the YAML" is not an answer.

### 3. Signatures bind to a payload hash, not an intent

The attack: agent gets approval for a $5k transfer, then executes $50k under the same approval.

```
payloadHash = SHA-256( JCS(payload) ‖ actionTypeId ‖ policyVersion )
```

- **Use RFC 8785 (JCS) canonicalization.** Hand-rolled `JSON.stringify` key ordering is a
  latent correctness bug.
- Bind `actionTypeId` and `policyVersion` into the hash so a signature obtained under an old
  policy cannot be replayed under a new one.
- Store the hash **the human actually saw** on the signature record.
- Recompute at execution; any mismatch ⇒ abort, void **all** signatures, revert to `proposed`.
- Render the first 8 hex chars in the UI. It is the most legible security property you have,
  and it demos in ten seconds.

### 4. Prevent bypass structurally, in four layers

Prompt-level instruction ("you must not call write endpoints directly") is not a control.

| Layer | Mechanism |
|---|---|
| **Tool shape** | Register **zero** write tools with the model. The only write-shaped affordance is `propose_action(actionTypeId, payload, evidenceRefs)` targeting the authority service. |
| **Identity** | Mutating endpoints require a broker claim that only the authority service can obtain. The agent's forwarded operator token is read-sufficient, write-insufficient. |
| **Network** | Network policy restricts agent-service egress to read endpoints + authority service. |
| **Re-validation** | The authority service never trusts a caller-claimed rung. It recomputes rung, re-verifies evidence, recomputes the hash. Caller claims are advisory telemetry. |

Layer 1 alone is one prompt injection from failing. Layers 2–3 mean that failing layer 1 is
**not a security incident**. This is the whole point.

### 5. Put the policy engine in a different service from the agent loop

Not organizational preference — blast radius. A single service puts the constraint engine in
the same process, same identity, and same code-review surface as the LLM loop it constrains.
Split them, and make "**the authority service contains no model SDK**" a reviewable,
enforceable property. Adding one becomes a rejectable PR rather than a judgement call.

### 6. Independent second opinions must be independent by construction

A second opinion that reads the first is a rubber stamp with extra latency. Prompting
("ignore the previous analysis") does not work.

1. **Blind input.** Fresh thread. Input is the *original human intent + raw entity IDs only* —
   never the primary's plan, narrative, recommendation, or confidence. Construct this from the
   original request, not from the primary's output.
2. **Independent retrieval.** The reviewer re-executes its own reads. It may not consume the
   primary's cached tool results. Reads are cheap; a second independent draw is the point.
3. **Adversarial framing.** Primary: *"work the case."* Reviewer: *"determine whether this
   action is defensible on the evidence, and state the strongest argument against it."*
4. **Different model deployment** where config allows — partial mitigation for correlated
   errors.
5. **Structured output only** (`{recommendation, confidence, keyFactors[],
   strongestCounterArgument}`) so it cannot echo phrasing it never saw.
6. **Assert it in a test.** Verify the reviewer's constructed prompt contains none of the
   primary's output tokens.
7. **Track agreement rate.** > 95% over a real sample means independence is broken. Say so
   rather than enjoying the number.

### 7. Approval requests are durable first-class objects

```
proposed → pending → signed → executed | execution_failed
              ├──→ denied
              └──→ expired  (== DENIED, never auto-approved)
       any state → proposed  (payload mutated ⇒ all signatures voided)
```

- **Expiry is driven by an explicit sweeper**, never by database TTL deletion. Losing the
  record is not the same as denying the request, and an expired proposal should be a *visible
  event*. Render it as **"Denied (timed out)"** so nobody reads silence as consent.
- Keep `executed` and `execution_failed` distinct and terminal. A failed downstream call must
  never look like a denial and must never silently retry under the old signature.
- Set the document TTL to the decision window **plus an audit retention tail**.
- Partition on **who must act** (`/actorId`), not on `/id`. The dominant query is "what's
  waiting for me?"; an `/id` partition key makes every inbox read a cross-partition fan-out.
  For a co-signer, write a duplicated pointer doc — duplicating a pointer beats fanning out a
  query.

### 8. Evidence requirements, enforced server-side

Each action type declares `requiredEvidence: [toolId…]`. The authority service re-validates the
submitted trace and rejects with `422 EVIDENCE_INCOMPLETE`. An agent that decides to skip its
homework cannot get a card in front of a human.

Known limit: this verifies **presence, not relevance** — `limit=1` satisfies the gate. Say so
in the spec rather than implying a stronger guarantee than you shipped.

### 9. Separation of duties is enforced server-side, not in the UI

- Signer-ID uniqueness across the signature array (a replayed signature is a no-op).
- Distinct-identity count, not signature count — the same human with two sessions counts once.
- Co-signer's role must be in the rung's `cosignerRoles`.
- Re-run the self-dealing check **against the co-signer** at signing time.

### 10. Design against approval fatigue, because it is the real threat model

If an operator signs 40 cards an hour, "human in the loop" is theatre and you have built a
slower autonomous system with a liability shield. Mitigations:

- A **velocity escalator** (signatures per rolling window raises the rung).
- **No blanket "Approve All"** — batch only within one action type, under threshold, never at
  dual-control rungs.
- Track signatures-per-hour and **time-to-sign, and treat falling time-to-sign as a defect,
  not as adoption.**

### 11. Capture denial reasons

Denials are the only corpus you will ever have for improving the agent — especially if
trajectory evaluation is deferred. Require a short mandatory reason (≥ 20 chars) on the
proposal. It costs nothing now and is unrecoverable later.

## Examples

Reference implementation spec: `docs/epics/banker-copilot.md` in `online-banking-demo`
(§4 policy engine, §5 approval object model, §6 subagent policy). Complete policy YAML,
tool-manifest JSON Schema, and worked rung-evaluation examples live there.

## Anti-Patterns

- ❌ **An "L0" auto-execute tier for low-risk actions.** Every carve-out becomes the path of
  least resistance and then the default. If it is worth doing, it is worth a signature.
- ❌ **Confidence score as an approval gate.** Model confidence is not calibrated and is not
  accountability. Use it to escalate, never to authorize.
- ❌ **Signing an intent instead of a payload.** Guarantees TOCTOU.
- ❌ **Database TTL as the expiry mechanism.** Silent document deletion is indistinguishable
  from "never happened."
- ❌ **Policy engine in the same service as the agent loop.** The constrainer must not share a
  blast radius with the constrained.
- ❌ **A "reviewer" agent that receives the primary's conclusion.** You have built an expensive
  yes-man and a false sense of dual control.
- ❌ **Prompt-level bypass prevention.** "You must not call write endpoints" is a suggestion to
  a stochastic system, not a control.
- ❌ **Blanket "Approve All".** Converts approval fatigue into de facto autonomy.
- ❌ **Exposing the full threshold table to every operator.** It tells an insider exactly how to
  structure activity to stay at the lowest rung. Return the matched rationale for a *specific*
  proposal instead.
- ❌ **Shipping an unenforced control.** If the org-graph check has no data behind it, either
  stub the data or delete the check and document the gap. A control that exists only in the
  spec is worse than no control.
