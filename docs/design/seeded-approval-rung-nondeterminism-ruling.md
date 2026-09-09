# Ruling — non-deterministic rung on the seeded `flag-review-denied` approval

**Author:** Danny (Lead/Architect) · **Date:** 2026-09-09 · **Branch:** `332-beta`
**Status:** RULED. Hand-off: implementation unassigned (Brian assigns).
**Blocks:** epic #332 stage-1 measurement (Livingston) — see §R6.
**Relates to** `probe-idempotency-and-divergence-silence-ruling.md` §F5/§F6 (a fixture may never
assert a field the service cannot produce) and `empty-ledger-narrowing-ruling.md` §E5.

---

## §R1 The hypothesis is CONFIRMED, and the real defect is worse than the rung

Brian's hypothesis is correct in mechanism. I verified every link from source rather than
accepting the framing, and the chain holds:

1. **The escalator keys off the payload amount.** `config/authority-policy.yaml:387` —
   `large-flagged-amount`, `when: { field: amount, op: gte, threshold:
   flagged_transaction_dual_control_amount }`, `raiseTo: L2`. The threshold default
   (line 103) is **`25000.00`**.
2. **`amount` resolves to the caller-supplied payload.**
   `PredicateEvaluator.Resolve` (line 49) tries the document root, then falls back to
   `document["payload"]`. `EvaluationContext.BuildDocument` overwrites `actor` and
   `context.selfDealing` but copies `Payload` through untouched. So the proposer's `amount`
   decides the rung. Nothing server-side corrects it.
3. **The seeder fills that amount from a race winner.** `config/demo-dataset.json`,
   `flag-review-denied.payload.amount` is `{"@ref": "secondFlaggedAmount"}`.
   `demo.sh:612` sets `secondFlaggedAmount` from the discovered subject list.
4. **The subject list has one member, and which member it is varies.** `demo.sh:553-560`
   breaks the poll as soon as `n_usable >= scoring.minScoredRequired`, and
   `minScoredRequired` is **`1`**. It is first-past-the-post, not best-of.
5. **The seeded transactions straddle the threshold 2-against-21.** Of 23 seeded
   transactions only two clear `$25,000` — the `61200.00` "Wire transfer to offshore
   account" and the `48500.00` "International wire — new beneficiary", both marked
   `anomalous: true`. The other 21 top out at `9480.00`.

So **21 of the 23 possible winners produce L1 and 2 produce L2.** Run A drew an anomalous
wire; run B did not. Nothing about the two config edits Brian names touches this —
correctly identified. `pollSeconds` is only the ceiling on the wait; the loop exits at
`minScoredRequired`, so raising it 90→300 could not have changed the outcome.

**One thing I cannot verify from source, and will not assert:** which transaction actually won
either run. The refs are not persisted anywhere I can read after the fact. The reconstruction
above is forced by the arithmetic — L2 requires `amount >= 25000`, and only two seeded
transactions qualify — but "run B's winner was transaction X" is not a claim I can make.

### The part Brian did not ask about, which matters more than the rung

`demo.sh:598`:

```
[[ "$(jq 'length' <<<"$flagged_pool")" -eq 0 ]] && flagged_pool="$pool"
```

**When nothing on this run's accounts was flagged, the flagged subject silently becomes a
merely-scored one.** Flagging is a separate, higher bar than scoring:
`anomaly_service.py:910` flags only at `riskScore >= FLAGGING_THRESHOLD`, and
`FLAGGING_THRESHOLD = 0.7` (line 39). A scored-but-unflagged winner therefore yields a
`secondFlaggedTransactionId` that **`get_flagged_transaction` will 404 on, live, during the
demo** — while the approval card sits there claiming to be a flagged-transaction review.

That is not rung noise. That is precisely the failure this team already ruled against:
*a fixture may never assert a field the service cannot produce*
(`probe-idempotency-and-divergence-silence-ruling.md` §F5). **This ruling is governed by
that one.** The rung divergence is the symptom that made the fixture's non-determinism
visible; the fallback is the defect that can detonate in front of an audience.

Run B is in one of two states and I cannot tell which from source:

- **(b-i)** the winner was flagged but under `$25,000` — e.g. one of Casey's three ~$9.4k
  cash deposits, which are a deliberately seeded structuring pattern a good model may well
  score `>= 0.7`. Rung drift only; evidence resolves.
- **(b-ii)** the winner was not flagged at all — the fallback fired, and
  `get_flagged_transaction` 404s on the seeded subject.

Both are defects. (b-ii) is a broken fixture, not a noisy one.

## §R2 What is NOT the cause — three things ruled out

- **Not `newScore` `0.25` → `"0.25"`.** That is `l2-score-override-pending`'s payload.
  `transaction.score.override` has `baseRung: L2` and **`rules: []`** — no escalators at
  all. Its rung cannot move.
- **Not `pollSeconds`.** See §R1 step 4.
- **Not the §7.x walkthrough.** I checked. `docs/design/banker-copilot-deployment-verification.md`
  §7.1 says "banker proposes an L2 action" — that is a *live* proposal made during the
  walkthrough, not this seeded record. §7.5 needs `flag-review-denied` only for its
  `terminalReason: HUMAN_DENIED`, which is set by the `after: deny` transition and is
  invariant to the rung. **Brian's worry about §7.x is unfounded — the walkthrough does not
  depend on this approval being L2.** Recording that so nobody re-raises it.

## §R3 The mechanism that should have caught this already exists — and skips this approval

`demo.sh:1091-1096` refuses to seed an approval whose declared escalator did not fire:

> *"An approval seeded to demonstrate an escalator MUST actually have fired it. Otherwise the
> demo shows a card that quietly proves the opposite of the point being made."*

That guard is exactly right and it is **conditional on the spec declaring `escalator`**. All
five `esc-*` approvals declare one and are asserted every run. `flag-review-denied` declares
none, so it is free to land anywhere and report success either way.

`tests/demo/test-demo-dataset.sh` has the matching static guard — line 408 checks that any
amount derived from a `*_dual_control_amount` threshold stays *below* the dual-control line.
It cannot see `flag-review-denied`, because that amount is an `@ref`, not a `@threshold`
expression. **Both guards are well-built and both have the same blind spot: a value discovered
at runtime.**

This is the generalisable finding. Every other money approval in the dataset pins its amount
as `{"@threshold": ..., "@delta": ...}` — resolved against the *live* policy value
(`demo-lib.sh:175-177`), so it stays correct even if the threshold is retuned.
`flag-review-denied` is **the only approval whose escalator-deciding field is a raw runtime
`@ref`.**

## §R4 RULING — (c), a variant of (a): pin the *selection*, never the *value*

**The project adopts (a) in outcome — the rung is pinned — but by a specific means that
option (a) as stated would get wrong.**

I considered and **reject** the obvious form of (a): rewriting the payload amount to
`{"@threshold": "flagged_transaction_dual_control_amount", "@delta": 100}` like its
neighbours. It would pin the rung, and it would be wrong. The payload amount must equal the
amount of a real transaction, because `hashFields` includes `amount` and the demo's whole
claim is that the approval refers to a subject the read tools can resolve. Pinning the value
independently of the subject makes the payload disagree with the service — **the same defect
as (b-ii), introduced deliberately.** A fixture may not assert what the service cannot
produce; that includes an amount.

**Pin the selection, not the value.** The seeder must choose a subject that is *guaranteed*
to be flagged and *guaranteed* to be over the dual-control line, and must fail loudly if no
such subject exists — rather than quietly taking whatever won the race.

Three parts, in priority order:

1. **Require a qualifying subject.** The flagged-subject selection must filter the pool to
   transactions that are genuinely flagged *and* whose amount is `>=` the live
   `flagged_transaction_dual_control_amount`, and pick deterministically from that filtered
   set. The dataset seeds two such transactions, so this is satisfiable.
2. **Delete the silent fallback.** `flagged_pool="$pool"` must become a `die` with the same
   voice as the existing scoring failure — naming that `get_flagged_transaction` would 404
   on the subject, and pointing at ai-service's stream consumer. A run that cannot produce a
   flagged subject has not produced a demo seed; it must say so rather than hand over a
   broken one.
