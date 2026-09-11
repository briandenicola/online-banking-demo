# Ruling — the primary agent's assessment, and what independence has to mean

**Author:** Danny (Lead/Architect)
**Date:** 2026-09-08
**Branch:** `332-beta`
**Epic:** #332 Phase 3 — Banker Copilot supervisor / L2 co-signature
**Requested by:** Brian (@briandenicola), via the coordinator
**Status:** RULED. Hand-off to Turk (implementation), Linus (card), Livingston (re-measurement).
**AMENDED 2026-09-08 (same day), on Brian's instruction:** the evidence ceiling is **in scope
now**, built in this cycle, deployed in two stages. §P5 is rewritten in full; §P8 and §P9 are
updated to match. The amendment is accepted with **one condition that decides whether it works
at all** — the stage-1/stage-2 switch must be a **budget, not a branch** (§P5.1). Nothing else in
this document is changed by the amendment.

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

**Added by the amendment, and it is a seventh item of the same kind:**

7. **The stage-1/stage-2 switch is a budget, not a branch** — otherwise stage 1 measures a
   configuration nobody runs, which is this feature's signature defect wearing yet another
   costume (§P5.1). And the ceiling's own back door gets closed in the same commit: **the
   supervisor's read list must come from the policy's `requiredEvidence`, not from the primary's
   evidence keys**, or discretionary gathering silently widens the supervisor's draw and
   blindness is defeated by a data-flow change in a module that never mentions the supervisor
   (§P5.7).

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

**AMENDED. In scope now.** Built in this cycle alongside the assessment, deployed in two stages.
The coordinator's reading of my original objection is correct and I accept the correction: I was
protecting **attribution between two measurements**, and two staged deploys are two measurements.
That was never an argument for writing the code a week later, and I should not have expressed a
sequencing constraint as a scope constraint. The distinction matters — one is a fact about
measurement, the other is a judgement about risk, and I conflated them.

Brian's framing — *the model judges; the policy decides what it must have looked at first* —
is unchanged and is the whole design.

### P5.1 The flag question, answered plainly, because it decides everything else

The coordinator asked the right question and offered to lose the argument over it: **if a
disabled ceiling means stage 1 runs a different code path from the one that ships in stage 2,
then stage 1 measures a configuration nobody runs.** That is this feature's signature defect and
it would be fatal here.

**It fails if the switch is a branch. It does not fail if the switch is a budget.** So:

> **RULING: there is no `if ceiling_enabled:`. There is a budget, and stage 1 sets it to zero.**

At budget 0 the code traverses **the same path** it traverses in stage 2: the model is asked the
same question, its reply is parsed by the same parser, its requests are recorded, the additions
function is called, and it returns empty because the budget is exhausted. Stage 1 is not the
loop switched off; it is the loop running zero iterations. The only untraversed edge is the one
that actually invokes an extra tool — and that edge is the executor, which is traversed on every
run anyway by the required evidence.

Two conditions make that true rather than merely stated, and Turk must hold both:

1. **The assessor's prompt is byte-identical in both stages.** Not "similar" — identical, one
   constant, no budget interpolated into it, no conditional paragraph. If stage 2's prompt
   invited requesting evidence and stage 1's did not, then stage 1 would measure an assessment
   the product never makes, and the flag question would be answered "yes, it fails" for a subtler
   reason than the branch. The request channel is **`unverified`, which §P2.1 already ruled into
   the contract** — the primary always states what it could not establish and may always name
   tools that would establish it. Whether that request is *honoured* is the budget's business,
   never the prompt's.
2. **A refused request is RECORDED, not dropped** — `requested but refused: budget_exhausted`
   in the trace and on the record (§P5.5). A refusal must be a positive stated fact, per the
   standing rule.

This buys something better than a safe stage 1: **stage 1 measures the demand for the ceiling
before the ceiling runs.** We will know, from real runs, which tools the primary asked for and
how often — which is the evidence for whether the budget of 3 (§P5.2) is right, and it is
evidence we would otherwise have to guess at. If stage 2 never happened, stage 1 would still not
be a lie: it is a bounded configuration, honestly reported, whose refusals are visible.

