# Ruling — Gate B, the evidence contract seam

**Author:** Danny (Lead/Architect)
**Date:** 2026-09-08
**Branch:** `332-beta`
**Epic:** #332 Phase 3 — Banker Copilot supervisor / L2 co-signature
**Requested by:** Brian (@briandenicola), via the coordinator
**Status:** RULED. Hand-off to Turk (implementation) + Livingston (fixtures, measurement).

**Inputs read:** `livingston-supervisor-agreement-measurement.md`, `.squad/identity/now.md`,
`config/authority-policy.yaml`, `config/copilot-tools.yaml`,
`src/authority-service/Policy/PolicyEvaluator.cs`, `src/banker-copilot-service/app/tools/manifest.py`,
`src/banker-copilot-service/app/planner/loop.py`, `scripts/demo/evidence-contract.py`.
No Azure resource was created, modified, deployed or seeded. Nothing was implemented.

---

## R0 — The ruling, in one line

**Turk is right, and I am adopting his recommendation with three amendments, one of which stops us
from shipping a lie.**

Adopt the **declared projection** (`evidenceProjection` in `config/copilot-tools.yaml`), applied on
the Python side beside `redaction`. Do **not** relax `EvidenceComplete`. Do **not** change five
services' response shapes.

The three amendments:

1. **The projection grammar is closed and non-computational.** Four verbs, no literals, no
   filtering, no defaults, and it must be **lossless**. (§R2)
2. **`list_login_audits` gets NO projection, and `user.lock` / `user.unlock` stay blocked.**
   A projection there would have to fabricate the subject. This is the one place Turk's shape
   cannot be applied honestly, and nobody has noticed it yet. (§R5 — read this one)
3. **`get_user.status` is a policy-side correction, not a rename.** The contract is wrong about
   the domain there; renaming `isActive` to `status` would put `true` in a field called `status`
   and call it evidence. (§R6)

The seam test lives in **C#**, not Python, for a reason that decided several of the above. (§R7)

---

## R1 — Why the alternatives lose

I am ruling against them on their merits, not by elimination.

**Relax `EvidenceComplete` to accept arrays — REJECTED, and it is the worst option on the table.**
Today the predicate asserts *"these named fields are present and non-null."* Accepting a bare array
degrades it to *"the key exists"* — which is already guaranteed by `loop.py:330`, since the planner
writes `evidence[tool_id]` on every successful call. The check would become a tautology that can
never fail, while continuing to appear in the code, in the approval record, and in the demo
narration as a control. Against Brian's test: **the demo would pass and the system would lie.** That
is the same defect class as the scripted supervisor and the `event-processor` README — failure
wearing the costume of success. This is the option I most want on the record as refused.

**Change the tool output shapes (`id` → `accountId` across five services) — REJECTED.** It is the
tail wagging the dog: altering the public responses of `account-service`, `transaction-service`,
`transfer-service`, `user-service` and `ai-service` to satisfy an internal policy document, breaking
the UI and every other consumer, in two languages, mid-validation. It also mislocates the
authority: `authority-policy.yaml` is entitled to say what an *approval* needs; it is not entitled
to dictate the wire format of services that existed before it. And it cannot work anyway — three
tools return bare arrays, so this option still requires a wrapper. It is the adapter with extra
casualties.

**Do nothing — REJECTED, obviously, but state the failure mode precisely:** 6 of 6 L2-reachable
actions refuse at propose, check 4.2 stays unmeasurable, and the co-signature feature — the headline
of #332 — has still never executed once in production.

**The adapter — ACCEPTED.** Turk's core argument is correct and I want it restated in the terms that
actually carry it: `requiredFields: [accountId, count]` on a list is *a genuinely good assertion*.
It says **this evidence is about THIS account, and it is non-empty.** A raw array asserts neither.
The approval record is the artifact that outlives the demo, and it should carry the assertion, not
the raw dump. The projection is not a workaround for a shape mismatch — it is the place where the
system states what a piece of evidence *means*. That is worth having explicitly, and it is worth
having *declared* so it can be read without reading code.

---

## R2 — Where it lives, and the grammar it may use

**Owner: `banker-copilot-service` (Python). Declared in `config/copilot-tools.yaml`, one
`evidenceProjection` block per tool, adjacent to `redaction`.**

Three reasons, in order of weight:

1. **Precedent already exists in that exact file.** `redaction` is a declared, path-shaped transform
   over tool output, applied once on the way out of `executor.py:186`. A projection is the same
   class of object in the same lifecycle position. Putting it anywhere else splits one concern —
   "how this tool's response is conditioned before anyone stores it" — across two files.
