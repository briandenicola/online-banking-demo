# Rulings — probe idempotency, and the silent factor-divergence indicator

**Author:** Danny (Lead/Architect) · **Date:** 2026-09-09 · **Branch:** `332-beta`
**Status:** RULED. Hand-off: **Rusty** (ruling A — nothing to change, record only),
**Linus** (ruling B — one label, see §F5). Neither ruling requires a redeploy.
**Relates to** `primary-assessment-ruling.md` §P4 and §P7.

Two rulings, both short, both settling questions the authors were right to raise rather than
answer themselves.

---

## Ruling A — a probe may not be idempotent

**Rusty's propose-path probe stays exactly as it is. It creates a fresh approval on every run,
and that is the correct behaviour, not a tolerated cost. Nothing to change; `e37e695` stands.**

### §F1 The rule

**A probe that drives a real path may not reuse a prior result.** The moment it does, it stops
answering *"is this path open now?"* and starts answering *"was this path open once?"* — and the
second question is exactly the one that a probe exists to stop anyone from mistaking for the
first.

Rusty already had the principle right: *"if a check can be performed by DOING the thing, doing it
is the only honest form of the check."* Idempotency is that principle's opposite. Reusing an
outstanding approval means a probe that passes on a day the propose path is broken — which is the
only day it matters.

### §F2 The accumulation is a feature and needs no lid

The objection is that a repeated `demo:seed` adds one fresh probe approval per run, because the
probe's approval carries the copilot session id and `existing_approval_id` cannot match it against
the `demo-seed-<key>` ids.

That is fine, and it should not be papered over:

- They are **genuine cards**. They were produced by a real login, a real session, a real run and a
  real trace. Nothing about them is synthetic, so nothing about them is misleading.
- `demo:reset` sweeps `scope=all` and clears them. The bound on accumulation already exists.
- The session-id mismatch is not a defect to be worked around — it is the **honest signature of a
  real run**. A probe approval that carried a `demo-seed-<key>` id would be claiming a provenance
  it does not have.

### §F3 If the accumulation ever becomes a problem

The fix is **not** to make the probe idempotent. It is to make the probe's own approval
identifiable — a marker on the approval that says "created by the propose-path probe" — and to have
the probe close its own card at the end of a successful run, in the same run that opened it.
That keeps every probe a real drive and leaves nothing outstanding. It is not needed today and I
am not asking for it now; recorded so the wrong fix does not get reached for later.

---

## Ruling B — structural silence is correct, and the asymmetry stays visible

**Linus's `7fbc1f2` stands. Ship the silence. The demo card stays visibly asymmetric. "Primary
emits `keyFactors` + `confidence`" is deferred to the next epic, not in scope now.**

Deleting three fabricated `{"label": factor, "value": "independently corroborated"}` values off a
row that check 4.2 reads was straightforwardly right and needs no ruling. The three open questions
do.

### §F4 (a) Is structural silence acceptable to ship? — Yes

`loop.py` has the primary emit `agentAssessment: {summary, evidenceToolIds}` and nothing else. No
`keyFactors`, no `confidence`. So `primaryFactors` is structurally empty, and computing divergence
only when both sides stated factors makes the indicator silent on all live data.

**Acceptable, and better than every alternative:**

- Before the fix, the indicator fired on **100% of runs**, in bold red, and was *loudest when the
  supervisor said nothing at all*. An indicator that always fires carries zero information and
  spends the viewer's attention teaching them to ignore it.
- Silence is the truthful rendering of "one side stated no factors". It is `not_comparable` from
  `primary-assessment-ruling.md` §P4, applied one level down — **a side that did not state a
  position cannot diverge from one**, and comparing against a defaulted position is the same
  classification error Livingston had to correct by hand.
- On Brian's test: fabricated corroboration made the demo **LIE**, on the exact row check 4.2
  reads. Silence makes it show less. Showing less true is always better than showing more false.

### §F5 One condition: silence must be legible, not blank

**Silent is not the same as absent, and the card must not let a viewer read "no divergence
detected" out of a component that structurally cannot detect any.**

Where the divergence indicator would render, when `primaryFactors` is empty, render the reason —
short, neutral, in the same register the card already uses for `supervisor_unavailable` now that
Linus has made that a failed call rather than a ticked factor. Something of the form:

> *Factor comparison unavailable — the primary agent does not emit key factors.*

That is Linus's one change and it is a label, not logic. It costs one string and it is the entire
difference between "we are not claiming agreement" and "we are quietly implying it".

### §F6 (b) Must the asymmetry be visible? — Yes, visible. It may not be hidden

Linus found `demoFixture` asserting primary `keyFactors` and `confidence` **the service has never
produced** — the fixture was agreeing with the renderer instead of with the service. Removing them
was correct and is not reopened.

**The card must show what the system produces.** A fixture that dresses the primary in factors it
does not emit is a demo that rehearses a product we do not have, and its failure mode is the worst
available: it fails **at the demo**, in front of the audience, the first time live data replaces
the fixture.

The asymmetry is visible because the product is asymmetric. If Brian wants it to look symmetric,
the way to get that is §F7 — make the primary emit factors — not a fixture that pretends. **A
fixture may never assert a field the service cannot produce.** That is a general rule from this
ruling, not a one-off.

Narration line I will endorse, so the asymmetry reads as a design position rather than an
oversight: *"The supervisor states its factors; the primary states a summary and what it read. We
only compare where both sides spoke — which today means we do not compare, and we say so."*

### §F7 (c) Primary emits `keyFactors` + `confidence`? — Deferred to the next epic

Out of scope now, for three reasons:

1. **It changes what the primary is asked to produce, mid-measurement.** `primary-assessment-ruling.md`
   §P8.1 stages the measurement precisely so uncontrolled variables do not land between stages.
   Widening the primary's output contract is exactly such a variable, and it lands on the agent
   whose independence is the thing under test.
2. **It is not a serialization change, it is a prompt-and-schema change**, and its output would
   immediately become load-bearing for a bold red divergence indicator. The failure mode of a
   half-specified `keyFactors` is a divergence claim built on a field the model was not carefully
   asked for — a new fabrication where we just removed one.
3. **`confidence` carries `primary-assessment-ruling.md` §P7 with it** — displayed confidence is
   self-reported, not measured, and the system must stop implying otherwise. Emitting a primary
   `confidence` re-opens that whole question and must not be smuggled in as a side effect of
   turning an indicator back on.

**Ticketed for the next epic**, with the shape it must have when it arrives: the primary's
`keyFactors` must be specified in the **same vocabulary and the same home** as the supervisor's
(`primary-assessment-ruling.md` §P2 — one vocabulary, one home, no translation table), and the
divergence indicator must remain tri-state with `not_comparable` when either side is silent. Until
then the indicator stays silent and labelled per §F5.

---

## §F8 Summary

| | Decision | Who | Redeploy |
|---|---|---|---|
| A — probe idempotency | Probes may **not** be idempotent. `e37e695` stands unchanged; fresh approval per run is correct, `demo:reset` bounds it. | Rusty — record only, no code change | No |
| B — divergence silence | Silence stands. Add the "comparison unavailable" label (§F5). Asymmetry stays visible; fixture may not assert fields the service cannot produce. Primary factors deferred. | Linus — one label string | No |