**Stage 1** — assessment real, `perRunAdditionalToolBudget: 0`. Livingston measures. The delta
from today is attributable to exactly one change: the agent count going from one to two.
**Stage 2** — budget raised. Livingston measures again. That delta is attributable to exactly one
change: the evidence surface widening. Nothing is deferred and nothing is conflated.

### P5.2 The floor first, then what bounds the ceiling

**Two invariants make "never less" true by construction rather than by validation. They come
first because everything below is only safe in their presence.**

1. **Required evidence is gathered first and unconditionally, before the model is consulted at
   all.** Ordering is the control: if the model is never asked until the required set is in hand,
   a model failure, a timeout or a garbage reply **cannot** reduce evidence below policy. There
   is nothing to check, because there is no sequence in which it happens.
2. **The additions function returns ADDITIONS, never a plan.** It cannot express "instead of",
   it cannot reorder and it cannot drop — the same move as `build_supervisor_input(intent)`. An
   unknown tool id is refused by name and recorded, not fatal: a model naming a tool that does
   not exist is a model being wrong, not a config being wrong.
   *(**Amended at audit, §P12.2.** I originally spelled this
   `additional_evidence(objective, action_id, gathered)`. That signature was wrong — it could not
   see the request it was meant to classify, and it carried the objective, which would have let a
   later edit reason about intent inside a function whose whole value is that it cannot. The
   shipped signature takes the parsed request plus four constraints, each of which can only
   **reduce** the granted set. It is a narrower control than the one I wrote.)*

**Now the bounds.** An unbounded loop in a banking demo is worse than no loop, and I want the
numbers defended rather than picked.

| bound | value | where |
|---|---:|---|
| `perRunAdditionalToolBudget` | **3** | `config/harness-limits.yaml` |
| `maxAssessmentIterations` | **2** | `config/harness-limits.yaml` |

**`perRunAdditionalToolBudget: 3`.** The registry holds twelve read tools; required sets are one
to three tools. Three additional therefore lets the model roughly **double** the evidence surface
— enough for the loop to be real — while keeping the trace legible. Trace legibility is the
stated reason `maxConcurrentSubagents` is 4 in that same file (*"the trace pane IS the demo"*),
and it is the right yardstick here too: a run that gathers eleven things is not a run anyone
watches. It is **per-run, not per-iteration** — two iterations cannot spend three each.

**`maxAssessmentIterations: 2`.** That is one initial judgement and **at most one re-judge**:
`judge → gather → judge → propose`. Two is the smallest number that makes this a feedback loop
rather than a straight line, and it makes non-convergence a **single definite event** instead of
a decaying sequence nobody can characterise. With a per-run budget of three, a third pass could
only differ by scraps. Every extra pass is also a live model call in front of an audience.

**Both live in `config/harness-limits.yaml`**, which is already the single home for these numbers
and already states the rule — a threshold stated twice is a threshold wrong once. No literal in
code; a missing or invalid value aborts startup, exactly as the rest of that file does.

**And a third bound already exists — use it rather than trusting a new one.** Discretionary reads
are inserted into the plan as **ordinary tool steps**, so they count against
`COPILOT_PLANNER_MAX_ITERATIONS` (12) and hit the existing `iteration_cap` `run.error` if
anything goes wrong with the budgets above. Two independent ceilings, one of them already
shipped and tested, is worth more than one carefully-argued new one.

### P5.3 What the model may gather — and the sharper risk, which is not tool choice

**Confirmed:** candidates are tools already declared in `config/copilot-tools.yaml`. There is no
way to spell a write in that file, so the ceiling cannot reach a mutating affordance — not
because it is filtered, but because one is not expressible.

**Correcting the assumption about capability scopes, because the correction matters.**
`capabilityScope` is declared per tool but the harness **does not enforce it** — it is metadata
the registry reports; enforcement is upstream, by the session's bearer token, which the executor
forwards unchanged. So the accurate statement is stronger than the assumed one: **the ceiling
cannot widen authority because it changes no credential.** A discretionary read the session may
not perform returns 403 from the upstream service, exactly as a required one does today (that is
what Gate A is). **Forbidden, stated rather than assumed: no discretionary read may use any
credential, token, header or identity other than the one the required reads used.** If a future
edit needs a service identity to make a discretionary read succeed, it is undoing Gate A and must
be refused at review.