2. **Only the caller holds the invocation arguments.** `list_account_transactions` returns a bare
   array; its `accountId` is not in the response and never will be. It exists only in the bound
   argument (`parameters.properties.accountId`, `required: [accountId]`). Authority-service never
   sees those arguments. **The projection is therefore only expressible on the calling side.** This
   is not a preference; the other options are not implementable.
3. **Shapes are the tool's own business.** The manifest already describes each tool's inputs
   (`parameters`) and its sensitive fields (`redaction`). Describing its output shape completes a
   description that is already two-thirds written.

**This does not breach the manifest's ownership rule.** `requiredEvidence` stays in
`_REFUSED_TOOL_KEYS`, rejected by name. The policy says what an *action needs*; the manifest says
what a *tool emits*. They are different statements by different owners that happen to meet. The
whole point of §R7 is that a test, not a comment, holds them together.

**The manifest loader must police the new key exactly as harshly as it polices the others.** Extend
`_ALLOWED_TOOL_KEYS`, and reject anything outside the closed grammar below **by name, with a
reason**, at startup, fatally. The value of that file is that a bad key cannot be silently ignored;
a permissive projection parser would be the first hole in it.

### The grammar — four verbs, and nothing else

| verb | means | example |
|---|---|---|
| `rename` | emit an existing response field under a more specific name | `id` → `accountId` |
| `bind` | emit a value taken from the tool's own bound invocation argument | `accountId: $args.accountId` |
| `count` | emit the arity of the response array | `count` |
| `collect` | emit the array under a named key | `items`, or `events` |

**Explicitly forbidden, and rejected at load:** literals, defaults, filters, predicates,
arithmetic, conditionals, cross-tool references, and any reference to the proposal payload.

The last two matter most. **A projection may reference the tool's own arguments, never the
proposal.** The moment a projection can read `payload.userId`, the proposer can stamp its own
conclusion onto its own evidence and the record becomes self-attesting. `$args` is safe because the
argument is what was actually sent upstream — it is a statement about the HTTP call that happened,
and the trace can be used to check it.

**The projection must be lossless.** It may add and rename; it may not drop. `collect` keeps the
full array. A projection that could discard fields would turn the approval record from a record into
a curated exhibit chosen by the party seeking approval.

Sketch, for clarity only — Turk owns the final spelling:

```yaml
  - toolId: list_account_transactions
    # ...
    evidenceProjection:
      accountId: { bind: $args.accountId }
      count:     { count: $ }
      items:     { collect: $ }

  - toolId: get_account
    # ...
    evidenceProjection:
      accountId: { rename: id }
```

Note `get_account` needs one line. Most of this fix is small; the thinking is the expensive part.

---

## R3 — What an approval record must contain

This is the part that outlives the demo, so I am ruling on it directly.

An approval record has one job: let a reader **a year from now, with no access to the people
involved**, answer three questions — *what was decided, on what basis, and could that basis have
supported it?* The third is the one we keep failing, and it is the reason `{accountId, count, items}`
beats a raw array.

**MUST carry, per evidence key:**

1. **The projected object** — the assertion. Subject identity, arity, and the material. This is what
   makes the record readable without a schema archaeology exercise.
2. **The material itself** — `items` in full, redacted. The assertion without the underlying data is
   an unfalsifiable claim; the data without the assertion is an undated dump. Both, or neither.
3. **Joinability to the run that produced it.** This is already ratified — `.squad/decisions.md`
   requires that *"evidence rows deep-link back to the originating trace node, making the trace the
   citation index for the recommendation."* A projected object with no path back to the call that
   produced it cannot satisfy that. `propose` already carries `sessionId` and
   `correlationId` (`loop.py:_run_propose_step`), and the trace holds `tool.completed` frames with
   status, duration and the bound arguments. **Confirm those ids are persisted on the approval**; if
   they are, provenance is joinable today and no schema change is needed for the demo. If they are
   not, that is a one-field fix and it *is* in scope.

**MUST NOT:** store the projection *instead of* the material (that is curation), or store evidence
whose subject identity was asserted by the proposer without the call having been scoped to that
subject (that is §R5).

**SHOULD, deferred — named here so it is not rediscovered:** a per-key provenance envelope on the
approval itself (`toolId`, method + path called, bound args, upstream status, `toolCallId`), so the
record stands alone without the trace. Right thing, wrong week: it changes the approval schema and
the schema change deserves its own test. **Required before `main`, not before the demo.**

---

## R4 — The strengthening I am deferring, and why I am naming it anyway

The projection's `accountId` is **asserted by the proposer**. Authority-service takes the copilot's
word that this evidence concerns the account in the payload.

