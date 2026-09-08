# Ruling — the primary agent's assessment, and what independence has to mean

**Author:** Danny (Lead/Architect)
**Date:** 2026-09-08
**Branch:** `332-beta`
**Epic:** #332 Phase 3 — Banker Copilot supervisor / L2 co-signature
**Requested by:** Brian (@briandenicola), via the coordinator
**Status:** RULED. Hand-off to Turk (implementation), Linus (card), Livingston (re-measurement).

**Inputs read:** `docs/design/gate-b-evidence-contract-ruling.md` (mine),
`tests/verification/README.md` (Livingston, rewritten),
`src/banker-copilot-service/app/planner/{loop,fanout,supervisor_model,approval_view,limits}.py`,
`app/lifespan.py`, `config/authority-policy.yaml`, `config/copilot-tools.yaml`,
`config/harness-limits.yaml`, `src/authority-service/{Models/Approval.cs,Contracts/Contracts.cs,
Services/ApprovalService.cs}`, `src/ui-app/src/components/copilot/types.ts`,
`.squad/decisions/inbox/{turk-gate-b-evidence-projection,turk-run-terminal-status-honesty,
linus-key-factor-shape-and-divergence,linus-verdict-vocabulary-and-presentation-boundary,
livingston-check-4-2-measured}.md`.
No Azure resource was read, created, modified, deployed or seeded. No build, no deploy, no
`kubectl`, no `az`. Nothing was implemented.

---

## P0 — The ruling, in one line

**Give the primary a real model, and make its independence from the supervisor a property of
*construction* rather than of *prompting* — then stop calling the resulting number an agreement
rate, because that name is what makes correlated bias look like corroboration.**

Six things decide the rest:

1. **The supervisor's spawn signature does not widen. Not by one field.** (§P1)
2. **The two agents are never asked the same question.** Asymmetry of *role* and of *evidence
   provenance* is the independence mechanism; a different model or temperature is not. (§P1)
3. **One verdict vocabulary, in one home, shared by both agents.** Two vocabularies need a
   translation table, and this repo has already shipped the bug that table causes. (§P2)
4. **Every failure is named and distinguishable, and none of them lands on a verdict.**
   `primary_unavailable` ≠ `primary_assessment_invalid` ≠ a mild `CONDITIONAL`. (§P4)
5. **Agreement becomes tri-state.** `agree | diverge | not_comparable`. A side that failed has
   no position, and comparing against a defaulted one is the mirror image of the classification
   error Livingston had to correct by hand. (§P4)
6. **Displayed confidence is self-reported, not measured, and the system must stop implying
   otherwise.** (§P7)

Brian's rulings on deterministic step selection and on the adverse proposal are not relitigated.
I confirm the second one on its own reasoning and sharpen why (§P6).

---

## P1 — What makes the supervisor's independence structural (the question I was asked)

### P1.0 The premise is correct and the risk is real

If the primary and the supervisor are the same model, seeing the same evidence, asked the same
question, then agreement measures **correlated bias**, and check 4.2 would score *better* while
being worth *less* than today's 22.6%. That is the failure mode this repo has hit five times —
failure wearing the costume of success — relocated from the code into the measurement. I am
ruling on that as the primary question, and everything in §P2–§P8 is downstream of it.

**Set the expectation in advance, because that is the only defence against reading a rise as
progress: after the primary becomes real, an agreement rate that jumps sharply is SUSPICIOUS,
not good.** If the two agents are the same base model and they start agreeing 70–80% of the
time, the first hypothesis is correlation, and it must be tested (§P8) before anyone quotes it.

### P1.1 A finding that changes the cost of this work

`planner_mode()` raises unless a Foundry endpoint, a model deployment and the
`agent_framework_foundry` package are all present — and **the planner then never calls a model.**
`loop.py` imports `FoundryChatClient` only to test importability; there is no `get_response` on
the planner path. So today `foundry` and `deterministic` are behaviourally identical, and the
mode name asserts a capability that is never exercised. That is a small instance of the same
defect class: a declaration reading as a capability.

The good news is that it makes this work cheap. The configuration, the credential pattern, the
timeout, the fail-closed parse and the broad-except reasoning all exist and are proven in
`FoundryDecider`. **The primary assessor is that file's sibling, not a new subsystem.**

### P1.2 Rulings on the candidates

**(a) A different model, or a different temperature — REJECTED as the basis of independence.**
Shared training produces correlated failure. It is a knob, not a control, and its worst property
is that it is *claimable*: "we used a different model" reads to a reviewer as independence while
guaranteeing nothing. Turk may make the primary's deployment separately configurable — that is
free and occasionally useful — but **it must never appear in the demo narration, the README or
the 4.2 write-up as the reason the second opinion is independent.**

**(b) A genuinely different evidence view — ACCEPTED in the form we already have, REJECTED in
the form proposed.**