3. **Assert the outcome.** `flag-review-denied` should declare its expected rung and let the
   existing post-propose check enforce it, so this class of drift dies at seed time instead
   of being discovered by comparing two runs by eye.

**Cost of the chosen path:** one shell function, one dataset field, one guard. No service
change, no redeploy, no schema change. The reseed gets *slower and occasionally louder* —
it must now wait for a genuinely flagged high-value subject rather than the first thing
scored, which under Foundry's 429s is a real wait. That is the correct trade: the current
speed is bought by accepting an unusable seed.

**Cost of (b), accept-and-label:** rejected. It is cheap in edit cost and expensive in
everything else. It concedes that #332's stage-1 baseline contains a fixture that varies in
the dimension being measured, and it does not address (b-ii) at all — labelling "may be L1 or
L2" would still leave a subject the Copilot's read tool may 404 on. A label cannot fix a
broken reference. It also puts the burden on every future consumer to remember a caveat,
which is how caveats get lost.

**Cost of doing nothing:** the demo 404s in front of an audience on some fraction of runs,
and #332's measurement carries unquantified noise.

## §R5 Siblings — one flaky fixture, but a design gap with a wider blast radius

I checked every seeded approval. **`flag-review-denied` is the only one whose *rung* can
drift.** The class is not as wide as feared, but it is not zero either.

| Approval | Escalator-deciding input | Rung stable? | Notes |
|---|---|---|---|
| `l1-pending-needs-you` | `@threshold`+`@delta` (−30) | **Yes** | Below the line by construction, against the live threshold. |
| `l2-pending-awaiting-cosigner` | none — `user.unlock` `baseRung: L2` | **Yes** | Subject `lockedUserId` pinned from the dataset. |
| `l1-signed` | `@threshold`+`@delta` (−25) | **Yes** | |
| `l1-superseded` | `@threshold`+`@delta` (−25/−100) | **Yes** | |
| `esc-bulk-fan-out` | `facts` via `@threshold`+`@delta` | **Yes** | Plus the `escalator` assertion. |
| `esc-low-agent-confidence` | `facts` via `@threshold`+`@delta` | **Yes** | Plus the assertion. |
| `esc-policy-exception` | literal `POL-004` | **Yes** | Plus the assertion. |
| `esc-high-risk-customer` | literal `riskTier: high` | **Yes** | Plus the assertion. |
| `esc-anomalous-session` | `facts` via `@threshold`+`@delta` | **Yes** | Plus the assertion. |
| `l2-score-override-pending` | **none** — `rules: []`, `baseRung: L2` | **Yes** | **But see below.** |
| `flag-review-denied` | **`@ref secondFlaggedAmount`** | **NO** | The defect. |

The `esc-*` family is triply protected: facts pinned relative to the live threshold, accounts
pinned from the dataset (`evidenceSubject` / `evidenceSubjectAlt`, `demo.sh:352`), and the
declared-escalator assertion. They are the model the fix should follow.

**`l2-score-override-pending` deserves a specific note.** Its *rung* is safe — the action has
no rules. But its subject `scoredTransactionId` **is** the race winner, and `scoredRiskScore`
is whatever the model returned. So its rung is deterministic while its *evidence card content*
varies run to run. That is acceptable for a rung measurement and **not** acceptable if
Livingston's stage-1 measurement reads evidence values. Worth knowing before the measurement
is designed, not after.

**The design gap, stated generally, is the higher-value finding:**

> A seeded fixture may take its *subject* from discovery, but never its *policy-deciding
> inputs*. Everything the engine reads to decide a rung must be pinned — to a literal, or to
> the live policy value it is defined relative to. And a seeder that selects a subject must
> assert the properties it relies on, not hope the winner has them.

Two approvals violate the spirit of that today (one on rung, one on evidence). The rule should
be written into `tests/demo/test-demo-dataset.sh` so the next approval added cannot reintroduce
it.

## §R6 THE BLOCKING QUESTION — no, not on the current seed

**Livingston may not take a stage-1 measurement on the seed produced by run B.**

The reasoning is deliberately not about the rung. If (b-i) held — winner flagged, merely under
the line — I would answer *yes, measure now, and record the rung as an uncontrolled variable*,
because one known-varying fixture in a documented dimension is a manageable caveat.

