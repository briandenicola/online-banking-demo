# Ruling — #140 sequencing, and the triage of #335

**Author:** Danny (Lead/Architect) · **Date:** 2026-09-09 · **Branch:** `332-beta`

Companion to `empty-ledger-narrowing-ruling.md` and
`probe-idempotency-and-divergence-silence-ruling.md`. Two questions, ruled separately.

---

## §G — #140 may open now, but may not touch four paths until stage 2 is on the board

### §G1 — The decision

**(a) #140 may open before stage 2 is measured. Research and design only.**

Both stages do **not** need to be on the board first. But the permission is bounded by files, not
by intent, and the boundary is below.

**#140 may not modify any of these until stage 2 is measured:**

```
config/harness-limits.yaml
config/authority-policy.yaml
config/copilot-tools.yaml
src/banker-copilot-service/
```

A change to any of the four requires the stage-2 number to be recorded first. Everything else —
the `loan-origination-service` skeleton, the Cosmos containers, the `/loans` React route, the
underwriting domain model, the six-agent design document — is outside the measured system and may
proceed in parallel.

### §G2 — Why this boundary and not "wait for both stages"

**The discriminating fact is a number, not a principle.** `config/harness-limits.yaml` declares
`maxConcurrentSubagents: 4`. #140 proposes **six** specialist underwriting agents. Six does not fit
in four, so #140 cannot be built as described without editing that file.

**Stage 2 IS an edit to that same file** — ceiling budget 0 → 3, config-only, deliberately isolated
so that the difference between the two measurements is attributable to one value. Two deploys and
two measurements exist precisely to preserve that attribution.

So the hazard is not "#140 is large" or "#140 is risky." It is specific and arithmetic: **if #140
raises the fan-out ceiling to fit six agents, the stage-2 delta stops being attributable to the
evidence ceiling, and Livingston's second measurement measures two changes at once.** That is the
same defect as moving the accounts under test between stage 1 and stage 2 — the one my earlier
sequencing rule already forbids. This is that rule, applied to a different file.

**And it is the reason the answer is not "wait."** Waiting would be the right call if the risk were
diffuse. It is not. It lives in four paths, and naming them costs nothing and unblocks a domain
that needs research time anyway. **A boundary a reviewer can check with `git diff --name-only` is
worth more than a judgement call about whether a change was "big enough" to matter.**

### §G3 — (b) Where `loan.*` stops being safe

`config/authority-policy.yaml:520` declares exactly one loan action, `loan.decision.record`, with
`agentMayPropose: true`, targeting `loan-origination-service`, requiring
`[get_loan_application, get_underwriting_decision, get_policy_evaluation]`.

**It is inert today. Verified, not assumed:** there is no `src/loan-origination-service/`, and
`config/copilot-tools.yaml` declares none of those three tools. The harness cannot propose an
action whose evidence tools do not exist.

**But note precisely what makes it inert. It is inert by ABSENCE, not by a flag.** There is no
`enabled: false` on the action. `agentMayPropose` is already `true`. The declaration is fully armed
and waiting for a tool manifest entry.

**Therefore the line is exact: `loan.*` stops being safe the moment a loan tool is added to
`config/copilot-tools.yaml`.** That single line — not the new service, not the React route, not the
Cosmos containers — is what connects #140 to the system under measurement. Phase 1 of #140 is safe
for as long as, and only for as long as, that file is untouched.

I am **not** asking for an `enabled: false` flag to be added. Adding one would create a second
place where "is this action live?" is stated, and a threshold or a state stated twice is stated
wrong once. The tool manifest is the single gate; it is sufficient; it just needs to be known to be
the gate, which is what this section records.

### §G4 — (c) Turk's contention is real, and thin

Turk owes three things. Ranked, with the sequencing I want:

1. **The stage-2 `quarantined` pin** — blocking. Stage 2 cannot be measured until the production
   call site is pinned. Small.
2. **The §B2.2 comment correction** (Ruling 1, §E6) — **comment-only. It changes no behaviour and
   requires no redeploy.** Minutes, not days. The functional §B2.2 fix is Rusty's, in `demo.sh`,
   and does not touch Turk at all.