The valuable asymmetry already ships: `ToolEvidenceReader` performs a **second, independent
draw** of the same tools, binding arguments from the banker's raw inputs, holding no reference to
the primary's cache. That is provenance independence and it demonstrably works — `S08` caught a
justification that the ledger did not support, and it caught it by going and looking.

But the specific proposal — *"the supervisor sees the projected evidence **and the proposal**"* —
is **REJECTED, and it is the one candidate on the list that would undo a shipped control.** The
proposal is downstream of the primary. `build_supervisor_input(intent)` takes exactly one
parameter so that the primary's output has no argument to travel through; `FanOutEngine` already
sources `action_id` from the *request* rather than from the approval body for precisely this
reason, in a comment that says so. Feeding the supervisor the proposal reintroduces the channel
that §6.4 exists to make unreachable, and it does so for a benefit — "a different view" — that
the second draw already provides.

**RULING: the supervisor's spawn input is closed. `SupervisorInput` gains no field, and
`build_supervisor_input` gains no parameter, as part of this work.** If the primary becoming real
appears to require widening it, that appearance is the bug.

**(c) An adversarial role asymmetry — ACCEPTED. This is the mechanism.**

It is half-built already: `SUPERVISOR_POSTURE` is fixed and not caller-supplied, and a missing
counter-argument is a failsafe rather than a shrug. What is missing is the *other* half — the
primary's question — and getting it right is the whole ruling:

> **The two agents must never be asked the same question.**
> The primary is asked: *"on the evidence gathered, is the banker's requested action supportable,
> and what is the case for it?"*
> The supervisor is asked: *"is this action defensible on evidence you gathered yourself, and
> what is the strongest argument against it?"*