A 403 on a discretionary read is **recorded as a refused read, spends budget, and does not fail
the run**. Recording it matters — otherwise the record cannot distinguish *"did not look"* from
*"was not allowed to look."* Spending budget matters too: it bounds a model that would otherwise
enumerate the 403s and learn the session's authority surface. Bounded and visible, rather than
prevented, is the right posture for a probe that grants nothing.

**The sharper risk is arguments, not tools, and it gets the structural rule:**

> **RULING: the model names a TOOL ID. It never supplies arguments.**

Arguments stay bound by `_bind_arguments` from the banker's own inputs — session context, payload,
facts — exactly as required evidence is bound today. A model that could choose arguments could
read *a different customer's account* and file it in this customer's approval record. That is a
data-boundary breach dressed as evidence gathering, and it is a much larger hole than tool
selection. A tool whose required parameters cannot be bound from those sources is **refused as
unbindable, never invented** — the same rule as §R5: the proposer may not stamp a subject onto
its own evidence.

**Excluded from the candidate set:**

- Tools already gathered (the additions function returns *additions*).
- The **§R5 quarantine** — `list_login_audits`, and anything else quarantined there. It has no
  projection precisely because its subject identity cannot be established, and letting it in
  through a discretionary door would put an unfiltered global audit list into an approval record
  by a route the Gate B ruling closed at the front. One line, no new judgement, consistent.
- Tools whose parameters cannot be bound (above).

### P5.4 How the extra evidence is held

**Yes — the same declared four-verb grammar, and there is nothing to build.** The projection is
applied in `executor.py` beside `redact`, on every invocation, so discretionary reads are
projected by construction. That is the payoff of having ruled it into the executor rather than
the planner, and it is the answer to "does the model get a different evidence path": it cannot.

Three consequences to state so nobody has to derive them:

1. **Discretionary evidence never counts toward `requiredEvidence`.** `EvidenceComplete` checks
   named keys; additions are disjoint from the required set by construction (already-gathered ids
   are excluded), so Gate B is untouched — strictly additive, as ruled. A discretionary read
   cannot satisfy a required key even accidentally.
2. **A required tool that FAILED cannot be re-entered as a discretionary addition.** A failed
   required read aborts the plan today (`outcome.aborted = True`), so the loop is never reached.
   Stated because "correct via a fact about another code path" is how a dependency nobody meant
   to create comes into existence.
3. **A tool with no declared projection is still gatherable**, and its raw response is stored.
   That is honest for discretionary evidence *because it is labelled discretionary* (§P5.5) and
   asserts nothing about a subject. The §R5 exclusion is what keeps the one case where raw
   storage would imply a false subject out of the set.

If a discretionary tool's projection is ill-formed, it aborts at **startup**, exactly as it does
now — the ceiling adds no new load-time path and no new grammar.

### P5.5 What the ceiling changes in the approval record

The coordinator's phrasing is the requirement and I am adopting it verbatim as the test: *"the
copilot reviewed the account" must not mean something different run to run while reading
identically.* This is the same concern as §P7 — the record is not reproducible, so it must at
least be **attributable and legible** — applied to the evidence axis instead of the model axis.

**RULING: `evidenceToolIds` is split, and refusals are recorded.**

| field | provenance |
|---|---|
| `requiredEvidenceToolIds` | the policy's `requiredEvidence` — a **control** |
| `discretionaryEvidenceToolIds` | what the model chose to add — a **choice** |
| `refusedEvidenceRequests` | `[{toolId, reason}]` — closed vocabulary, one home. `budget_exhausted` \| `unknown_tool` \| `unbindable` \| `quarantined` \| `read_refused_403` \| `already_gathered` \| `iterations_exhausted` *(last two added at audit, §P12.3)* |
| `assessmentIterations`, `converged` | how many passes, and whether it stopped because it was satisfied |