3. **#140 research** — not blocking anything, and the item with the longest natural lead time.

**Ruling: sequence 1 and 2 ahead of 3, and then let Turk pick up #140 research in parallel. Do not
hold the research.** Items 1 and 2 together are a fraction of a day; #140 research is weeks. Making
the long item wait on the short ones costs real calendar time and buys nothing, because the
research produces a design document, and a design document cannot invalidate a measurement.

**What I am explicitly NOT doing: I am not making Turk's #140 work wait on Livingston.** The
contention Brian flagged is a real overlap of one person, but it resolves by ordering two small
items first, not by serialising an epic behind a measurement.

### §G5 — What would change this ruling

If #140 research concludes that six agents cannot be designed without also re-tuning fan-out —
i.e. the ceiling change is not deferrable to Phase 2 — then it stops being a research question and
becomes a scheduling one, and it comes back to me. **A research phase that discovers it must edit
`harness-limits.yaml` to continue has reached the boundary in §G1 and must stop there, not push
through it.**

---

## §H — #335 is NOT a #332 blocker. The approval trail is audited. Two real items remain.

### §H1 — Read the code first: the issue is substantially stale

**(c) first, because it is the question that was expected to go the other way, and it does not.**

**The nine authority event types are NOT dropped. All eleven are handled explicitly**, in
`src/event-processor/main.go:457–481` — `CopilotSessionStarted`, `ApprovalProposed`,
`ActionProposalRejected`, `PolicyEscalated`, `ApprovalSigned`, `ApprovalDenied`, `ApprovalExpired`,
`ApprovalExecuted`, `ApprovalExecutionFailed`, `ApprovalVoidedByPolicyChange`, `PolicyReloaded` —
with a common field set (`approvalId`, `correlationId`, `signerId`, `slotOrdinal`,
`terminalReason`, `policyVersion`) chosen so an auditor can reconstruct a full chain by filtering
on one key. They are really published: `authority-service/Services/ApprovalService.cs` publishes
via `AuditPublisher`, off `SharedIdentifiers.Events`.

**Defect A is also fixed.** `InsufficientFundsAttempt` (`main.go:422`) and `UserRegistered`
(`main.go:429`) both have cases now, plus `RoleGranted` at WARN. The issue body describes a
two-case switch; the switch has sixteen types.

**And it is guarded**: `TestEveryPublishedEventTypeIsAudited` asserts every listed type produces an
`Audit <type>` line and does not reach the default branch, with `TestGenuinelyUnknownEventStillWarns`
as the anti-vacuity control so the guard cannot pass by the default branch disappearing.

**So the loud statement Brian asked for is loud in the good direction: #332's approval trail is not
affected by #335, and #335 is not a `before-main` blocker for #332.**

### §H2 — (a) Scope: out of #332, and not a blocker. It is real work, ranked below.

Three items genuinely remain. Ranked by what they cost if left:

**(i) The contract test does not do what its own comment claims it does. — the one that matters.**

`publishedEventTypes` in `event_processor_audit_test.go:31` is a **hand-maintained Go string
slice**. Its comment says:

> *"Adding a producer without adding a case here must fail this test."*

**That claim is false.** Adding a producer and forgetting the Go `case` fails this test **only if
someone also remembers to add the string to this list** — and the person who forgot the case is the
same person who would have to remember the list. The test cannot catch the omission it names.

There are now **four independently-stated lists of event types**: `transaction-service/Constants.cs`,
`transfer-service/Constants.cs`, `user-service/Constants.cs`,
`authority-service/SharedIdentifiers.cs` (`Events.All`), the Go `switch`, and this test slice.
Each is internally coherent. **This is the exact shape this repo has now hit repeatedly — a defect
living in a seam between two independently-stated facts, with the tests green throughout because
each test asserts against the same side of the seam its author wrote.**