The fix is one line of intent: `EvidenceComplete` should require that evidence identity fields
**match the corresponding payload identity** — `evidence.get_account.accountId ==
payload.accountId`. That converts the projection from a claim into a checked claim, and it is the
single highest-value follow-on in this document. It also begins closing a limitation the team
already accepted with open eyes — `.squad/decisions.md`: *"`requiredEvidence` verifies presence not
relevance."* Identity matching is the cheapest available step from presence toward relevance.

**Deferred, deliberately.** It modifies a ratified evaluator's semantics, and an evaluator change
must arrive with its own test rather than riding along on someone else's. Against Brian's test: in
this single-tenant demo the proposer is also the caller, so the unchecked assertion makes the record
*weaker*, not *false*. That is a FAIL-less defect, so it waits.

**Required before `main`.** Ticket it now, do not carry it in a decision file.

---

## R5 — `list_login_audits`: the projection that would be a lie

**This is a new finding. It is not in Livingston's write-up and it changes the shape of the fix.**

`config/authority-policy.yaml` requires `list_login_audits` → `requiredFields: [userId, count]`.
The tool is declared at `config/copilot-tools.yaml:213`, and its **own description says**:

> *"NOTE: the upstream endpoint filters by recency only, not by user — filter the returned records
> yourself."*

`parameters.required: []`. The only parameter is `limit`. **There is no `userId` anywhere — not in
the response, not in the arguments, not in the path.**

So a projection here could only produce `userId` by reading `payload.userId` — the very thing §R2
forbids. The resulting approval record would assert **"here are user X's recent logins, and there
were N of them"** when the truth is **"here are the last N logins of anybody at all, and X's may not
be among them."** `count` would be the arity of an unfiltered global list, presented as the
subject's login history.

That is not a shape mismatch. It is a **false statement in an audit artifact about a security
action** — and `user.unlock` is exactly the action where a reviewer would lean on that evidence
hardest. Against Brian's test, this is unambiguously the **LIE** column, and it is worse than the
bug we are fixing, because the current failure is loud and this one would be silent and permanent.

**RULING: `list_login_audits` gets no `evidenceProjection`. `user.lock` and `user.unlock` remain
blocked at Gate B, knowingly and on the record.**

They are blocked at Gate A as well (`/api/admin/login-audits` is admin-only), so this costs the demo
nothing that was not already gone. Two honest exits exist, both out of scope this week:

- **(a)** give the upstream a `userId` filter and the tool a `userId` parameter — then `bind` works
  and the assertion is true; or
- **(b)** correct the policy to require what the tool can honestly supply, and accept that this
  evidence is contextual rather than subject-scoped.

I lean (a): the requirement is right, the tool is under-specified. Do it after the demo.

**Generalise this, because it is the actual lesson:** a projection is only legitimate where the
subject identity is *already determined by the call that was made*. Where the call was not scoped to
the subject, no reshaping can make it so — and reaching for the payload to fill the gap is how a
formatting fix becomes a false record. Turk's adapter is right; this is the boundary it must not
cross, and it was not visible from either config file alone.

---

## R6 — `get_user.status` is a policy bug, not a rename

Contract wants `[userId, status]`; the tool returns `id`, `isActive`. `userId` ← `rename: id` is
fine. **`status` is not.** `isActive` is a boolean; `status` names a state. `isActive: true`
surfaced in an approval as `status` reads as a string field carrying `true`, and a year from now
nobody can tell whether that meant *active*, *not locked*, or *the projection did something clever*.

**RULING: correct the policy to `requiredFields: [userId, isActive]`.** Renames are only legitimate
when they *add* specificity to the same value and lose nothing (`id` → `accountId` says which kind of
id and discards no meaning). `isActive` → `status` swaps one concept for another. This is the one
place where the policy is simply wrong about the domain and should move — which is why I am not
adopting "neither config file should move much" as an absolute.

Blocked at Gate A regardless; sequence it with §R5.

---

## R7 — The test that holds the seam

**Turk's proposed test is the right test. I am overruling him on where it lives, and the reason
generalises.**

Proposal, accepted in substance: for every action's `requiredEvidence`, resolve the tool, apply its
declared projection to a recorded sample response, and assert `EvidenceComplete` passes — failing
when *either* document moves.

**It must run the real `EvidenceComplete`, not a restatement of it.** A Python test asserting
"the projected object contains the required fields" re-implements `PolicyEvaluator.cs:211-217` in a
second language. We would then hold a seam between two documents with a **third** document that can
itself drift — and if `EvidenceComplete` is ever strengthened (§R4 does exactly that), the Python
test keeps passing while the seam reopens. That is this repo's signature defect, committed a third
time, inside the fix for the second.