All four are **server-observed**, never model-asserted, exactly as `evidenceToolIds` is today
(§P3.3). The model's *requests* are its claim; these fields are the observation.

Two reasons this is not bookkeeping. First, a control and a choice must never be blurred into one
list — that is the same argument that refused relaxing `EvidenceComplete`, and the same one that
requires the trace to title discretionary steps differently. Second, **`refusedEvidenceRequests`
is what makes stage 1 measurable at all** (§P5.1): with the budget at zero it is the *only* place
the ceiling's demand is visible.

### P5.6 What happens when re-judging does not converge

Reasoning inside Turk's rule — terminal status derives from *was a proposal admitted* — and by
the same argument as §P6:

> **RULING: it proposes, with the model's own adverse assessment stating the insufficiency. The
> run's terminal status is unchanged. Hitting the cap is not a run failure.**

An agent that gathered what it could, remained unsatisfied, and then *declined to propose* has
disposed rather than proposed — invisibly, and on grounds the ladder never granted it. Worse, the
banker still needs to act, so the refusal relocates the work to the unaudited admin path (§P6.3).
The primary's verdict will presumably be `hold`, its `unverified` array carries what it could not
establish, and `refusedEvidenceRequests` carries what it asked for and did not get. **That is a
far more useful artifact than an empty screen: a human sees precisely what was missing.**

Three things forbidden, because each is a plausible-looking edit:

- **Retrying past the cap**, in any form, including a "just one more" special case.
- **Treating non-convergence as a failed run.** No `run.error`; the approval was admitted.
- **Skipping the fan-out because the primary already objected.** Same as §P6: making the second
  opinion conditional on the first is the anchoring §P1 removes, in scheduling form.

And `converged: false` must be a **positive recorded fact**, not an absence. Without it, "hit the
cap while still unsatisfied" and "was satisfied on the first pass" read identically — a broken
path looking like a working one, which is the defect class this feature keeps producing.

**One position per agent.** The final assessment is the primary's position on the card. Do not
render both passes: two verdicts from one agent forces the reader to decide which one counts,
which is a judgement the card must not delegate. The earlier pass lives in the trace, which is
this system's record by ratified decision.

### P5.7 Does the supervisor see that the ceiling was exercised? NO — and the ceiling opens a back door I want closed in the same commit

**Ruling: no. The supervisor is not told that discretionary gathering happened, what was
requested, or what was refused.** The coordinator's instinct is right and the reason is the one I
gave in §P1.2d: *"the primary went looking for more"* is a statement **about the primary's
reasoning**, which is the class §6.4(1) names by hand. It is a weaker anchor than the conclusion,
and weaker anchors still anchor. `SupervisorInput` is closed (§P1.2b); the first real test of a
boundary is whether it holds against a case one likes, and this is that case.

**Now the finding, which is the most important paragraph in this amendment.**
`FanOutEngine` derives the supervisor's read list from `sorted(primary_evidence.keys())`. The
moment discretionary evidence lands in that same dict, **the supervisor's independent draw
silently widens to follow the primary's choices** — the ceiling leaks into supervisor
construction through the back door, nobody decides it, and the diff that causes it contains no
mention of the supervisor at all. Blindness would be defeated by a *data-flow* change in another
module, which is exactly how every defect on this feature has happened.

> **RULING: the supervisor's reader tool ids are derived from the action's `requiredEvidence`,
> not from the primary's evidence keys.**

That is both more correct and safer. More correct: the supervisor's draw should be defined by
**the action under review**, which is policy, not by what the primary happened to do. Safer: it
closes the leak structurally rather than by remembering to filter. Held by a test — *the
supervisor's tool ids equal the required set regardless of what the primary gathered* — which
fails the day someone re-points the derivation at the evidence dict. **This is required in the
same commit as the ceiling; the ceiling must not merge without it.**