**It is also the exact shape of the failure ruled on this morning.** Turk's §B2.2 narrowing was
accepted on a written cost claim that was false. This test carries a written coverage claim that is
false. Both were catchable only because someone wrote the claim down. **The fix is the one #335
itself proposed as item 4: derive the list by reading the `Constants.cs` and `SharedIdentifiers.cs`
files from disk, rather than restating it in Go.** Precedent exists and works — `observabilityRoles.contract.test.ts`
parses `BankingRoles.cs` from Jest, and the §R7 seam test parses the shipped manifest. A Go test
reading four C# files with a regex is no harder.

Two conditions on that fix, both from precedent already recorded:
- **It must fail loudly, never skip, if a source file moves or a constant is renamed.** A contract
  test that quietly finds nothing to compare is worse than no test, because it reports green.
- **It must be tampered in both directions**: add a `.cs` constant with no Go case (must fail), and
  delete a Go case for an existing constant (must fail).

**(ii) Defect B — `account-opening-service` envelope and stream divergence. Unchanged, still real.**

Verified still present: `src/account-opening-service/app/events.py:8` writes to
`account-opening-events`, with flat XADD fields and `data` as a **JSON string**, where the Go
consumer requires a single `payload` field containing an envelope whose `data` is an object.

Latent today because nothing consumes that stream. **The hazard is the repair, not the state:** if
someone repoints `STREAM_NAME` to `banking-events` without changing the shape, every message fails
the `has no payload field` check, burns its retries and lands in `banking-events-dlq` — and the
account-opening lifecycle goes from *unaudited and quiet* to *unaudited and noisy*, which is worse
only in that it will be discovered during a demo. **Either align the envelope, or write down that
`account-opening-events` is deliberately a separate stream and give it a consumer.** Silence
between those two is what makes the wrong repair likely.

**(iii) The countable default branch.** The default arm logs `"Audit Unknown event type"` at WARN,
which reads as consumer noise rather than *an audited business event was dropped*. A metric
(`audit_unhandled_event_total{event_type}`) makes it alertable. **Lowest priority of the three, and
it becomes near-redundant once (i) lands** — a contract test that cannot be forgotten is a better
guard than an alert that fires after the fact. Keep it, but do not sequence it first.

**Ruling on scope: #335 is `release:before-main`, not `release:332`.** It is not in #332's scope —
the epic's own audit surface is covered and guarded. It is a `before-main` item because *"activity
that looks audited produces no audit record"* is a **LIE-class** defect by Brian's own test, and
LIE-class defects do not ship to `main`. But it blocks nothing on the current validation chain, and
**nothing in it may be sequenced ahead of reseed → fixtures → §7.1–7.7 → stage 1 → stage 2.**

### §H3 — (b) Owner and labels

**Recommended labels on #335:**

| Label | Value |
|---|---|
| `release:*` | **`release:before-main`** |
| `squad:{member}` | **`squad:turk`** |
| existing | keep `type:bug`; **remove `squad`** (the triage-inbox label) now that it is assigned |

**Owner: Turk.** Reasoning, since one owner for three items needs justifying:

- All three items are backend service-boundary work — a Go consumer, a Python publisher, and a
  cross-language contract test. That is Turk's surface.
- **He found Defect B originally**, and the seam-shaped-contract-test problem in (i) is the same
  class as the `EvidenceComplete` seam test he already built and correctly flagged as a deviation.
- **Do not split this across three people.** All three items are one seam. Splitting it produces
  three partial views of the same drift, which is how the drift got here.

**Sequencing for Turk, explicit, since he now holds four things:** stage-2 `quarantined` pin →
§B2.2 comment correction → #140 research (§G4) → #335. **#335 is last of the four.** If that is too
much for one person, the item to reassign is #335 item (ii), the Python publisher, which is
separable from (i) and (iii) — but (i) and (iii) must stay together.

### §H4 — One thing to change on the issue itself

**The issue body is now wrong in its most-read section.** It states the switch handles exactly two
cases and shows a code block that no longer exists. Anyone reading it will re-derive a fixed defect.

**Ask Turk to post a comment recording that Defect A is closed, with the commit and the guarding
test named, and to strike the stale code block** — rather than silently editing the body. The
original text is evidence of what was believed when it was filed, and this week has twice depended
on being able to read a claim as it was originally written.
