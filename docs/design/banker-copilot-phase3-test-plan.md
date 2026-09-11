# Banker Copilot — Phase 3 Test Plan

**Author:** Livingston (Tester/QA)
**Epic:** [#332 Banker Copilot](../epics/banker-copilot.md)
**Branch:** `squad/332-phase3-supervisor`
**Phase 1 plan:** [banker-copilot-phase1-test-plan.md](./banker-copilot-phase1-test-plan.md)
**Phase 2 plan:** [banker-copilot-phase2-test-plan.md](./banker-copilot-phase2-test-plan.md)
**Suites:**
- `src/banker-copilot-service.Tests/` (Python) — 298 passing, 0 skipped; blind-construction oracle, production attack, ledger.
- `src/authority-service.Tests/` (.NET, net10.0) — 224 passing, 0 skipped; batch, role-divergence, supersede.

> Written from the SPEC while Turk, Rusty, and Linus were coding the same branch
> in parallel. Nothing below was derived from their implementation; a test that
> merely agrees with the code it is meant to check is the exact failure mode this
> whole exercise exists to catch. Where production code for a Phase 3 affordance
> does not exist yet, that is a **failing ledger entry**, never a green tick.

---

## 0. How this plan is built

### 0.1 The invariant, restated for Phase 3

> **Agents never approve.** Every state-changing action carries a human
> signature. Thresholds govern **how many** humans sign and **how senior** —
> never **whether** a human signs.

Phase 3 adds the supervisor agent, subagent fan-out, and the L2 co-signature
window. Each is a new surface on which the invariant could be defeated *without
anyone deciding to defeat it*. The headline is **blind construction
independence**: a supervisor agent that silently reads the proposer's conclusion
is not a second opinion, it is an echo — and an echo that "co-signs" is one
identity signing twice.

### 0.2 Structural over behavioural — prove independence by what was *handed over*

The brief is explicit: a test that checks the supervisor was *told* to ignore the
proposer ("please disregard the above") proves nothing, because an instruction is
not a barrier. So the primary defence is **structural**: the function that builds
the supervisor's input, `build_supervisor_input(intent)`, takes **only** the
banker's intent. The proposer's plan, reasoning, and conclusion are not
parameters — there is no argument for them to travel through. This is the same
technique that made Phase 1's `ExecuteAsync` safe by taking no payload parameter:
a leak that cannot be *named* cannot be *passed*.

The behavioural token-scan (`independence_report`) is a **cross-check**, not the
proof. It intersects the bytes of the proposer's private reasoning with
everything the supervisor was actually spawned with and asserts the intersection
is empty — and it is guarded by a positive control that proves the scan can go
red, so an empty corpus cannot pass it vacuously (learning #1).

### 0.3 Every criterion carries its false pass

Each case below names the specific way it can go green while proving nothing.
The five Phase-1/2 false passes and the CI family that followed
(machine-pinned security tests, an ownership check with no test, an
ambient-`AZURE_CLIENT_ID` suite) all share one root: a test that **cannot fail**,
or one whose outcome reports the **developer's shell** rather than the code.
Mutation/tamper testing catches the first class. It does **not** catch a test
that asserts the *wrong thing* (Phase 1's `ProductionRoleModelTests`, which
defended the vulnerable model). Spec-derivation is the only guard against that,
which is why this plan was written before the code.

### 0.4 Coverage is not tracked

Per Brian's ruling, there are **no coverage metrics** anywhere in this phase —
not gathered, not reported. Coverage was green across all five tests that could
not fail for the right reason. Every guard here is proven by **tamper**: break
it, watch a *named* test go red, revert. A guard that was not tamper-tested is
not proven, and is listed as a non-tick in §4.

### 0.5 Pending work fails; it never skips

`pending-integration.manifest.json` + `test_integration_ledger.py` carry over.
The Phase 3 entry `phase3-supervisor-blind-construction` fails in both
directions: while the production fan-out planner is absent the dependency marker
must still be absent, and the day it appears the ledger entry must be promoted to
a real integration test and deleted. No `skip` markers exist; a self-check
enforces it.

---

## 1. Priority 1 — Blind construction independence (the headline)

**Suite:** `src/banker-copilot-service.Tests/` · oracle `spec/supervisor.py` ·
tests `tests/test_blind_construction.py` (14 cases).

The oracle models the harness the way §6.4 specifies it: a `SupervisorAgent`
with its **own transport**, a `Harness.second_opinion_for(intent)` that builds
the supervisor's input from the intent alone, and `subagent_tool_ids` that a
fanned-out child inherits.

| # | Property (spec) | Case | False pass it guards |
|---|---|---|---|
| 1.1 | The builder cannot receive the proposer's output | `build_supervisor_input` has exactly one parameter, `intent` | A test that reads a docstring saying "independent" — proves intent, not structure |
| 1.2 | No leak field on the input type | `SupervisorInput` has no field carrying primary reasoning/plan/conclusion | Asserting a value is *ignored* while it still rides along in a field |
| 1.3 | Byte-level independence | `independence_report` ∩ (primary tokens, supervisor spawn bytes) = ∅ | **Empty corpus** — guarded by 1.4 |
| 1.4 | The scan can fail | Positive control feeds a known leak and asserts the scan reports it | A scan that always returns ∅ (the `_by_id` class of dead assertion) |
| 1.5 | Agreement is *computed*, not *read* | supervisor's verdict derives from re-derivation, never from `primary.conclusion` | Reading the proposer's answer and calling the match "agreement" |
| 1.6 | Disagreement does not block | a divergent second opinion still routes to the human; it does not deny | An agent that "vetoes" — agents never approve *or* deny |
| 1.7 | Own transport | the supervisor reads facts through its own client, not a shared cache | A shared context object that backdoors the proposer's tool results |
| 1.8 | Artifact/intent smuggle | neither the artifact nor the intent may carry primary conclusion bytes | A "facts" blob that is actually the proposer's writeup |
| 1.9 | Subagent never proposes | a fanned-out child's tool ids never include `propose_action` (§6.3) | A child that inherits propose authority and reaches L2/L3 |

**Tamper results (Python harness, all PROVEN):**

- `blind-builder-signature` — give `build_supervisor_input` a second parameter for
  the primary result → 1.1 red.
- `blind-token-scan` — make `independence_report` return ∅ unconditionally → 1.3/1.4 red.
- `blind-subagent-propose-floor` — let a subagent inherit `propose_action` → 1.9 red.

### 1a. Proven against the SHIPPING harness, not only the oracle

Turk's production `app/planner/fanout.py` **landed during this session**, so the
oracle proof is no longer the whole story. `tests/production/test_supervisor_blind_construction.py`
(5 cases) imports the real module and re-runs the structural attack against it,
deriving expectations from §6.4, not from Turk's field set:

- the shipping `build_supervisor_input` signature admits only `intent` — and has no
  `*args`/`**kwargs` backdoor;
- passing a real `PrimaryResult` positionally is a `TypeError`;
- the shipping `SupervisorInput` dataclass exposes no field named for, or typed as,
  a primary channel;
- no distinctive primary token survives into the real `serialize()` bytes, with a
  positive control proving the scan is not vacuous.

**Tamper results (production `fanout.py`, PROVEN):** `prod-blind-builder-signature`
(add a `primary=None` parameter → signature and TypeError cases red);
`prod-blind-input-leak-field` (add a `recommendation` field to the shipping
`SupervisorInput` → field-set case red). Turk's builder matches the oracle
name-for-name and passes both the independent attack and the tamper.

---

## 2. Priority 2 — Separation of duties, re-attacked from the loader

**Suite:** `src/authority-service.Tests/` · `Engine/RoleModelDivergenceTests.cs` (7 cases).

The existing `Engine/SeparationOfDutiesTests.cs` attack the signature **store**
(two humans, one identity, admin at the slot). This suite attacks one rung lower:
Turk's **fail-closed cross-file check** between the shipping `authority-policy.yaml`
and the ratified `role-hierarchy.yaml`. That check exists because the two Phase 1
escalations were each internally coherent and invisible alone — my
`banker.claimValues` contained `user`, and the coordinator's `admin` sat above
supervisor and inside `L2.cosignerRoles`. Both original attacks are re-run here
against the real config.

Every case tampers the **real shipping YAML** (never a fixture) and every case is
preceded by a positive control (`The_shipping_policy_and_the_ratified_hierarchy_agree`)
proving the untampered pair loads clean — so a green result means *the tamper is
what broke it*, not that the baseline was already broken (the wrong-reason false
pass).

| # | Attack | Case | Guard exercised |
|---|---|---|---|
| 2.1 | Retail claim mapped onto a banking role | `A_customer_claim_mapped_onto_banker_is_refused` | `claimValues` may only spell its own role |
| 2.2 | admin fully wired as an L2 co-signer | `Admin_added_to_the_L2_cosigner_list_is_refused` | seniority floor: signer/cosigner roles need banking seniority ≥ 1 |
| 2.3 | admin as an L1 signer | `Admin_added_to_an_L1_signer_list_is_refused` | undeclared-role **and** seniority-floor, either sufficient |
| 2.4 | Re-encode the vulnerable model | `A_signer_role_that_restates_its_own_seniority_is_refused` | inline `seniority:` under a signer role is refused (learning #2) |
| 2.5 | Exposure boundary | `If_the_ratified_ladder_gives_admin_banking_seniority_the_floor_no_longer_protects` | documents F3-2 (below) rather than pretending the loader closes it |
| 2.6 | Ladder tripwire | `The_ratified_ladder_keeps_admin_at_platform_zero_implying_nothing` | pins admin seniority 0 / implies nothing, in the *correct* direction |

2.2, 2.3 and 2.4 wire admin as a **first-class signer role** before attacking, so
the guard actually reached is the seniority floor — not the shallower
"undeclared role" check that trips first on a half-wired tamper. That was found by
watching the tests fail with the wrong message and correcting the tamper, not the
assertion.

**Tamper results (production `PolicyLoader.cs`, all PROVEN):**

| Guard broken | Test that went red |
|---|---|
| seniority floor `SeniorityOf(role) < 1` → `false` | `Admin_added_to_the_L2_cosigner_list_is_refused` |
| claim-spelling check → `false` | `A_customer_claim_mapped_onto_banker_is_refused` |
| ladder tripwire (bump admin seniority 0→3 in `role-hierarchy.yaml`) | `The_ratified_ladder_keeps_admin_at_platform_zero_implying_nothing` |

---

## 3. Priority 3 — L2 batching is impossible, not merely absent

**Suite:** `src/authority-service.Tests/` · oracle `Spec/BatchSigner.cs` ·
tests `Store/BatchApprovalTests.cs` (8 cases).

Batch approval is L1-only within one action type (invariant I-10). The oracle
`BatchSigner.SignBatch` is **fail-closed and all-or-nothing**: it refuses the
*whole* batch if any item's **resolved** rung is not L1, or if items span more
than one action type. It keys on `RequiredRung` (resolved), never `BaseRung` —
an L1 base action that *escalated* to L2 must still take the batch down.

| # | Property | Case | False pass it guards |
|---|---|---|---|
| 3.1 | A clean L1 same-type batch signs | `A_batch_of_two_L1_items_of_one_action_type_signs` | non-vacuity: the happy path must exist |
| 3.2 | An escalated item voids the batch | `A_batch_containing_an_L1_base_action_that_ESCALATED_to_L2_is_refused_whole` | keying on `BaseRung` — passes while admitting an escalated item |
| 3.3 | Keying is on resolved rung | `A_batch_keys_on_required_rung_not_base_rung` | as 3.2, stated directly |
| 3.4 | Cross-type batch refused | `A_batch_that_spans_two_action_types_is_refused` | "Approve All" with extra steps |
| 3.5 | Shipping config caps at L1/same-type | `The_shipping_policy_caps_batches_at_L1_within_one_action_type` | reads the **real** config, not a fixture |
| 3.6 | Loader refuses `maxRung: L2` | `The_loader_refuses_a_batch_cap_of_L2` | production I-10 guard, on the shipping validator |
| 3.7 | Loader refuses cross-type default | `The_loader_refuses_a_cross_action_type_batch_config` | as 3.6 |
| 3.8 | **F3-1 tripwire** | `No_shipping_action_is_both_batchable_and_above_L1` | empty-corpus vacuum — guarded by an explicit anchor on the two shipping L2 actions |

**Tamper results (all PROVEN):**

| Guard broken | Test that went red |
|---|---|
| oracle keys on `BaseRung` not `RequiredRung` | `A_batch_containing_an_L1_base_action_that_ESCALATED_to_L2_is_refused_whole` |
| production `defaults.batchApproval.maxRung != "L1"` → `false` | `The_loader_refuses_a_batch_cap_of_L2` |
| production `!SameActionTypeOnly` → `false` | `The_loader_refuses_a_cross_action_type_batch_config` |
| add `batchable: true` to `transaction.score.override` (L2) in real config | `No_shipping_action_is_both_batchable_and_above_L1` |

---

## 4. Priority 4 — `terminalReason` and the payload-supersede void path

The four-value closed enum, its wire round-trip, fail-closed on an unknown value,
the metric buckets, and `supersededByApprovalId` linkage are **already covered**
by `Store/TerminalReasonTests.cs` and the `ApprovalStore` oracle. The
never-auto-downgrade path is covered by `Engine/ReEvaluationGateTests.cs`
(`Relaxation_while_pending_honours_the_signature`, `Escalation…voids…`,
`An_escalation_to_L3_refuses_entirely`). I did **not** duplicate those.

The **fresh Phase 3 angle** is the L2 co-signature window:
`Store/SupersedeSignatureVoidTests.cs` (2 cases).

The existing supersede test supersedes an approval that was **never signed**, so
its claim "a replan starts from zero signatures" is only lightly exercised —
there was no signature to lose. The attack that matters in Phase 3: an agent
obtains the **first** human co-signature on an L2 action, then mutates the
payload and asks for the second. If any prior signature survived the mutation,
the proposer would have smuggled an unsigned change past a real human.

| # | Property | Case | False pass it guards |
|---|---|---|---|
| 4.1 | No signature survives a replan | `A_first_L2_signature_does_not_survive_a_payload_replan` | supersede with **no** prior signature — the vacuous version of this claim |
| 4.2 | The successor still demands two signers | `The_replanned_L2_approval_still_demands_two_independent_signatures` | a replan that silently drops to L1 or a single slot — an auto-downgrade dressed as a payload edit |

4.1 fills a real slot first, asserts it was filled (non-vacuity), asserts the
hash actually changed (the mutation is real), then asserts **no** replacement
slot is filled and none references the first signer.

**Tamper result (oracle, PROVEN):** make `SupersedeByReplan` inherit the
superseded approval's `SignatureSlots` → `A_first_L2_signature_does_not_survive_a_payload_replan`
goes red while the two-slots test stays green (correctly — it does not assert
fill state).

---

## 5. Priority 5 — Adversarial review

Phase 2 closed F2-7 (path-parameter traversal reachable by prompt injection) and
covered injection via tool output. Phase 3's injection surface is the **agent
boundary**, and the blind-construction suite already attacks it structurally:

- Injection that tries to make the supervisor *read* the proposer's conclusion
  has nowhere to land — the input builder takes only the intent (§1.1–1.2, 1.8).
- Injection that tries to flip the second opinion into agreement is defeated by
  agreement being **computed, not read** (§1.5).
- Injection that tries to make a subagent *propose* (reaching L2/L3) is refused
  by the subagent propose-floor (§1.9) and, at the tool boundary, by Phase 2's
  `propose-refuses-execute` / reserved-`propose_action`-id guards (still PROVEN
  this round).

I did **not** invent a redundant new injection test where an existing structural
guard already makes the attack unrepresentable. Adding one would be a guard with
a spare (§0.2 of the Phase 2 plan).

---

## 6. Findings

### F3-1 — I-10 is enforced globally, not per-action *(latent, medium)*

The loader enforces "batch is L1-only" **only** through the global
`defaults.batchApproval.maxRung: L1` cap. It does **not** reject a per-action
`batchable: true` on an action whose `baseRung` is L2 (e.g.
`transaction.score.override`, `user.unlock`) or on an L1 action whose rules
escalate it to L2. I proved this empirically: adding `batchable: true` to
`transaction.score.override` loads **without error**.

It is **latent today** — no action sets `batchable`, and no batch-sign endpoint
exists — so I did **not** write a test asserting the loader rejects it. That
would be a false pass defending a gap that is not closed. Instead
`No_shipping_action_is_both_batchable_and_above_L1` pins the shipping config: the
day someone marks an L2 action batchable, it goes red and forces the loader fix.
**Recommended fix (Turk):** in `PolicyLoader.Validate`, reject any action with
`Batchable == true` whose resolved rung can exceed L1.

### F3-2 — the seniority floor trusts the ratified ladder *(exposure, low, by design)*

The loader's "signer/cosigner roles need banking seniority ≥ 1" floor consumes
`role-hierarchy.yaml`; it does not independently pin `admin` to platform-only. If
a future edit to `role-hierarchy.yaml` gave `admin` banking seniority ≥ 1, the
loader would **accept** admin in a cosigner slot and dual control would collapse
— the Phase 1 shape, one file upstream. This is by design (this service consumes
the ladder, it does not ratify it), and it is demonstrated by
`If_the_ratified_ladder_gives_admin_banking_seniority_the_floor_no_longer_protects`
and pinned by `The_ratified_ladder_keeps_admin_at_platform_zero_implying_nothing`.
It is not a bug to fix here; it is a boundary to know about. The ratified file is
the control, and it now has a tripwire.

---

## 7. Honest non-ticks — what I could NOT verify

- **Production fan-out landed mid-session and is verified — but only the builder.**
  Turk's `app/planner/fanout.py` now exists, so the earlier "no production code"
  non-tick is resolved for the blind-construction *builder*: it is proven by an
  independent structural attack and tamper-proven (§1a). What is **not** yet proven
  end-to-end is the full fan-out engine under a real model — the loop that actually
  spawns the supervisor thread, gathers its own evidence, and returns a second
  opinion — because no Foundry endpoint runs here. The `real-model-tool-choice`
  ledger entry still covers that gap.
- **No batch-sign endpoint exists.** The batch tests prove the oracle and the
  loader/config. There is no production `POST /approvals/batch` to attack, so the
  end-to-end "one signer, N items, all L1" flow is unproven against real code.
- **No .NET tamper harness.** The Python `tamper-test.py` only tampers Python
  files. The seven .NET guards in this phase were tamper-proven **manually**
  (break the guard, run the named test, confirm red, revert), documented in §2–§4.
  This is reproducible but not automated; a `dotnet`-side tamper runner would be
  worth building and is not in scope this phase.
- **F3-1 is latent, not closed.** I pinned it; I did not fix it. If a batchable
  action or a batch endpoint lands before Turk closes the loader gap, the
  tripwire will fire but a real exploit path could open in the same PR.
- **No CI wiring verified this phase.** Phase 2 found the CI ran this suite before
  its dependencies existed (F2-9) and that the quarantine patterns matched nothing
  (F2-10). I did not re-audit CI this phase; treat those as still open until the
  coordinator confirms otherwise.

---

## 8. Running it

```bash
# Python — blind construction, ledger, tamper harness
python -m pytest src/banker-copilot-service.Tests/ -q          # 298 passed, 0 skipped
python src/banker-copilot-service.Tests/tamper-test.py         # 22 PROVEN

# .NET — batch, role divergence, supersede (net10.0)
dotnet test src/authority-service.Tests/authority-service.Tests.csproj   # 224 passed, 0 skipped
```