**Should the supervisor get its own discretionary gathering?** It sounds symmetric and I am
ruling **no for now — deferred-before-`main`, ticketed.** It would double the model calls inside
the fan-out and, more importantly, make the second draw's surface depend on a second model's
choices, so divergence would become uninterpretable during the very measurement this staging
exists to protect. Its posture already lets it say the evidence is insufficient, and Livingston's
corpus shows it does so precisely. Revisit after stage 2 is measured.

### P5.8 What this makes true about the harness — stated honestly, since Brian asked

The coordinator's answer to Brian was accurate and I am not going to improve it by inflating it:
today there is one model call, no feedback loop, a supervisor verdict that changes no control
flow, and a repair seam with nothing behind it.

This ruling closes two of those four. **A real feedback loop exists on the evidence axis** —
judge, gather, re-judge, and a bounded non-convergence outcome — and the primary's model call
becomes a judgement rather than a formality. That is genuinely what separates an investigating
harness from a workflow engine with a model bolted on, and it is cheap because the executor,
the projection, the argument binding and the budgets all already exist.

**What remains scripted, and deliberately so:** step selection stays deterministic (Brian's
ruling — `requiredEvidence` is a control, and a control that a model may re-plan degrades from a
guarantee to a detection), and the supervisor's verdict still changes no control flow (§6.4(6),
ratified — disagreement is first-class and does not gate proceeding; that is the *authority*
model, not a missing feature). The honest summary is: **the loop is on the evidence axis by
design, and off the authority axis by design.** Anyone describing this as "the agent decides what
to do" is making a claim the mechanism does not support (§P11).


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

### P8.1 Two stages, two measurements — what each one is allowed to claim (AMENDED)

The staging in §P5.1 exists for this section's benefit, so its terms are set here.

**Stage 1 — real primary assessment, `perRunAdditionalToolBudget: 0`.** The only change from the
measured `226b24a` baseline is *the agent count going from one to two*. Any movement in position
divergence is attributable to that and nothing else. This is the run that answers whether the
22.6% was measuring one agent, and it is the first time check 4.2's name is accurate.

**Stage 1 also produces a result nobody has today, for free:** `refusedEvidenceRequests` records
what the primary asked for and was refused for budget. That is a **demand measurement** — which
tools, how often, on which case classes — and it is the evidence for whether 3 is the right
budget. Report it. If the primary rarely asks, the ceiling is worth less than we think and
stage 2 should be judged accordingly rather than assumed to be an improvement.

**Stage 2 — budget raised.** The only change is *the evidence surface widening*. The delta is
attributable to that. The specific hypothesis to test is Livingston's own finding: dissent is
dominated by justifications living outside the ledger. **If the ceiling helps, it should move the
grounded cases and leave the ungrounded ones roughly where they are** — because no additional
read can produce a consent form the system does not hold. A ceiling that raised agreement
*uniformly* would be raising it for a reason unrelated to evidence, and that is a finding against
it, not for it.

**Neither stage may be pooled with the other, and neither may be pooled with the `226b24a`
baseline.** Three configurations, three separately reported results, each carrying its build
provenance — Livingston's rewritten README already sets that standard and it applies to itself.

**A guard on the whole exercise:** the ceiling changes what the primary sees while the supervisor
keeps drawing from the required set (§P5.7). That asymmetry is deliberate and it means stage 2's
divergence figure is *not* comparable to a world where both sides gathered more. Say so where the
number is quoted.

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

**Also ships now — the evidence ceiling (§P5, AMENDED).** Built in this pass, deployed second,
budget zero at stage 1:

11. The loop: required evidence first and unconditionally; `additional_evidence(...)` returning
    additions only; discretionary reads inserted as ordinary plan steps so they inherit the
    existing iteration cap (§P5.2).
12. `perRunAdditionalToolBudget` (3) and `maxAssessmentIterations` (2) in
    `config/harness-limits.yaml`, no literals in code, fatal on missing or invalid (§P5.2).
13. Tool ids only, never arguments; binding unchanged; unbindable, quarantined (§R5), unknown and
    already-gathered ids refused **by name and recorded**; no credential other than the session's
    (§P5.3).