**RULING: the seam test lives in `src/authority-service.UnitTests`.** Both configs are repo-root
YAML, readable from C# as easily as from Python, and — I checked — `authority-service.UnitTests` and
`authority-service.Tests` already exist, so this costs no new project. The test must:

1. enumerate **every** action in `actionTypes` and every id in its `requiredEvidence`;
2. fail if a named evidence key has no tool in the manifest, or a tool has no recorded sample;
3. apply the declared projection to the recorded sample;
4. call the **real** `EvidenceComplete`, and assert it passes — **except** for the keys explicitly
   quarantined by §R5/§R6, which must be listed **with their reason in the test itself** so that
   fixing the upstream deletes the exemption and the test starts holding them automatically. A
   quarantine that is invisible becomes permanent.

**Fixtures:** recorded real responses in `tests/fixtures/evidence-samples/<toolId>.json`, each
carrying the run id or trace it was captured from. Hand-written fixtures are how a seam test passes
against a system that does not exist. `scripts/demo/evidence-contract.py` (Rusty, #356) already
derives the *contract* from both files without restating either — it is well-built and it is the
right capture-side companion; extend it to emit the sample manifest rather than writing a second
tool. **It does not encode the mapping** — I checked — so nothing here is duplicated work.

**On the Python side, one narrow unit test only:** that the projection *engine* implements the four
verbs and rejects everything else. That is testing an implementation, not the seam, and it belongs
where the implementation is.

**Sufficient?** Yes, for what it claims — that the two documents remain mutually satisfiable against
a recorded shape. It does **not** prove the recorded shape still matches live services; that gap is
real and is a post-demo contract test. Say so in the test's own comment, so the next reader does not
over-trust it.

---

## R8 — Scope and sequencing

**Minimum to unblock check 4.2 — this and nothing else:**

1. `evidenceProjection` support in `manifest.py` — closed grammar, four verbs, refused keys by name,
   fatal at startup. Applied in `executor.py` beside `redact`, so `loop.py:330` stores the projected
   object with no planner change.
2. Projections for **two tools only**: `get_account` (`rename: id`) and `list_account_transactions`
   (`bind` + `count` + `collect`). These are precisely the `requiredEvidence` of
   `account.balance.adjust` — the one L2-reachable action that clears Gate A unaided (Livingston,
   D3) and therefore the shortest honest path to a measurable 4.2.
3. The C# seam test (§R7) with fixtures for those two tools, quarantining the rest **with reasons**.
4. Confirm the approval persists `sessionId`/`correlationId`; add it if not (§R3.3).

Two tools, one loader change, one test. Turk owns it. **Success signal is unchanged and is not "no
errors":** an `approval.required` frame with `requiredRung: "L2"` followed by `subagent.spawned`,
and `grep -c "Supervisor second opinion"` > 0 in the pod logs.

**Explicitly waits — do not let this grow:**

- projections for the remaining tools, including the four still behind Gate A;
- `list_login_audits` / `user.*` (§R5) — needs an upstream change, and shipping it wrong is worse
  than shipping nothing;
- `get_user.status` policy correction (§R6);
- the evidence↔payload identity cross-check (§R4) — **required before `main`**;
- the per-key provenance envelope (§R3) — **required before `main`**;
- loan tools (`get_loan_application`, `get_underwriting_decision`, `get_policy_evaluation`) — inert
  until `loan-origination-service` ships; they must appear in the seam test as **declared-inert**,
  not silently skipped;
- live contract tests against real service responses.

**Applying Brian's test to our own fix:** unfixed, the demo **FAILS** — loudly, at propose, exactly
as it does now. Fixed the wrong way (arrays accepted, or `userId` stamped onto a global audit list),
the demo **PASSES AND LIES**. The projection as bounded here is the only option that makes the demo
pass while leaving an approval record that is still true when someone reads it next year. That is
the whole ruling.

---

## R9 — For the record

Every defect found on this repo today — the scripted supervisor, the `event-processor` README, Gate
A, Gate B — was **correct within its own file and unheld across a boundary**. That is not four bugs;
it is one missing habit, four times. §R7 is non-negotiable for that reason, and I would rather ship
the two-tool fix **with** its test than the ten-tool fix without it.

Turk's instinct to make the fix *declared rather than coded* is the right one and I want it noted as
such: it is what turns §R7 from a heroic test into a trivial one, and it is why the `list_login_audits`
lie was findable at all. The mechanism was sound. It just needed a boundary drawn around it.

**Ratified untouched:** `RoleHierarchy.cs`, `config/role-hierarchy.yaml` and their tripwires (§5.8.2)
are not implicated by anything above.