Two different questions over the same facts produce genuinely different reasoning traces even
from one base model. Two similar questions produce one opinion, twice. **Symmetry is the enemy
here, and it is the thing a well-meaning future edit will reintroduce** ("let's reuse the
instruction block, it's better written").

**Do NOT require the primary to state its own strongest counter-argument.** That is symmetry
wearing the costume of rigour: it makes the primary do the supervisor's job, and it makes the two
outputs comparable in a way that invites averaging them. The primary states the case *for*, plus
what it could not verify (§P2). The supervisor owns the case *against*. That division is the
product.

**How the asymmetry is held structurally** — Turk, these are the enforceable parts:

1. **No shared instruction template, no shared prompt builder.** The primary's instructions live
   in its own module as a module-level constant, exactly as `_INSTRUCTIONS` does. A test asserts
   the two constants are not the same object and that neither module imports the other's
   instruction constant. This does not prove the *questions* differ — nothing can — but it makes
   the "let's share it" refactor fail a named test instead of passing review.
2. **A signature-shaped blindness assertion for the new direction**, mirroring
   `builder_accepts_only_intent()`: the primary assessor's callable takes exactly
   `(objective, action_id, payload, evidence)` and no supervisor-shaped parameter. Ordering
   (primary runs first) is *not* a control — it is a fact about today's code that a refactor can
   change silently. Make it a signature.
3. **The `FanOutEngine` remains the only object that holds both opinions** (already true; keep
   it true, and keep the comparison in §P4's tri-state function inside it).

**(d) Withheld context — the supervisor sees the primary's conclusion but not its reasoning —
REJECTED.** The supervisor today sees *neither*, and that is better. A conclusion is the cheapest
possible anchor and the most effective one; "PROCEED, 0.94" is precisely the token an anchored
reviewer reaches for. Agreement computed by comparison after both are in hand (§6.4(6)) is only
meaningful if neither side saw the other. **Keep the supervisor blind to both.**

**(e) My addition — bound the CLAIM, not just the construction.**

Even with (b) and (c), the primary and the supervisor are two instances of the same base model.
That residual correlation cannot be engineered away this week, so it must be *disclosed* rather
than papered over:

- The approval record carries the model deployment for **both** assessments (§P7), so a reader
  can see for themselves that they were the same model.
- The words **"independent corroboration"** and **"independently corroborated"** are **banned**
  from the card, the demo script, the README and the 4.2 write-up. Linus already deleted that
  exact phrase once, where it was a fabricated constant stamped onto `supervisor_unavailable`.
  It should not return as narration.
- The defensible claim, and the only one anyone may make, is: *"a second, differently-constructed
  reviewer, working from its own reads and asked the opposite question, reached a different
  conclusion N% of the time."* That claim is true, it is measured, and it is worth having.

### P1.3 Is 77% disagreement a defect, a correct posture, or unmeasurable?

**All three, in different senses, and the distinctions matter more than the number.**

1. **As a supervisor property: a CORRECT POSTURE, and it must not be tuned.** Livingston's four
   tests are the right tests and they pass: it tracks ledger-groundedness (57% vs 94% withhold),
   it separates two near-identical prose framings pointed at different accounts, it grades
   severity, and 41 of 41 counter-arguments were distinct. Reflex does not do those things.
   Moreover the dominant *cause* of dissent is that the evidence surface is narrower than the
   justifications — the supervisor can see a ledger, never a consent form, a court order or an
   employer's confirmation. **A `hold` meaning "I cannot see the consent you are relying on" is
   the correct output of a reviewer who cannot see it.** Making it agree more would be training
   the reviewer to assume documents it never read. That is the wrong optimisation and it is
   forbidden. Anyone proposing a prompt change to raise the agreement rate must first show the
   change raises agreement on *grounded* cases without raising it on ungrounded ones (§P8).

2. **As an agreement rate: UNMEASURABLE today, and only PARTIALLY measurable after this work.**
   Livingston is right to disqualify his own headline and he should not be talked out of it.
   Today there is no second position, so the rate is the supervisor's proceed rate. After §P2
   ships there will be two positions — but they are two instances of one base model, so the rate
   still measures correlation plus judgement, mixed. **Report it with that caveat permanently
   attached, or do not report it.**

3. **As a system property: a latent DEFECT of the evidence surface, not of the model.** Three of
   nine withholds on defensible cases were "the justification lives outside the ledger". That is
   a statement about which tools the supervisor has. It is the honest cause of most of the
   dissent and it should be recorded as a known limitation of the demo, not as reviewer caution.
   `D04` (an unadjudicated sanctions hit proceeding on a $600 account for $9,500, where `D07`
   held on the identical shortfall) is the one genuine reasoning weakness in 42 runs. It is one
   case; ticket it, do not redesign around it.

**RULING: the headline of check 4.2 is retired and replaced by two separately reported
quantities** (§P8): *dissent reachability and groundedness* (already proven, sign it off), and
*position divergence* (measurable after this work, quoted with its caveat and its instability
band). A single blended "agreement rate" is a number wearing the costume of a measurement, which
is Livingston's own rule applied to his own headline.

---

## P2 — The assessment contract

### P2.1 What the primary must emit

```jsonc
{
  "verdict":     "proceed" | "hold" | "decline",   // required, closed set
  "confidence":  0.0-1.0,                          // required, self-reported (§P7)
  "rationale":   "<the case FOR the action, in its own words>",   // required, non-empty
  "keyFactors": [                                  // required, non-empty
    { "label": "<short factor>", "citedEvidenceIds": ["get_account", ...] }
  ],
  "unverified": ["<what the evidence could not establish>", ...]  // optional, see below
}
```

Reasoning, field by field:

**`verdict` — the SAME vocabulary as the supervisor: `proceed | hold | decline`.** Agreement is
computed by string comparison (`_recommendations_agree`). Two vocabularies would require a
translation table between them, and this repo has already shipped the bug that table causes:
`decline` matched no key and fell through to `"CONDITIONAL"` — the *mildest* word on the screen,
indistinguishable from "the model returned gibberish". **One vocabulary, one home.**

`RECOMMENDATIONS` currently lives in `supervisor_model.py`, and `approval_view` reaches it
through a deferred import to dodge an import cycle. That location was right when the vocabulary
belonged to one agent; it is wrong now. **RULING: move the vocabulary to a neutral module
(`app/planner/verdicts.py`), imported normally by `supervisor_model`, the new primary assessor
and `approval_view`.** The deferred import disappears with it — a cycle worked around is a design
statement nobody made deliberately. This is a move, not a copy; a second definition of this tuple
anywhere in any language is a defect on sight.

The tokens read correctly for a proposer once §P6 is in place: `proceed` means *"taking THAT
action is defensible on this evidence"*, which is a sentence the proposer can also say — or
refuse to say.

**`confidence` — required, `[0.0, 1.0]`, self-reported.** See §P7 for what it may and may not be
used for. A missing or unparsable confidence is a **parse failure**, not a silent `0.0`
(§P4.2).

**`rationale` — required, non-empty, and structurally forbidden from being the objective.**
This is the defect being fixed, so it gets a structural hold rather than a hope:

> The parse **fails** with `primary_rationale_echoes_objective` if the rationale, normalised
> (casefold, collapse whitespace, strip trailing punctuation), equals the run's objective.

One comparison, and the exact regression becomes unshippable. Do **not** extend this into a
similarity score — an exact-match guard is honest about what it catches; a fuzzy one invites
trust it has not earned.

**`keyFactors` — required, non-empty, each a `{label}` plus optional `citedEvidenceIds`.** Shape
and grounding in §P3. Empty `keyFactors` is a parse failure: an assessment with no stated factors
has not assessed anything, exactly as a second opinion with no counter-argument has not reviewed
anything.

**`unverified` — optional, and it is the primary's honest half of the asymmetry.** Livingston's
most important finding is that most dissent comes from justifications living outside the ledger.
If the primary states *what it could not establish*, a reader can tell a supervisor `hold` that
found something the primary missed from one that objects to something the primary already flagged
as unverifiable. That distinction is worth more than any tuning of the rate, and it costs one
optional array. **Optional, because absent is honest and an empty-string filler is not.**

### P2.2 What holds it

`parse_primary_assessment(text) -> PrimaryAssessment`, the sibling of `parse_second_opinion`,
built on the same principles: `_extract_json` unchanged in behaviour (find the outermost braces,
parse once, never repair — a reply we cannot read is a reply we must not act on), and **every
rejection path names the field and the reason.**

Then, the part that is easy to forget and is where the last bug actually shipped — **the wire
adapter must lose its defaults.** `primary_wire_assessment` currently does:

```python
recommendation = str(existing.get("recommendation") or "proceed")   # DELETE
if summary and "rationale" not in existing:                          # DELETE
    existing["rationale"] = summary
```

Both are manufacturing. The first invents a verdict for an agent that stated none; the second
promotes the echoed objective into a rationale, which is precisely how the card came to display
a "Primary agent — PROCEED" row that no agent produced. **RULING: delete both.** After this work
the assessment either arrived and parsed, or it failed and says so (§P4). There is no third state
for a default to serve, and while the default exists the failure is invisible.

**No default may re-enter by a different route.** The client's `AgentAssessment` fields are all
optional (`verdict?`, `confidence?`, ...), so a missing field renders as blank rather than as
failure. That is why §P4's sentinel is a *positive value on the wire* and not the absence of one:
this system's standing rule is that a success signal must be the thing that was supposed to
happen, observed — and its twin is that a **failure** signal must be a stated failure, not an
absence a renderer is left to interpret.

---

## P3 — Grounding: what structurally prevents a fabricated `value` returning

Four rules. The first three are enforceable; the fourth is a boundary I want written into the
code so nobody over-trusts the first three.

**1. The primary emits no factor `value`, and the builder has no parameter for one.**
Linus's ruling is correct and general: a flat model factor is a **statement**, not a
dimension-and-measurement pair, so there is no second half to populate and anything populating it
is invented. Apply the `build_supervisor_input` move: the primary's wire builder accepts
`key_factors: tuple[str, ...]` (or the label/citation pairs) and has **no `value` argument**. A
future edit that wants one must widen the signature, and that widening is what the test catches.
`concern` is likewise never defaulted — a defaulted `false` is a tick on a judgement nobody made,
and it makes the third arm of a tri-state unreachable by construction.

**2. Citations are CHECKED, and a bad citation is fatal, not dropped.**
Every id in `keyFactors[].citedEvidenceIds` must be a key of the evidence **actually gathered in
this run**. An id that was not gathered fails the parse with
`primary_cited_ungathered_evidence: <id>`. Silently dropping the offending id is the tempting
implementation and it is wrong: it converts "the model cited evidence it never gathered" — a
loud, specific, diagnostic fact — into a clean-looking record. That is exactly the class of edit
that produced every defect on this feature.

**3. The gathered-evidence id set stays server-derived.** `evidenceToolIds` continues to come
from `sorted(evidence.keys())`, never from the model. The record's statement of *what was
gathered* must be an observation; only the *citation* is the model's claim, and (2) checks the
claim against the observation. Keep those two facts in separate fields with separate provenance,
and do not let the model's citation list overwrite the observed one.

**4. The boundary, stated in the code so the next reader does not over-trust it.**
We check that a cited tool was gathered. We do **not** check that the factor is *true* of that
evidence, and no cheap mechanism can. Write that in the parser's docstring, in the same voice
`supervisor_model` uses about `_extract_json`. A record that implies semantic grounding it does
not have is the same lie in a smaller costume. **Semantic grounding is explicitly OUT OF SCOPE —
not deferred, refused** — until somebody proposes a mechanism that is not itself an unverified
model call.

**5. Held by the golden-wire test.** `test_golden_wire_envelopes.py` already exists and already
holds exact bytes. Extend it to the primary assessment so that any constant string reappearing on
that wire fails a named test. That is what caught the fabricated `"independently corroborated"`
the first time.

---

## P4 — Failure posture

### P4.1 Two failures, two names

The supervisor collapses every failure onto one `_failsafe`. For the primary I am ruling
otherwise, because Livingston's corpus already shows why: he had to separate *instrument failure*
from *supervisor unavailable*, since a rig that broke and a reviewer that failed are different
facts with different fixes. The same split applies here:

| sentinel | means | cause |
|---|---|---|
| `primary_unavailable` | the model was not reached, or did not answer | timeout, transport, throttling, content filter, auth |
| `primary_assessment_invalid` | a reply arrived and violated the contract | not JSON, unknown verdict, missing rationale, echoed objective, ungathered citation |

Both produce **no verdict**. Neither may produce a mild one. The failure reason travels in the
rationale, in the failsafe voice `_failsafe` already gets right — a human reading the card learns
that no assessment was formed and why, rather than seeing a confident verdict no model produced.

**Confidence is ABSENT on a failed assessment, not `0.0`.** A zero is a number: it can be
plotted, averaged and compared, and Livingston's distribution work shows exactly how a sentinel
number gets pooled into a statistic. An absent field cannot be averaged by accident. *(The
supervisor's existing `confidence=0.0` on `_failsafe`, and its silent clamp of an unparsable
confidence to `0.0` while keeping the verdict, are the same defect on the other side. I am
**deferring** their alignment rather than changing supervisor behaviour in the middle of a
measurement — see §P9. One ticket, both halves, one test.)*

### P4.2 Does the run proceed?

**Yes. The run proposes anyway, and its terminal status is unchanged.**

Turk's rule is the right frame and it answers this cleanly: terminal status derives from *"was a
proposal admitted"*. The assessment is not what the run exists to produce — **the approval is**.
The evidence was gathered deterministically and is real; the supervisor still runs and still
gives a real second opinion; the human still signs. Deleting the banker's ability to act because
a model call timed out would be the harness exercising a veto nobody granted it (§P6), and it
would do so on infrastructure grounds.

So: a failed assessment is **recorded, rendered as a failure, and does not fail the run.** Log at
warning. Do **not** emit `run.error` — the run is not failing, and an error frame that does not
correspond to a failed run is how the status field started lying in the first place.

### P4.3 Agreement becomes tri-state — this is a real defect, found here

`_primary_recommendation` reads `agentAssessment.recommendation` **and falls back to
`"proceed"`**. Once the primary can fail, that fallback manufactures a position for an agent that
has none, and the supervisor's `hold` against it renders as a *disagreement*. That is precisely
the classification error Livingston had to correct by hand in the other direction — a failed
supervisor call must never be counted as dissent — mirrored onto the primary side, and it would
be *inside the code* rather than inside a probe.

**RULING: agreement is tri-state — `agree | diverge | not_comparable`.** `not_comparable` is
returned whenever either side has no verdict, and it must render as such on the card and be
excluded from every denominator, exactly as `supervisor_unavailable` already is. This is the same
rule Linus applied to factor-level divergence (compute only when both sides stated factors), and
it should be the same rule, stated once, for verdicts.

The banner is the reason to be strict: it has already rendered *"Independent review reached the
same verdict"* over two absent verdicts. **A dead pipeline must never be able to display as
consensus.**

---

## P5 — The evidence ceiling: the model may gather MORE, never less

Accepted as Brian framed it — *the model judges; the policy decides what it must have looked at
first* — and specified here in full so it is not redesigned later. **Sequenced second (§P9).**

**Structural shape, so "never less" is true by construction rather than by validation:**

1. **Required evidence is gathered first and unconditionally, before the model is consulted at
   all.** Ordering is the control here: if the model is never asked until the required set is in
   hand, a model failure cannot reduce evidence below policy. Nothing needs to check it.
2. **The additions function returns ADDITIONS, never a plan.** Signature control:
   `additional_evidence(objective, action_id, gathered) -> tuple[str, ...]`. It cannot express
   "instead of", it cannot reorder, it cannot drop. This is the same move as
   `build_supervisor_input(intent)`.
3. **Candidates are the registry's read allowlist, minus what was already gathered.** An
   unknown id is refused by name and logged; it is not a fatal error, because a model naming a
   tool that does not exist is a model being wrong, not a config being wrong.
4. **Bounded by config, with no literal in code.** Add `perRunAdditionalToolBudget` to
   `config/harness-limits.yaml`, which is already the single home for these numbers and already
   says a threshold stated twice is a threshold wrong once.
5. **The trace and the approval must distinguish policy-required evidence from model-chosen
   evidence.** Different step titles, and a flag on the record. Blurring a control with a choice
   in the same list is how the control quietly becomes a preference — the same reasoning that
   refused relaxing `EvidenceComplete` in the Gate B ruling.

Gate B is unaffected: the required set is unchanged and the additions are strictly additive.

---

## P6 — The adverse proposal: I confirm the default, and it is not merely reversible

The coordinator set it as a reversible default and invited pushback. **I have none — I rule it
correct**, and the seam exists so Brian can see the behaviour, not because the alternative is
close.

Three reasons, strongest last:

1. **The contract of record is "agents propose; humans dispose."** An agent that declines to
   propose has *disposed*. It has exercised a veto the authority ladder never granted it, and it
   exercises it invisibly — the banker gets an empty screen, not a denial.
2. **The card's two-position comparison only exists if there are two positions.** An adverse
   assessment attached to a real proposal is the most informative artifact this feature can
   produce: a human sees the action, the evidence, the primary's objection and the supervisor's
   independent objection, and decides. Suppressing the proposal destroys the artifact the epic is
   about.
3. **A refusal pushes the work onto the ungoverned path.** The banker still needs to act. The
   admin tabs are reachable, role-authorized and — as I ruled previously — **leave no audit
   record**. An agent that refuses to propose does not prevent the action; it relocates it to the
   surface with no approval, no evidence bundle and no second opinion. **An adverse proposal on
   the governed path is strictly better than a silent refusal that routes around it.**

**The seam, so the flip is real and not a rewrite:** one declared setting on the `planner_mode`
pattern — `COPILOT_ADVERSE_PROPOSAL = propose | withhold`, default `propose`, declared and never
inferred, logged at startup, one call site, one named function. If flipped to `withhold`, the run
**must end `failed`** with `primary_declined` — no approval was admitted, and Turk's derived
status already yields that. State it explicitly so flipping the seam cannot quietly reintroduce
the `completed`-on-no-approval lie through a new door.

**And the fan-out still runs.** An adverse primary at L2 spawns the supervisor exactly as a
supportive one does. Do not shortcut it on the grounds that someone already objected — making the
second opinion conditional on the first is the anchoring §P1 removes, in scheduling form.

---

## P7 — Determinism, the record, and whether confidence is honest

### P7.1 The record cannot be reproducible, so change what it claims

Identical bytes produce split verdicts. No amount of record-keeping makes a nondeterministic call
reproducible, so **the record's job changes from "reproducible" to "attributable and
re-checkable": a reader must be able to say which model, on which exact bytes, said this — even
though re-running it would not reproduce it.** A record that implies reproducibility it does not
have is the same lie in a new costume.

**MUST be captured, per assessment (primary AND supervisor):**

| field | why |
|---|---|
| `mode` (`foundry` / `deterministic`) | distinguishes a judgement from a script — the exact confusion `supervisor_mode` was written to prevent |
| model deployment id | so a reader can see both assessments came from the same base model (§P1.2e) |
| `promptSha256` | the exact bytes; `build_prompt` is already separated from the call so the suite can assert on them |
| `responseSha256` | ties the stored structural fields to a specific reply |

**NOT on the approval: the raw reply text.** It is derived from evidence already stored, and the
trace is this system's citation index by ratified decision — `sessionId` and `correlationId` are
already persisted (Turk confirmed and held both directions). Store the raw reply in the event
stream, joined by those ids. This follows §R3's structure and avoids a Cosmos schema fight for a
field that has a home already.

*(`agentAssessment` is a free-form `JObject` in `Approval.cs`, so this needs no C# schema change.
That is convenient and it is also a weakness — nothing on the authority side validates the shape.
Ticketed, §P9; not blocking, because the Python parser is the gate and the golden-wire test holds
the bytes.)*

### P7.2 Is displayed confidence honest? No — and here is the narrow fix

The measurement is unambiguous: min 0.83, median 0.94, max 0.98; the coin-flip case ranged
0.82–0.96 **with no separation between its holds and its proceeds**; the rock-solid case and the
marginal case sit in the same range. So the number (a) never goes low, (b) does not distinguish
stable from unstable, and (c) is displayed to a human deciding whether to sign. **A reader shown
0.94 will infer near-certainty on a case that flips on identical input.** That is misleading, and
it is misleading in the direction of signing.

**RULING — three parts, none of them "recalibrate":**

1. **Do not delete it.** It is the model's own stated confidence and deleting data is its own
   dishonesty. It also has one legitimate use: an assessment reporting 0.83 alongside a stated
   `unverified` list is genuinely informative *as prose*.
2. **Stop presenting it as a decision aid.** The card must not rank, sort, colour-scale or gate
   anything on confidence, and no numeric threshold may appear in `approvalPolicy.ts` or
   anywhere else. Nothing may be hidden or revealed because a number crossed a line.
3. **Name it for what it is.** The wire field becomes `selfReportedConfidence` — the field name
   carries the caveat where a tooltip would not, and it is the only form of caveat that survives
   being copied into a screenshot. *(This crosses the language boundary and touches the golden
   wire tests, so the **rename is deferred-before-`main`** (§P9). What is **required now**, and
   costs nothing: no document, demo script, README or 4.2 write-up may describe confidence as a
   reliability or certainty signal, and the one honest measured sentence — "self-reported;
   observed 0.83–0.98, and identical inputs have produced opposite verdicts at overlapping
   confidence" — goes in `tests/verification/README.md` once, where the number is quoted.)*

The `disagreementOf` confidence branch already fails closed to `false`; leave it closed. It
should not start firing on a signal we have just ruled uninformative.

---

## P8 — What check 4.2 should measure after this

For Livingston, and it needs no new infrastructure — the corpus already records `expectation`,
`polarity` and `grounded` per case, fixed before the run.

**Sign off now, on the current data, exactly as Livingston proposed:** *independent dissent is
reachable, evidence-anchored and frequently correct.* That is a real result and it should not
wait for this work.

**Do not sign off "agreement" — retire the metric.** Replace it with three quantities:

1. **Dissent groundedness** (already measured): withhold rate on ledger-grounded vs ungrounded
   framings — 57% vs 94%. This is the instrument that shows reasoning rather than reflex, and it
   is the one to keep pointing at.
2. **Position divergence** (measurable after this work): the rate at which the two verdicts
   differ, tri-state, `not_comparable` excluded from the denominator and reported separately, with
   the marginal-case instability band stated as a band and not a point.
3. **The one that actually tests independence — caught-error rate.** On cases where the framing
   is **ungrounded** against the live ledger and the **primary** nonetheless says `proceed`, how
   often does the supervisor withhold? *That* is the number that says the second opinion is worth
   its cost. An agreement rate cannot distinguish two good reviewers from two identically blind
   ones; this can.

**The correlation test, stated in advance so it cannot be rationalised afterwards:** if the
primary and supervisor agree at similar rates on grounded and ungrounded cases alike, that is
**correlated bias** — the two agents are failing together — and a high agreement rate under those
conditions is a *worse* result than today's 22.6%. If instead agreement is high on grounded cases
and low on ungrounded ones, the two agents are discriminating on evidence, and the number means
what it says. **Both agents' error correlation is the finding; the rate is only its shadow.**

One more, cheap and unrelated to models: `SupervisorInput` carries no payload, so `credit` vs
`debit` and the amount reach the supervisor only as prose — on `account.balance.adjust`, the only
L2 action currently exercisable, where both directions share one action id. Livingston already
flagged this and he is right that it is narrower than it looks. It is **not** fixed by widening
the spawn input casually (§P1.2b); the honest options are a distinct action id per direction or a
declared, payload-derived direction field admitted under §6.4(1) as banker-declared. **Ticketed,
required before `main`, and it is a design question, not a patch.**

---

## P9 — Scope, sequencing, and what waits

**Brian's test, applied to this defect: does it make the demo FAIL, or LIE?** It **LIES**, which
is why it is in scope now. The card renders a "Primary agent — PROCEED" row, with a rationale,
that no agent produced; the epic's headline number is quoted as a two-agent comparison that
measures one agent. Nothing errors. Everything looks like it works.

**Ships now — the minimum that makes the card true:**

1. The primary assessor: its own module, own instruction constant, own prompt builder, the
   `FoundryDecider` pattern for client/credential/timeout/broad-except (§P1.1).
2. The shared vocabulary moved to `app/planner/verdicts.py`; the deferred import deleted (§P2.1).
3. `parse_primary_assessment` — closed verdict set, required rationale with the objective-echo
   guard, required non-empty `keyFactors`, citation-set check, every rejection named (§P2.2, §P3).
4. Deletion of the `or "proceed"` verdict default and the `summary → rationale` promotion in
   `primary_wire_assessment` (§P2.2).
5. `primary_unavailable` / `primary_assessment_invalid`, confidence **absent** on failure, run
   proceeds, no `run.error` (§P4.1–2).
6. Tri-state agreement; `not_comparable` when either side has no verdict; excluded from
   denominators; the banner may not render consensus over it (§P4.3).
7. The adverse-proposal seam, declared, one call site, `withhold` ⇒ run `failed` +
   `primary_declined` (§P6).
8. Attribution on both assessments: mode, model deployment, `promptSha256`, `responseSha256`
   (§P7.1).
9. Tests: the two-instruction-constants separation test; the assessor-signature blindness
   assertion; golden-wire extension over the primary assessment; and — Turk, this one specifically
   — a test that **fails if the wiring is removed**. Your own tamper matrix found that unwiring
   `project(...)` left 285 tests green and the whole fix inert. The equivalent hole here is an
   assessor that is never called from `_run_propose_step`.
10. Documentation: confidence may not be described as a reliability signal; "independent
    corroboration" banned (§P1.2e, §P7.2).

**Deferred-before-`main` — ticketed, not carried in a decision file:**

- **The additional-evidence ceiling (§P5).** Sequenced *second*, and for a real reason rather than
  caution: shipping it at the same time as the primary assessment would change the evidence
  surface and the number of agents in the same deploy, and no movement in 4.2 could then be
  attributed to either. **Ship the assessment, re-measure, then open the ceiling.**
- Supervisor confidence alignment: `_failsafe` confidence absent rather than `0.0`, and an
  unparsable confidence failing closed rather than clamping to `0.0` while keeping the verdict.
  Deferred because it changes supervisor behaviour mid-measurement. One ticket, both halves.
- `confidence` → `selfReportedConfidence` on the wire (§P7.2), with the client and golden-wire
  updates.
- Authority-side shape validation of `agentAssessment`, today an unvalidated `JObject` (§P7.1).
- The supervisor's payload-direction gap on `account.balance.adjust` (§P8).
- Carried over from the Gate B ruling and still owed: the evidence↔payload identity cross-check
  (§R4) and the per-key provenance envelope (§R3).

**Refused, not deferred:** semantic grounding of key factors (§P3.4); widening `SupervisorInput`
(§P1.2b); requiring a counter-argument from the primary (§P1.2c); tuning either agent to raise the
agreement rate (§P1.3).

---

## P10 — Two confirmations owed

### P10.1 Turk's §R7 split — CONFIRMED, and §R7 is amended to match

He applied the *reason* of §R7 over its letter, and the reason is the part that carries: **no
third document restating a second.** Taken literally, "apply the declared projection in C#"
required a C# interpreter of the four verbs — a third statement of the grammar, drifting from the
Python engine, committed inside the fix for the second instance of that exact defect. He saw that,
chose the construction that avoids it, and **flagged the deviation instead of burying it**, which
is the behaviour I want to see repeated.

His split is stronger than what I wrote. Each test runs one **real** component — Python proves the
fixture is what the shipped loader and engine actually emit; C# feeds that fixture to the real
`EvidenceComplete` — and the checked-in artifact is the join, so a hand-edited fixture fails the
Python side and a drifted policy fails the C# side. His additions after tamper testing (asserting
the manifest *declares* a projection for every held key, after finding the C# suite green with the
declaration deleted; the negative control requiring the raw response to FAIL what the projection
passes) close holes my text did not anticipate. **§R7 is amended: the seam is held by two tests
over one artifact, each exercising one real component. No C# verb interpreter.**

Two notes for the record. His largest stated risk — hand-built fixtures — was the right thing to
flag and has since been closed by the coordinator's live captures at `226b24a`; the *combination*
is what makes it sound, and neither half would have been enough. And the move I most want reused:
making `bind` able to name only a parameter in the tool's own `parameters.required`, which turned
my §R5 generalisation from a paragraph into a **startup abort** — the `list_login_audits` lie is
now unspellable rather than merely forbidden. That is the standard: structural, not documented.

### P10.2 Linus's two backend lines — ENDORSED, with the rule stated so it is not a blank cheque

Endorsed. The reasoning that makes it right is not "it was only two lines":

**A charter boundary follows the concern, not the file extension.** A translation table from
server verdict tokens to display captions is presentation logic. It had **drifted across the
language boundary into Python, out of frontend review** — and that drift is exactly what let
`decline` render as `CONDITIONAL` for as long as it did, because the people who owned the meaning
of the caption were not looking at the file that produced it. Fixing presentation logic where it
actually lives is squarely within a frontend charter.

**But the permission is asymmetric, and the asymmetry is the whole rule: Linus may DELETE
presentation logic from the backend. He may not ADD it there.** Removal returns a concern to its
owner; addition puts a second one across the boundary. Conditions, all of which he met: it is a
removal or a reduction, it is flagged rather than hidden, and the owning agent reviews it.

His `value` deletion is the same call as deleting `"CONDITIONAL"`, and it generalises to a rule I
am adopting: **a field that must be fabricated to populate corresponds to nothing and must not be
populated.** §P3.1 applies it to the primary before the primary exists. His refusal to delete
factor-level divergence — guarding it instead so it starts working the day the primary emits
factors — was also right, and this ruling is what makes that day arrive.

---

## P11 — For the record

The Gate B ruling closed with the observation that every defect found that day was **correct
within its own file and unheld across a boundary.** This one has a companion, and it is the
reason §P1 is the longest section in the document:

**Every defect on this feature has been a claim the system was not entitled to make.** The
scripted supervisor claimed review. The banner claimed consensus over two absent verdicts.
`run.done` claimed completion over a refused proposal. `"independently corroborated"` claimed
corroboration that was never performed. The primary's echoed objective claims an assessment.
And an agreement rate between two instances of one model, prompted alike, would claim
independence.

The pattern is not sloppiness — every one of those was written by someone doing careful work in a
file where the claim was locally true. **What is missing is the habit of asking what the artifact
will be read as by someone who cannot see the code.** That question is what §R5 was, and it is
what §P1.2e, §P4.3 and §P7.2 are here.

So the standing test I want alongside Brian's: *does the defect make the demo FAIL, or make it
LIE?* — and its companion — **does this artifact claim more than the mechanism behind it can
support?** The second one is what catches the defects that never throw.

**Ratified untouched by this ruling:** `build_supervisor_input` and the blindness suite; the
`RoleHierarchy` tripwires; the Gate B projection grammar and its two tests; Turk's derived
terminal status; Linus's tri-state `concern` and the both-sides factor guard.