I answer no because **the current seed cannot be shown to be in state (b-i) rather than
(b-ii)**, and in (b-ii) the seed is not noisy but broken: an approval that claims a flagged
subject the service will not return. A measurement taken on a seed that may contain an
unresolvable reference is not a baseline; it is a result that has to be thrown away the moment
anyone checks. Given #332 rests on this baseline, the cost of re-measuring later exceeds the
cost of settling it now.

**The escape hatch, and it is cheap.** This is decidable in one call, without the fix. Against
the current seed, fetch `/api/admin/flagged-transactions` as admin and check whether the
`flag-review-denied` subject's id appears in it:

- **Present, and its amount is under `$25,000`** → state (b-i). The seed is usable. Livingston
  may measure now, provided the measurement does not read this approval's rung or its evidence
  amounts, and the ruling's fix proceeds in parallel.
- **Absent** → state (b-ii). The seed is discarded and reseeded after the §R4 fix. No
  measurement.

I would rather Brian spend that one call than have me guess, and guessing is the specific
failure that cost this team three times today.

Independent of which state holds: **the §R4 fix must land before any measurement that is
intended to be reproducible**, because a baseline you cannot regenerate is not a baseline.

## §R7 Scope of the fix — files and changes, NOT implemented

Named for whoever Brian assigns. I have deliberately not written any of it.

**1. `scripts/demo/demo.sh` — `flagged_pool` selection (lines ~592-615).**
Filter the flagged pool to members whose `.amount` is `>=` the live
`flagged_transaction_dual_control_amount` (available in `THRESHOLDS`) before choosing
`secondFlagged*`. Sorting stays `-riskScore` for tie-breaks. Selection must be total —
if two qualify, the choice between them must be deterministic, not incidental.

**2. `scripts/demo/demo.sh` line 598 — delete the fallback.**
Replace `[[ ... -eq 0 ]] && flagged_pool="$pool"` with a `die`. The message must name the
consequence in the voice of the existing scoring failure: the subject would not be a flagged
transaction, `get_flagged_transaction` would 404 during the demo, check the ai-service stream
consumer and `FLAGGING_THRESHOLD`. Keep an explicit `--allow-unscored`-style opt-out only if
Brian wants one; the existing `build_unscored_fallback_refs` path already covers the
deliberate degraded case and should carry the same warning.

**3. `config/demo-dataset.json` — `flag-review-denied`.**
Add `"expectedRung": "L2"` (or reuse the `escalator: large-flagged-amount` field, which gets
the existing assertion at `demo.sh:1091` for free — **this is the smaller change and I prefer
it**, since the guard already exists and needs no new code). Note the constraint at
`test-demo-dataset.sh:366`: an escalator demo is asserted to start from `baseRung: L1`.
`transaction.flag.review` *is* `baseRung: L1`, so declaring `escalator` here is consistent
with that guard. Verify that before relying on it.

**4. `tests/demo/test-demo-dataset.sh` — close the static blind spot.**
The threshold-derived amount check at line 408 should be joined by its converse: an approval
whose payload feeds an escalator predicate must either derive that field from `@threshold`, or
declare the escalator it expects. This is the guard that stops the *next* approval from
reintroducing the class.

**Explicitly out of scope:** no change to `authority-policy.yaml` (the escalator and threshold
are correct), no change to `src/authority-service/**` (the engine behaved exactly as
specified — it read the amount it was given), and no change to ai-service's
`FLAGGING_THRESHOLD`. The engine is not at fault here and must not be adjusted to make a seed
convenient.

## §R8 Summary

| # | Question | Ruling |
|---|---|---|
| 1 | Is the hypothesis right? | **Confirmed from source**, and it understates the problem — the `flagged_pool` fallback can also yield a subject `get_flagged_transaction` 404s on. |
| 2 | (a) pin, (b) label, or (c)? | **(c)** — pin the *selection*, not the value. Rewriting the amount to `@threshold` would pin the rung and break the payload/service agreement. |
| 3 | Can Livingston measure now? | **No, not on the current seed.** One admin call (§R6) decides whether it is merely noisy or actually broken. The fix must land before any reproducible baseline. |
| 4 | Fix scope | `demo.sh` selection + delete fallback; `demo-dataset.json` declare the escalator; `test-demo-dataset.sh` close the blind spot. Not implemented. |
| 5 | Siblings | Rung drift is **unique to `flag-review-denied`**. But `l2-score-override-pending`'s *evidence* varies, and the underlying design gap — runtime-discovered values reaching policy-deciding fields — applies to every approval added from here. |