14. Record split: `requiredEvidenceToolIds` / `discretionaryEvidenceToolIds` /
    `refusedEvidenceRequests` / `assessmentIterations` + `converged`, all server-observed;
    discretionary steps titled distinctly in the trace (§P5.5).
15. Non-convergence proposes with the adverse assessment; no `run.error`; fan-out still runs
    (§P5.6).
16. **The supervisor's reader tool ids re-derived from the action's `requiredEvidence` rather
    than from the primary's evidence keys, with the test that holds it. This must land in the
    same commit as the ceiling** — without it, discretionary gathering silently widens the
    supervisor's draw and blindness is defeated by a data-flow change in another module (§P5.7).
17. Tests specific to the staging: the assessor prompt is byte-identical at budget 0 and budget
    3; a refused request is recorded at budget 0; and the budget-0 path executes the same
    functions as the budget-3 path rather than skipping them (§P5.1). **Turk — that last one is
    the equivalent of the unwired-`project()` hole your own tamper matrix found. If the loop can
    be made inert without a test going red, the staging argument collapses.**

**Deferred-before-`main` — ticketed, not carried in a decision file:**

- **~~The additional-evidence ceiling (§P5)~~ — NO LONGER DEFERRED.** In scope now, built in this
  pass, deployed at stage 2 (§P5.1). The sequencing constraint survives as a *deploy* constraint;
  it was never a scope constraint and I was wrong to express it as one.
- **Discretionary gathering for the supervisor (§P5.7).** Sounds symmetric; would double the
  fan-out's model calls and make the second draw's surface depend on a second model's choices,
  which would render divergence uninterpretable during the measurement the staging protects.
  Revisit after stage 2.
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
(§P1.2b), including to say that the ceiling was exercised (§P5.7); requiring a counter-argument
from the primary (§P1.2c); tuning either agent to raise the agreement rate (§P1.3); letting the
model supply tool **arguments** (§P5.3); any discretionary read using a credential other than the
session's (§P5.3); retrying past `maxAssessmentIterations` (§P5.6).

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

---

# §P12 — Audit of the implementation (added after Turk's four commits)

Turk implemented §P1–§P7 in `b1d3d94`, `e5a11ee`, `29a2b4a`, `c62e945`. I have read the shipped
code against my own text and run the suite locally: **402 passing**. Nothing has run against
Azure. This section is the audit; where it corrects the ruling, the ruling above is edited in
place and points here.

**Headline: GO for stage 1** (budget 0). One two-line fix should land first — §P12.7 — because it
corrupts the one number stage 1 exists to produce. Everything else is ticketed.

## §P12.1 — `requestedEvidence` as a declared array: CONFIRMED

I wrote that the model's request would be read from its `unverified` prose. That was a mistake of
the exact class this feature keeps repeating: an **implicit contract**, in which the meaning of a
field is recovered by pattern-matching free text, and every downstream reader has to guess the
same way. Turk gave the request its own declared, closed channel.

The tell that this is right: with a declared array, a request that names a nonexistent tool is
*refused by name and recorded*. With prose parsing, the same request is **silently invisible** —
indistinguishable from a model that asked for nothing. Stage 1 exists to count requests. A channel
whose failure mode is an undercount would have quietly falsified it.

Confirmed as a correction to the ruling, not a deviation from it.

## §P12.2 — The widened `additional_evidence` signature: CONFIRMED, and it is a narrowing

This is the one I was asked to check hardest, and the suspicion was the right one: *"the ruled
signature could not do its job"* is the sentence that normally precedes a control widening. It is
not what happened here.

The control I ruled was never the arity. It was the **return type**: the function hands back
additions, so no caller can spell "instead of", "reorder" or "drop", and the floor is therefore
held one layer up by ordering rather than by this function's good behaviour. That return is
intact — `(granted, refused)`, granted disjoint from gathered.

What changed is the inputs, and the direction of the change matters:

- **Removed:** `objective`. My signature let this function see the banker's intent. A function
  that can see intent is a function a later edit can make *reason* about intent — the one thing a
  pure classifier must never do. Its removal closes a door I had left open.
- **Added:** `requested`, `known_tool_ids`, `bindable_tool_ids`, `budget`, `quarantined`. Every
  one of these except `requested` can only **shrink** the granted set. `requested` is the model's
  claim and is bounded by the other four. **No parameter carries authority**; none can lower the
  floor, because the floor is not this function's business.

A widened signature is a widened control only when a new parameter can *increase* what the
function permits. None here can. Confirmed.

**But one gap, from the same standard.** `quarantined` has a default and is overridable, so a
caller can pass `()` and empty the §R5 quarantine. No production call site does — and nothing
holds that. The signature test pins the parameter names; it does not pin the call. By the standard
in §P12.5, this parameter is a *filtered channel where an absent one would do*. Before stage 2:
either add a test that holds the production call site to the module constant, or drop the
parameter and let the function read the constant directly. **Not a stage-1 blocker** — at budget
0 nothing is granted regardless — but it must not survive to stage 2. Ticketed,
deferred-before-`main`.

## §P12.3 — Two refusal reasons beyond my five: BOTH CONFIRMED

- `already_gathered` names something my ruling *required* be excluded but never gave a name to. A
  recorded exclusion beats a silent one; without it the request vanishes and the demand count
  drops.
- `iterations_exhausted` is compelled by my own argument. Recording an unspent budget as
  `budget_exhausted` would report demand that was never tested against the cap as demand the cap
  rejected — corrupting stage 1's number in the direction that would most flatter stage 2.

The vocabulary is closed at seven in one home (`REFUSAL_REASONS`). Closed and complete beats short
and lossy. The table in §P5.5 is amended above.

## §P12.4 — Ruling over brief on `confidence`: CORRECT PRECEDENCE

Where the brief and the ruling disagreed, the ruling governs; where the ruling is wrong, it gets
amended in place and the amendment governs. Turk followed the ruling and said so, which is the
behaviour I want. `self_reported_confidence` is the internal name; the wire rename to
`selfReportedConfidence` crosses the language boundary and the golden wire and stays
**deferred-before-`main`, ticketed** (§P7.2, §P9). The deferral is what I intended.

What was required *now* is not the name — it is that nothing ranks, sorts, colour-scales, gates or
thresholds on the number. I checked; nothing does.

## §P12.5 — The fan-out deviation: CONFIRMED, and this is now the standard

I ruled the supervisor's read list be **derived** from the action's `requiredEvidence`. Turk
removed `primary_evidence` from `FanOutEngine.run_second_opinion` **entirely** — *"filtering would
have been a promise."* He is right and my version was weaker. A derived list still accepts the
primary's evidence dict at the boundary, so the leak stays reachable by anyone who later passes
the wrong argument, and the guarantee degrades from a fact into a convention with a test on it.

**The standard, written down because this is the third time it has paid:**

> When a control depends on some value never reaching some place, **delete the parameter rather
> than filter it.** A filtered channel is a promise; an absent parameter is a fact. Prefer making
> the lie unrepresentable over making it checked — and where you cannot, say plainly which of the
> two you achieved.

Its three payments: `build_supervisor_input(intent)`, which cannot name the proposal; §R5's `bind`
may only name a *required* parameter, which made the `list_login_audits` lie unspellable and aborts
startup; and now this. In each case a test was the alternative, and in each case the deleted
parameter also deleted the need for the test.

## §P12.6 — The byte-equality prompt test: KEEP, and prove it can fail

The premise needs correcting first. The tamper that byte-equality missed was **not the defect it
was designed for** — it was an incomplete edit that could not yet cause that defect. Interpolating
a budget the caller does not pass produces a prompt that is the same at every budget, so the
prompts really were equal and the assertion really should have passed. The mention-scan caught the
*intent* one move before the wiring existed. That is two guards firing at two stages of one
mistake, which is layering working, not redundancy.

But the underlying worry is legitimate and I will not wave it away: **the three guards are not
interchangeable, and only one of them is load-bearing.**

- The mention-scan and the AST no-branch test are *early and specific* — they name the offending
  line. Both are defeatable by paraphrase ("you may ask for up to three more reads" trips nothing).