**The general rule this ruling adds:** *a seeded fixture may discover its subject, but never its
policy-deciding inputs; and a seeder that selects a subject must assert the properties it relies
on rather than accept whatever it was handed.*

Both existing guards — the runtime escalator assertion and the static threshold check — are
well-built and both were blind to a value that appears only at runtime. That is the shape to
watch for, and it is the fourth instance this week of a written premise being the only handle
on a false claim.

---

# REVISION 1 — 2026-09-09, after the §R6 diagnostic

**Status:** §R6 is SUPERSEDED by §R9. §R7 is AMENDED by §R10 — as written it contained a
defect that would have produced a seeder that reliably dies. §R11 and §R12 are new.
Everything above this line stands as originally written and is not edited; the diagnostic
confirmed §R1-§R5 exactly.

**Input:** `docs/design/seeded-approval-rung-diagnostic-result.md` (Coordinator, live read-only
calls, 21:55Z).

## §R9 SUPERSEDES §R6 — the seed is state (b-i), and Livingston MAY measure

The diagnostic settles the branch I left open. Run A `apr_dd707c2a4ddb46ca8f7e537b` carried
`payload.amount 61200` and fired `large-flagged-amount` against `thresholdValue 25000.00`
(L1→L2). Run B `apr_2241a79e38b64cacb9bc43ce` carried `9350` and fired nothing (L1). The
current subject `6a026fdc-…` is genuinely flagged — `riskScore 0.72`, a real `flags` array
including `potential_structuring`, `flaggedAt` inside the successful run's window. **The §598
fallback did not fire.**

**§R1's arithmetic is confirmed exactly, including the part I flagged as unverifiable.** The
winner was one of Casey's near-threshold cash deposits — the deliberately seeded structuring
trio I named in §R1 as the most likely (b-i) candidate.

**Answer to the blocking question, revised: YES.** Livingston may take the stage-1 measurement
on the current seed, under the proviso §R6 already set and which still binds: **the measurement
must not read `flag-review-denied`'s rung, and must not read its evidence amounts.** Those are
the two things known to vary. Everything else in the seed is pinned (§R5 table).

I record without hedging that my §R6 answer was **no** and the correct answer was **yes**. The
reasoning was sound on what I had — I refused to certify a seed I could not distinguish between
two states — but the ruling's practical effect was to block work that did not need blocking.
The lesson is in §R13.

**The diagnostic's own correction is the more important artifact.** The first check reported the
subject absent — state (b-ii), discard the seed — because it matched `payload.transactionId`
against the flagged row's `transactionId` *field* rather than its `id`. It was caught only
because run A's subject *also* came back absent, and two absences where one was expected present
indicts the matcher rather than the data. That is the correct instinct and it is worth naming:
**when a check returns the same surprising answer for a case you already know the answer to, the
check is the suspect.** A control case is cheap and it is the only thing standing between a
matcher bug and a discarded-seed decision.

## §R10 AMENDS §R7 — the trap is real, and the fix is one word: *when*, not *what*

The Coordinator is right, and this is the most important correction in the revision. **§R7.1 and
§R7.2 as I wrote them combine into a seeder that reliably dies instead of seeding.**

The arithmetic is the Coordinator's and it is correct. `minScoredRequired: 1` makes the poll
first-past-the-post (`demo.sh:553-560`). Under Foundry's 429 throttling each scoring call costs
~5-6s, so at the moment the poll breaks the pool typically holds exactly **one** transaction.
Only 2 of 23 seeded transactions clear `$25,000`. A filter applied to that pool therefore finds
nothing ~21/23 of the time, and with the fallback deleted the run dies.

**I got the diagnosis right in §R4 and the prescription wrong in §R7.** "Pin the selection" was
correct; implementing it as *a filter applied after the wait* was not. The defect has a name:

> **A seeder must wait for the thing it will later require. Any predicate used to SELECT a
> subject must be the same predicate that TERMINATES the wait. Filtering on a property the poll
> did not wait for is not a filter — it is a race with an assertion bolted onto the end.**

That is the generalisable finding and it supersedes §R7.1's phrasing. The fix is not a better
filter. It is moving the predicate from after the poll into the poll's break condition.

**RULED: option (ii) — change the break condition, not the post-poll filter.**

The poll at `demo.sh:541-560` must continue until **both** hold:

1. `n_usable >= scoring.minScoredRequired` — unchanged, still governs `scoredTransactionId`; and
2. **a qualifying flagged subject exists** — a row on a seeded account whose `.amount` is `>=`
   the live `flagged_transaction_dual_control_amount`.

Only then is the subject selected, from that same qualifying set, sorted deterministically
(`-amount`, then `-riskScore` as tie-break). `minScoredRequired` does **not** need raising;
raising it (the Coordinator's option (i)) would make the wait longer without making it wait for
the *right* thing — it would still be waiting for *any* N subjects, which is the same defect at
a larger N.

**Why not option (iii), naming the intended subject in the dataset and matching by identity.**
I designed this and rejected it on evidence. It is the theoretically stronger fix — it would pin
the subject, not just the rung — but it is built on the weakest field available:

- The flagged row's `.id` is **`str(uuid.uuid4())`, minted fresh on every scoring event**
  (`anomaly_service.py:879`). It is not stable across runs and cannot identify a transaction.
- Identity matching must therefore go through the row's inner `.transactionId` — and the
  diagnostic observed that only **14 of 128** flagged rows carry a non-empty one. The producer
  falls back to `""` when the stream event lacks both keys
  (`anomaly_service.py:884`).

So (iii) would rest on the sparsely-populated field while (ii) rests on `amount` and `accountId`,
which the seeder's existing `owned` filter already depends on and which fresh rows populate
correctly. **(ii) is both smaller and better-founded.** (iii) is the right upgrade *only if*
Livingston's measurement turns out to read the payload amount, and only after the empty
`transactionId` observation is understood rather than assumed away.

### §R10.1 The die-on-reseed risk this introduces, ruled explicitly

Option (ii) with a hard `die` has a failure mode I must own rather than leave for the
implementer: **the qualifying subject depends on a model score.** The wire must be scored
`>= 0.7` to be flagged at all. If tomorrow morning the model returns `0.68` on the offshore wire,
Brian's pre-demo reseed produces **no demo at all**. That is worse than an L1 card.

The evidence says this is unlikely — run A produced `61200` flagged and escalated, so we have a
direct observation of the offshore wire clearing both bars, and the scoring prompt's own
few-shots put a $15,000 unusual-hours wire at `0.85`. Unlikely is not never.

**Ruled: the `die` stands as the default, and an explicit labelled opt-out is added.** This is
*not* the option (b) I rejected in §R4. What I rejected was **silent default variance** — a
fixture that quietly lands anywhere and reports success. An opt-out that the operator must type,
which prints a warning naming exactly what is degraded, is the opposite: it makes the variance a
deliberate, visible, recorded act. The precedent is already in the file — `--allow-unscored`
does exactly this, and `build_unscored_fallback_refs` warns that `get_flagged_transaction` will
404. Follow that shape. A flag such as `--allow-unescalated` should seed the best available
flagged subject, warn that `flag-review-denied` will be L1 rather than L2, and warn that the run
is therefore not measurement-grade.

Brian must never be one bad model score away from having nothing to demo.

### §R10.2 Expected seed time under 429 throttling

Required, because the poll now waits for a specific *class* of transaction rather than the first
one to arrive.

At ~5-6s per scoring call, 23 seeded transactions take **~115-140s** to drain if scoring is
sequential. The two qualifying wires sit late in their owners' blocks (Casey's offshore wire is
the 10th of 23 overall; Retail's international wire the 22nd), so the wait runs to a substantial
fraction of the full drain. **Expect the scoring stage to take ~2-3 minutes**, against ~45s
today.

**`scoring.pollSeconds: 300` is adequate and must NOT be lowered.** It leaves roughly 2x margin
over the expected worst case. It should be revisited if the seeded transaction count grows past
~40, where the drain alone approaches 240s. The relationship is linear in transaction count and
should be stated in a comment beside the value so the next person to add transactions sees it.

The `die` message must distinguish the two failure modes, because they have different causes and
different fixes: *"no flagged subjects at all on seeded accounts"* (stream consumer or Foundry
connectivity — the existing message applies) versus *"flagged subjects exist but none reach the
$25,000 dual-control line within Ns"* (the model scored the wires below `FLAGGING_THRESHOLD`, or
`pollSeconds` is too low for the current transaction count). Collapsing them into one message
would send the next debugger to the wrong service.