- Byte-equality is *late and unconditional*. It fails on the **effect** — the prompt actually
  differing between budgets — no matter which route produced it: a threaded parameter, a global, a
  config read inside the builder, an appended paragraph, an env var. It is the backstop, and it is
  the only guard that cannot be paraphrased around.

Deleting the backstop because a cheaper guard fired first is the same reasoning that would have
deleted Gate B's `EvidenceComplete` assertion for never having failed. **Keep it.**

The honest residue is that we cannot currently *see* it fail, and "I assume this can fail" is not
a standard I let anyone else use. So, required before stage 2 and cheap enough to do now: add a
**positive control** — construct a deliberately budget-dependent prompt builder in the test and
assert the same equality trips. Turk already used this pattern in Gate B, where the raw response
must fail the very check its projection passes. A guard demonstrated to fail on the thing it names
is load-bearing. One assumed to is decoration wearing a green tick.

## §P12.7 — One defect found, fix before the stage-1 number is quoted

`_is_bindable` computes `required = schema.get("required") or list(properties.keys())`. That `or`
conflates two different facts: *"the schema declares no `required` key"* and *"the schema declares
`required: []`"*. The second means **every parameter is optional** — the tool is bindable with no
arguments at all. The fallback treats it as though every parameter were mandatory.

Live effect: `list_account_applications` (`required: []`, properties `[status]`) is recorded as
`unbindable` when it is in fact bindable. It errs **closed**, so there is no authority consequence
— but the *recorded reason is false*, and at stage 1 a request for that tool is filed as
`unbindable` instead of `budget_exhausted`. That is not a cosmetic label. It removes a real
request from the demand count, and the demand count is the entire product of stage 1.

Distinguish the two cases explicitly rather than with `or`. It is smaller than this paragraph.
Fix it before deploy.

## §P12.8 — One interpretation Turk did not flag, which I confirm

`_proposal_permitted` under the reversible `withhold` seam blocks `decline` **only** — not `hold`,
and not a failed assessment (`verdict is None` proposes). That is correct and, more than that, it
is *compelled*:

- §P5.6 rules that non-convergence proposes with an adverse assessment, and non-convergence
  typically arrives as `hold`. Blocking `hold` would make §P5.6 and §P6 contradict each other the
  moment Brian flipped the seam.
- Withholding on `primary_unavailable` would convert an **infrastructure failure into a veto** —
  the exact substitution §P4 exists to prevent.

The code says only "under the default `propose`, this is always True." Put the two sentences above
at that call site. The next person to read it will otherwise reasonably conclude the narrow
condition is an oversight and "fix" it. Not a blocker.

## §P12.9 — Two notes that are not code changes

- **For Livingston.** At budget 0, `converged: false` will be the *common* stage-1 outcome — any
  request at all yields `converged=False, assessmentIterations=1`. That is honest, but it reads
  like "hit the cap" and it is not; the refusal reasons disambiguate. Say so where the number is
  reported, and report **requests made** as its own figure. That figure is stage 1's real product.
- **Before stage 2 only.** Discretionary reads add up to three more tool payloads to the approval
  body, and `collect: $` carries whole arrays. Check the stored item against the Cosmos item limit
  before the budget is raised. I verified the C# side does not otherwise object: `EvidenceComplete`
  checks only the *named required* keys and is indifferent to extra ones, so stage 2's extra
  evidence will not produce a 422 at propose.

## §P12.10 — Verdict

**GO for stage 1**, ceiling budget 0, after §P12.7. Confirmed: §P12.1, §P12.2, §P12.3, §P12.4,
§P12.5, §P12.8. Ticketed **deferred-before-`main`**: the `quarantined` override (§P12.2), the
byte-equality positive control (§P12.6), the `_proposal_permitted` comment (§P12.8), the
`selfReportedConfidence` wire rename (§P12.4), and the stage-2 payload-size check (§P12.9).

The thing worth saying plainly about this implementation: on all three points where Turk departed
from my text, he departed by **narrowing** something I had left wide, and he said which line he
was departing from. That is the opposite of the failure mode this feature has produced five times.