## §R11 DO-NOT-CHANGE GUARD — `.id` is the lookup key; `.transactionId` is not

Recorded at the Coordinator's request, and confirmed independently from source. **The seeder's
use of `.id` at `demo.sh:604/611` is correct and must not be "fixed".**

`src/ai-service/app/routes/api.py:244` resolves `get_flagged_transaction` by reading the Redis
key `FLAGGED_TRANSACTION_PREFIX{tx_id}`. The value written at `anomaly_service.py:923` uses
`scored_id` as that suffix, and `scored_id` is what the row exposes as **`id`**. Live calls
confirm it: the row's `.id` returns 200 on both the flagged and scored endpoints; its
`.transactionId` returns 404 on both.

**One refinement the guard needs, or it will cause the next bug instead of preventing it.** The
rule is *"`.id` is the lookup key"*, **not** *"never read `.transactionId`"*. The two fields are
different things and both are legitimate in their place:

| Field | What it is | Correct use |
|---|---|---|
| `.id` | the scoring event's uuid, the Redis key suffix | **references** — payload `transactionId`, evidence, anything a read tool must resolve |
| `.transactionId` | the banking transaction's own id | **correlation** — matching a flagged row back to a transaction the seeder posted |

Stated as a blanket "never touch `.transactionId`", the guard would forbid exactly the identity
matching that option (iii) would need if it is ever adopted. Stated as above, it forbids the
actual error — substituting it as a lookup key — and permits the legitimate use. **My chosen fix
(ii) deliberately depends on neither**, resting on `amount` and `accountId` instead, so the
guard is a constraint on future work rather than on Rusty's current task.

Note also that because `.id` is a fresh uuid per scoring event, **a transaction scored twice has
two flagged rows with different `.id`s and the same `.transactionId`.** Any future correlation
work must expect that and pick deterministically.

## §R12 NEW — the 20-minute TTL is a real defect for the demo, and it is not this bug

The Coordinator's TTL finding is correct, and it is more urgent for tomorrow than the rung is.

**The binding TTL is 1200s — 20 minutes — not the 30-60 the summary suggests.**
`ttl_balance_adjust` is `1200` (`authority-policy.yaml:81`), and **eight of the ten seeded
approvals are `account.balance.adjust`**: `l1-pending-needs-you`, `l1-signed`, `l1-superseded`
and all five `esc-*`. The observation that only 2 of 10 survived twenty minutes matches exactly
— the survivors are `l2-pending-awaiting-cosigner` (`ttl_user_unlock`, 1800s) and
`l2-score-override-pending` (`ttl_transaction_score_override`, 3600s).

**So the entire NEEDS YOU queue and every escalator card — the centrepiece of the walkthrough —
has a twenty-minute life.**

**Answers to the two questions asked:**

**(1) Is reseeding immediately before the walkthrough the intended workflow? Yes.** A demo seed
is perishable by design and approvals expiring is correct product behaviour, not a bug. Brian
must reseed tomorrow morning regardless of anything in this ruling. **Tonight's usable seed buys
nothing for tomorrow's UI test**, and the Coordinator is right that this moves the §R10 fix onto
the blocking path: it must land tonight and be demonstrated by an actual successful reseed, not
reasoned about. A ruling that a fix will work is not a fix that works. I have not run the
seeder and cannot certify it; Rusty's implementation is not done until a reseed completes and
the card reads L2.

**(2) Is the short TTL itself a problem? Yes — and it is a separate defect Brian needs on the
record.** The verification document alone is eight sections across two identities; §7 is five
checks requiring two browser sessions. That does not complete in twenty minutes. **The escalator
cards will expire mid-demo**, and they are the precise artifacts epic #332 rests on. Worse, they
expire into `TTL_EXPIRED`, which renders as a terminal state — so the demo would show the
audience a queue that emptied itself for reasons the presenter must then explain.

**Ruled: fix this in the environment, not in the policy defaults.** The defaults in
`authority-policy.yaml` are product values; twenty minutes is a defensible real-world control on
a balance adjustment and I will not weaken it to make a demo convenient — that is the §R7 error
in a different costume. Every threshold already declares an `env:` override key, and I verified
the loader honours it: `PolicyLoader` resolves **environment variable → file default, with no
third source** (`PolicyLoader.cs:156-160`), and in fact *requires* every threshold to declare an
override key (line 152). **The mechanism exists and nothing currently sets it** — no
`POLICY_TTL_*` value is set anywhere in `deploy/`, `infra/` or the Taskfile.

The demo environment should set `POLICY_TTL_BALANCE_ADJUST` (and `POLICY_TTL_USER_UNLOCK`,
`POLICY_TTL_TRANSACTION_FLAG_REVIEW`) to comfortably exceed a walkthrough — four hours is a
reasonable figure and leaves room for a demo that runs long or is repeated after lunch. This is
configuration, requires no code change, and leaves the product defaults honest.

**One consequence that must not be discovered later.** Verification check **2.5** — *"TTL expiry
sweeper fires → `denied`, `terminalReason: TTL_EXPIRED`"* — is observable today **only because
the TTL is short**. Raising it in the demo environment silently disables that check. 2.5 must
then be run against a purpose-seeded short-TTL approval, or in a separate pass with the override
removed. **This is the same shape as §R3: a guard whose coverage quietly depends on a value
somebody else is about to change.** Third instance of that pattern in this ruling alone.

## §R13 What this revision changes about how I rule

- **§R6 was a correct process producing an unhelpful answer.** Refusing to certify what I could
  not distinguish was right; the cost was blocking Livingston for the time it took to run one
  read-only call. **The escape hatch was the load-bearing part of that ruling, not the "no".**
  When I cannot decide, the value is entirely in specifying the experiment — and I should weight
  a cheap experiment as *resolving* the question rather than as a caveat attached to a block.
- **I diagnosed correctly and prescribed a fix that could not run.** §R4's principle survived the
  diagnostic untouched; §R7.1's implementation of it would have died ~21 times in 23.
  **A principle is not a fix, and the gap between them is where the arithmetic lives.** I had
  every number needed to catch it — `minScoredRequired: 1`, the 2-of-23 split, the 429 cost —
  and did not multiply them together because I had stopped at the point where the principle felt
  settled.
- **The fix that is theoretically stronger was built on the weaker field.** (iii) pins more than
  (ii) and I rejected it because 114 of 128 rows have an empty `transactionId` and `.id` is a
  per-event uuid. **Check what a design rests on before preferring it for what it achieves.**

## §R14 Revised summary

| # | Question | Revised ruling |
|---|---|---|
| 1 | Hypothesis | Confirmed exactly, live. §R1 arithmetic verified against both approvals. |
| 2 | Fix approach | §R4 stands. §R7.1's post-poll filter is REPLACED by §R10: move the predicate into the poll's break condition. |
| 3 | **Can Livingston measure?** | **YES** — state (b-i) confirmed. Must not read `flag-review-denied`'s rung or evidence amounts. |
| 4 | Scope | §R10 (break condition + deterministic pick + labelled `--allow-unescalated` opt-out), §R11 (guard), §R12 (env TTL). `pollSeconds: 300` unchanged. |
| 5 | Siblings | §R5 stands unchanged. |
| 6 | **New — TTL** | 20 minutes binds 8 of 10 approvals. Reseed-before-demo is intended; the 20-minute life is a **separate defect**. Fix via `POLICY_TTL_*` env in the demo environment, not in the defaults. Watch check 2.5. |
| 7 | **New — urgency** | Tonight's seed does not survive to tomorrow. The §R10 fix is on the **blocking path** and must be proven by a real reseed, not by this document. |
