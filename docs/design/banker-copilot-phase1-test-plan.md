# Banker Copilot — Phase 1 Test Plan

**Author:** Livingston (Tester/QA)
**Epic:** #332 — Banker Copilot
**Branch:** `squad/332-banker-copilot`
**Status:** Phase 1. 209 tests written and passing; 15 guards tamper-proven; 9 test areas pending integration.

---

## 0. The invariant under test

> **Agents never approve.** Every state-changing action carries a human signature. Thresholds
> decide *how many* humans sign and *how senior* — never *whether* a human signs.

Every test in this plan exists to attack that sentence. The organising question is not "does the
code do what it says" but "is there any sequence of inputs, timings or configurations under which
a write executes without a valid human signature at the correct rung".

### 0.1 Why this document leads with false passes

A test suite for an authorisation system fails in a characteristic way: it goes green because it
never reached the code it claims to check. The invariant is a *negative* — no path exists — and
negatives are exactly what a passing test is worst at establishing.

This happened three times while writing this suite, each time caught only by a redundant guard:

1. **The empty-evidence vacuum.** `Every_admissible_action_requires_at_least_one_human` iterated
   over zero actions, because the evaluator returns `UnderEvidenced` before any policy maths and
   my contexts carried no evidence. The loop was empty and the test was green. Only an explicit
   `admissible.Should().BeGreaterThan(0)` exposed it.
2. **The unreachable counter-example.** The monotonicity property test over the real policy
   stayed green when I replaced the rung combinator with last-writer-wins, because every
   escalator in the shipping policy uses `raiseBy: 1` — under an always-ascending rule set,
   "max" and "last" are the same number. The property was true of the data, not of the code.
3. **The unobserved guard.** Disabling the negative-`raiseBy` load-time check changed nothing in
   a 184-test run. The guard was correct, load-bearing, and completely untested.

None of these would have been visible in a green build, in a coverage report, or in review. So
every criterion below carries a **false-pass** row: the specific way that test could report
success while the property it names is broken. Where a false pass is plausible, there is a named
anti-vacuous guard.

### 0.2 Structural proof over behavioural proof

Where possible, a property is made **unrepresentable** rather than merely checked:

| Property | Behavioural test | Structural equivalent used here |
|---|---|---|
| A `denied` record always has a reason | reject writes with a null reason | `TerminalTransition` has a positional required `Reason`; `Approval.Status` is *derived*, so a reasonless denial cannot be constructed |
| Execution only via the gate | assert the gate was called | `ExecutionAuthorization` has a private constructor and only the nested `ReEvaluationGate` can mint one; `Execute` requires the token |
| Execute cannot use a mutated payload | compare hashes on the way in | `ExecuteAsync` takes **no payload parameter** — there is no input for a mutation to arrive through |
| Escalators cannot lower a rung | test many combinations | the grammar rejects a negative `raiseBy` at load time, so a downgrade does not parse |

A structural violation fails to **compile**. That is a much stronger statement than a red test,
and it is the honest answer to "how do you assert the absence of a path?" — you make the path
unconstructible and then assert the construction still fails.

---

## 1. What actually runs today

**209 tests, all passing**, in `src/authority-service.Tests/` (net10.0, xUnit).

| Area | File | Tests | Runs against |
|---|---|---|---|
| Rung monotonicity (property) | `Engine/MonotonicityPropertyTests.cs` | 6 | reference model |
| Re-evaluation gate, both directions | `Engine/ReEvaluationGateTests.cs` | 6 | reference model |
| Payload hashing / canonicalisation | `Engine/PayloadHashTests.cs` | 30 | reference model |
| Separation of duties | `Engine/SeparationOfDutiesTests.cs` | 10 | reference model |
| Policy grammar validation | `Engine/PolicyGrammarValidationTests.cs` | 11 | reference model |
| No-bypass path (structural) | `Store/NoBypassPathTests.cs` | 9 | reference model |
| TTL expiry and the sweeper | `Store/TtlExpiryTests.cs` | 12 | reference model |
| `terminalReason` | `Store/TerminalReasonTests.cs` | 13 | reference model |
| Denial reason validation | `Store/DenialReasonValidatorTests.cs` | 15 | reference model |
| Shared identifiers | `Contracts/SharedIdentifierContractTests.cs` | 12 | the specs and the repo |
| `policyVersion` binding | `Contracts/PolicyVersionBindingTests.cs` | 9 | reference model |
| Repo gates (§10 grep criteria) | `Contracts/RepoGateTests.cs` | 7 | **the repo** |
| Integration ledger | `Contracts/IntegrationReadinessTests.cs` | 7 | **the repo** |
| Real policy engine | `Production/ProductionPolicyEngineTests.cs` | 8 | **production** |
| Rung combinator | `Production/RungCombinatorTests.cs` | 7 | **production** |
| Architecture / structure | `Production/ProductionArchitectureTests.cs` | 8 | **production** |
| Denial validator | `Production/ProductionDenialReasonTests.cs` | 17 | **production** |
| Role model | `Production/ProductionRoleModelTests.cs` | 10 | **production + user-service** |

### 1.1 The reference model, and its honest limitation

Most of this suite was written before `authority-service` existed. Rather than write pseudocode,
I built a **spec-derived reference implementation** in `Spec/` — an executable oracle for the
lifecycle, canonicalisation, hashing, gate and store described in the epic and design docs.

**What it is good for:** it makes the specification executable, so ambiguities surface as
compile errors and contradictions surface as failing tests. It found three genuine specification
gaps before any production code existed.

**What it is not:** it is not evidence about Turk's code. A green reference-model test proves the
*specification* is coherent, not that the service implements it. This distinction is load-bearing
and I have kept the two in separate directories so it cannot be blurred: `Spec/` + `Engine/` +
`Store/` are the oracle; `Production/` is the only thing that can fail because of someone else's
code.

The `IPolicyEvaluator` seam exists so that oracle suites can be re-pointed at the production
engine as differential tests. That migration is **partially done** — the monotonicity property
now runs against the real engine — and is the highest-value remaining work.

---

## 2. §10 acceptance criteria → test cases

Each row: what is asserted · what a failure means · **what a false pass looks like**.

### AC-1 · Property-based test proving no escalator combination can lower a rung

| | |
|---|---|
| **Tests** | `MonotonicityPropertyTests` (6, oracle) · `ProductionPolicyEngineTests.No_combination_of_real_escalators_can_lower_a_rung` · `RungCombinatorTests` (7, production) |
| **Asserted** | Over the full power set of escalators, adding any escalator never lowers the rung, the signer count, the distinct-identity count or the seniority bar. Order-independence (commutativity) is asserted separately. Load-time grammar rejects a negative `raiseBy`/`minSigners`/`minSeniority`. |
| **Failure means** | A combination of ordinary conditions produces *less* scrutiny than a subset of them — an attacker adds a risk factor to reduce oversight. This is the deepest possible break of the invariant: the ladder inverts. |
| **False pass** | **Observed, twice.** (a) The generator cannot reach a counter-example: with every escalator using relative `raiseBy: 1`, last-writer-wins is numerically identical to max, so the property holds for reasons unrelated to the code. (b) Fact-merging drops a shared fact when escalators combine, so the added escalator never fires and monotonicity holds vacuously. |
| **Guard** | `TestPolicies/descending-escalators.yaml` supplies absolute `raiseTo` escalators in *descending* declaration order — the input the production policy cannot express — loaded through the **real** `PolicyLoader` and run through the **real** evaluator. `Merge()` unions list-valued facts and throws on scalar collision. `comparisons.Should().Be(12)` proves the power-set loop ran. |

> **Finding:** monotonicity is protected *twice* in production — the outer `rung = Max(rung, raised)` fold and the inner `var result = current` in `Raised()`. Each independently prevents a descent, so **breaking either alone is undetectable**. Only the simultaneous break is observable, and the fixture catches that. This is genuine defence in depth, but it means a single-point regression here is silent, and the redundancy should be deliberate rather than accidental.

### AC-2 · Payload mutation after signature voids the signature

| | |
|---|---|
| **Tests** | `PayloadHashTests` (30) — mutation theory over every hashed field, removal, money formatting, sub-cent distinctness, float rejection, explicit-null ≡ absent, NFC normalisation, key order, array order, domain separation, slot/approval replay |
| **Asserted** | Changing *any* declared `hashField` after signature produces a different `payloadHash`, so the prior signature no longer verifies. Fields outside `hashFields` are deliberately ignored. |
| **Failure means** | An agent signs a $50 transfer and executes a $50,000 one. |
| **False pass** | **Observed (F-2/F-3).** (a) The gate re-hashes the *stored* payload and compares it to itself — a tautology that passes for every input. (b) `Canonicalizer.Project` exempts money fields from the missing-declared-field error, so removing `amount` matches rather than voids — the worst possible exemption, and invisible because the test only ever *changed* fields, never removed them. |
| **Guard** | `An_end_to_end_mutation_is_caught_at_the_gate_not_merely_by_the_hash_function` hashes the payload **presented for execution**. `The_hashed_field_set_itself_is_asserted_because_every_other_test_depends_on_it` pins the field set, so a shrinking `hashFields` list fails loudly instead of quietly reducing coverage. |
| **Production status** | ⚠️ See finding **F-2** in §4. `ApprovalService.VerifyStoredHash` recomputes from `approval.Payload`. The real control is that `ExecuteAsync` accepts **no payload**, asserted structurally by `The_execute_entry_point_accepts_no_caller_supplied_payload`. |

### AC-3 · Policy escalation while pending voids the signature

| | |
|---|---|
| **Tests** | `ReEvaluationGateTests` · `NoBypassPathTests.A_retry_after_a_failed_execution_re_enters_the_gate_and_is_voided_by_a_tightening` |
| **Asserted** | Sign at L1 → tighten policy to L2 → execute is refused, approval goes terminal `denied` + `POLICY_RUNG_ESCALATED`, the discarded signature is recorded in full, and a replacement is linked by `supersededByApprovalId`. |
| **Failure means** | A signature collected under a weaker rule set is honoured after the rule tightened — the policy update is cosmetic for everything already in flight. |
| **False pass** | The test tightens the policy but the gate reads the **stored** decision rather than re-evaluating live, so it "detects escalation" by comparing a value to itself. Also: asserting only `status == denied` without asserting `terminalReason`, which would pass identically for a TTL expiry that happened to fire during the test. |
| **Guard** | The gate is driven from a **freshly loaded** policy and a rebuilt context; the assertion covers status, `terminalReason`, the recorded discarded signature (signer, slot, rung satisfied, bound `policyVersion`) and the supersede link together. |

### AC-4 · Policy relaxation while pending does NOT void

| | |
|---|---|
| **Tests** | `ReEvaluationGateTests` — relaxation honoured; L3-absolute case; unchanged policy; cosmetic edit |
| **Asserted** | Sign at L2 → relax policy to L1 → the existing signature is honoured and the action executes. |
| **Failure means** | Either the asymmetry is lost (relaxation also voids — safe but wrong, and it would make every policy edit a mass-cancellation event), or worse, the gate auto-*downgrades* an under-signed action. |
| **False pass** | The relaxation test passes because the action was **already fully signed for the lower rung**, so no re-evaluation logic was exercised at all. It would pass with the gate removed entirely. |
| **Guard** | `An_under_signed_approval_cannot_execute_even_if_the_policy_later_relaxes` is the paired negative: relaxation must honour an *adequate* signature without ever manufacturing a *missing* one. **Brian's rule — test both directions or you have tested neither — applies within this criterion too, not just across AC-3/AC-4.** |

### AC-5 · No path from `signed` to `executed` bypasses the re-evaluation gate

**The criterion most likely to pass vacuously,** because it asserts the *absence* of a path and
the natural test asserts the *presence* of a check. "The gate ran" is compatible with "and also
three other things call the broker directly".

Four independent angles:

1. **Structural (oracle).** `ExecutionAuthorization` has a private constructor; the only minter
   is the nested `ReEvaluationGate`; `ApprovalStore.Execute` requires the token. A bypass does
   not compile. `ExecutionAuthorization_has_no_publicly_reachable_constructor` asserts the shape
   by reflection so a future `public` slip fails here.
2. **Ordering (production).** `The_re_evaluation_call_precedes_the_downstream_call_in_the_execute_path`
   asserts on the source of `ExecuteAsync` that `ReEvaluate` appears before `_broker`. Unit tests
   observe outcomes, never order — and a gate that runs after the money moves is not a gate.
3. **Single writer (production).** `Only_the_write_guard_may_replace_an_approval_document` scans
   for `ReplaceItemAsync`/`UpsertItemAsync`/`PatchItemAsync` outside the repository. One stray
   Cosmos call routes around every ordering guarantee in one line.
4. **Behavioural.** Retry-after-failure re-enters the gate and is voided by a tightening; a voided
   approval replayed five times never proceeds; a signed-but-expired approval is refused.

| **False pass** | A mock `IPolicyEvaluator` returns the same decision every time, so the gate "passes" without comparing anything; or the test asserts `evaluator.Verify(...)` was called, which proves a call happened, not that its result gated anything. |
| **Guard** | The gate outcome is asserted through observable *state* (`VoidPolicyEscalated`, `RefuseQuorum`, `RefuseHashMismatch`, `RefuseTtlExpired`), never through a call-count assertion. |

> **Not yet covered:** there is no HTTP-level test proving the *route* has no second entry point.
> The structural tests cover the service class; a controller action that called the broker
> directly would be caught by angle 3 only if it used a Cosmos verb. **Recorded as pending.**

### AC-6 · Separation of duties — L2 requires two distinct identities

| | |
|---|---|
| **Tests** | `SeparationOfDutiesTests` (10, oracle) · `ProductionRoleModelTests.L2_requires_two_distinct_identities_so_no_single_person_can_satisfy_it` |
| **Asserted** | The same human cannot fill both L2 slots; the requester may hold slot 0 but can never co-sign; step-up auth / a second `jti` from the same human does not satisfy slot 1; `mustDifferFrom` cannot be emptied by any escalator combination; an agent identity cannot sign at all. Asserted **server-side**, never through the UI. |
| **Failure means** | Two signatures become one signature typed twice. Dual control is decorative. |
| **False pass** | Asserting the *rung config* says `distinctIdentities: 2` rather than asserting the *engine* rejects the second signature. Config is a claim; enforcement is a behaviour. |
| **Guard** | A positive control (two genuinely distinct humans **succeed**) sits beside every rejection test — otherwise an engine that rejects *all* second signatures passes every negative test while making L2 unsatisfiable. |
| **⚠️ Mid-flight change** | `distinctIdentities` was **retired** during this session (Danny, 2026-09-04). SoD now lives in `signatureSlots[].mustDifferFrom`, and the loader **rejects** a policy still declaring the old key — the right call, since a dead knob an operator can set to `1` and believe they relaxed dual control is worse than no knob. Tests were rewritten to assert on emitted slots. **The count is now derived, not declared**, which is stronger: an empty `mustDifferFrom` on a co-signer slot fails immediately. |

### AC-7 · `admin` implies neither `banker` nor `supervisor`

| | |
|---|---|
| **Tests** | `ProductionRoleModelTests` (10) · `SeparationOfDutiesTests` — one admin cannot fill both L2 slots |
| **Asserted** | `admin` does not appear in the `claimValues` of the `banker` or `supervisor` signer roles; `supervisor` does not grant `admin`; L3 is admin-only and not proposable; the L2 co-signer set is strictly narrower than the L2 signer set; an unknown role carries seniority `0`. |
| **Failure means** | §5.8.2 verbatim: *"a single admin identity could satisfy both signatures on an L2 approval — and separation of duties evaporates while every test still passes."* |
| **False pass** | Testing role *names* rather than role *mappings*. `admin` can be absent from the ladder while `administrator` — a `claimValue` on the same role — is present. The test must walk the claim-value map, not the role list. |
| **Guard** | Assertions run over `claimValues` case-insensitively and include the `administrator` spelling. |

### AC-8 · TTL expiry produces `denied` + `TTL_EXPIRED` and never executes

| | |
|---|---|
| **Tests** | `TtlExpiryTests` (12) · `ProductionArchitectureTests.No_approval_container_is_configured_with_a_cosmos_ttl` |
| **Asserted** | TTL read from config, never a literal; expiry writes `denied` + `TTL_EXPIRED`; no `expired` status exists; an expired-but-signed approval never executes; **expiry is checked before quorum**; a late signature is rejected even if the sweeper has not yet run; boundary behaviour at and one tick before expiry; the sweeper is idempotent and will not overwrite an existing `HUMAN_DENIED`; only past-TTL approvals are swept; there is no `Reopen` verb. |
| **Failure means** | Silence reads as consent. I-6 inverted. |
| **False pass** | **The most dangerous in this document.** If the sweeper is the *only* mechanism, a test that advances the clock and then calls the sweeper proves nothing about the window *before* the sweep. An approval expired-but-not-yet-swept is exactly what an attacker races. |
| **Guard** | `A_late_signature_is_rejected_even_though_the_sweeper_has_not_run` asserts **lazy** expiry at the read path independently of the sweeper. Production has `ApplyLazyExpiryAsync` as step 2 of `ExecuteAsync`, before the status check — verified by reading the ordered gate. |
| **Also** | Cosmos TTL must never be the mechanism: losing the record is not the same as denying the request. Asserted against `infra/cloud/cosmos.tf`. |

### AC-9 · `terminalReason` is mandatory on every `denied`

| | |
|---|---|
| **Tests** | `TerminalReasonTests` (13) · `ProductionArchitectureTests.There_are_exactly_four_terminal_reasons` |
| **Asserted** | A reasonless `denied` **cannot be constructed**; `denied ⟺ reason` in both directions; the enum is closed at four; wire round-trip is stable; seven unknown wire values fail closed; no id is embedded in the value (`supersededByApprovalId` is a separate field); terminal documents are immutable and there is no `denied → proposed` edge; every store verb writes a reason. |
| **Failure means** | A denial with no explanation. #333 loses its only corpus of labelled agent misjudgement, and "why was the agent wrong?" becomes unanswerable. |
| **False pass** | Testing that the *API* rejects a null reason while the *model* still permits one. The criterion says "rejected by the model, not caught by a code review" — an API-level test passes while a background job, a migration or a repair script writes a reasonless denial. |
| **Guard** | Structural: `TerminalTransition` takes `Reason` as a positional required parameter and `Approval.Status` is **derived** from the transition. There is no state in which a reasonless denial exists to be validated. Tamper-proven: adding a default value to `Reason` fails to **compile**. |

### AC-10 · No consumer aggregates across `terminalReason`

| | |
|---|---|
| **Tests** | `TerminalReasonTests` — 40-escalation burst does not move the human denial rate; distinct metric buckets; `TTL_EXPIRED` excluded from denial-rate metrics |
| **Asserted** | `CountsTowardDenialRate()` and `MetricBucket()` separate machine-generated terminal reasons from human judgement. |
| **Failure means** | A policy change or a broken notification sink reads as "the agent is getting worse", and someone tunes a model against noise. |
| **False pass** | The metric is computed *in the test* rather than by the production aggregation, so the test proves its own arithmetic. |
| **Status** | ⚠️ **Oracle-only.** Production metric emission is not yet reachable. **Pending.** |

### AC-11 · One `policyVersion`, byte-identical everywhere

| | |
|---|---|
| **Tests** | `PolicyVersionBindingTests` (9) · `ProductionPolicyEngineTests.The_policy_version_is_stable_across_loads_and_moves_when_a_threshold_moves` |
| **Asserted** | Shape `^pv1:[0-9a-f]{16}$`; derived from the **resolved** policy, not file bytes, so an env override that leaves the file identical still produces a new version; stable across 20 loads; unchanged by cosmetic reformatting; identical across the approval record, every signature hash input, the trace frame and the audit events. |
| **Failure means** | Two components disagree about which policy was in force. Every signature hash is computed against a different input than the one that will be verified. |
| **False pass** | **Observed (F-6).** The version derivation interpolated `JsonElement` raw text, so **pretty-printing the policy file changed the version** — which would silently void every in-flight signature on a whitespace-only commit. The stability test passed because it compared repeated loads of the *same bytes*. |
| **Guard** | `TestPolicies/baseline-reformatted.json` — same semantics, reversed key order, different indentation, numeric literals preserved exactly. Plus `The_binding_survives_a_policy_edit`, which is the test that actually catches drift. |

### AC-12 · Denial reason cannot be whitespace or a repeated character

| | |
|---|---|
| **Tests** | `DenialReasonValidatorTests` (15, oracle) · `ProductionDenialReasonTests` (17, **production**) |
| **Asserted** | Rejected: null, empty, 24 spaces, `aaaa…`, `abab…`, **`asdfasdfasdfasdfasdf`**, `....`, digits-only, below minimum, padded-to-minimum. Accepted: four genuine sentences, Japanese, Arabic, text containing a family emoji (grapheme-cluster measurement). Every rejection names the V-rule it failed. The validator **refuses to start** without configuration. Bounds are constructed *from* config so raising a bound cannot make a test pass vacuously. |
| **Failure means** | A required field defeated by holding down a key. The denial corpus is noise. |
| **False pass** | A validator that rejects *everything* passes every negative test above. **Four positive controls** are therefore mandatory, not optional. |
| **⚠️ Known gap (F-4)** | `ReasonMaxRepeatUnit = 4` means `"qwertyqwertyqwertyqwerty"` (6-character repeat unit) clears every degeneracy rule. `FINDING_F4_a_repeat_unit_longer_than_the_configured_bound_still_escapes` asserts the current ratified behaviour **and proves that raising the bound to 8 closes it** — the finding is demonstrated, not merely claimed. Deliberately not fixed: the bound is config, and config is not mine. |

### AC-13 · Zero thresholds in application code

| | |
|---|---|
| **Tests** | `RepoGateTests.There_are_no_money_thresholds_hardcoded_in_the_authority_service` · `The_denial_reason_bounds_are_not_literals_in_the_validator` |
| **Asserted** | No currency-shaped literal is compared against anything in `authority-service`; denial bounds come from configuration only. |
| **False pass** | A gate broad enough to flag array indexes and HTTP status codes gets muted, exempted or deleted — and then catches nothing while still appearing in the criteria list as satisfied. |
| **Guard** | The pattern is deliberately narrow (4+ digit literals in comparisons, excluding time/size/port/status contexts) and the **blind spot is documented in the test itself**. Two exemptions were added after false positives; both are recorded in comments with the reason, rather than the regex being widened silently. |
| **⚠️** | §10 says "verified by a repo grep gate **in CI**". **No CI workflow in this repository builds or tests any .NET project.** These gates exist and run locally; that is materially weaker than the criterion, and the criterion should not be ticked. |

### AC-14 · No named co-signer anywhere

| | |
|---|---|
| **Tests** | `RepoGateTests.No_field_or_index_routes_an_approval_to_a_named_co_signer` · `The_mustDifferFrom_mechanism_is_an_exclusion_not_an_assignment` |
| **Asserted** | No `assignedTo`/`reviewerId`/`approverId`-style field in service code or Terraform indexes. |
| **False pass** | **The interesting one.** `mustDifferFrom` is on neither the allowed nor the forbidden list, so if it were ever populated with the *intended reviewer* instead of the *excluded requester*, the field-name gate passes while the property is exactly inverted. Excluding a person narrows the pool; naming a person selects from it. |
| **Guard** | A second test asserts `MustDifferFrom = [context.Actor.UserId]` specifically, and that no supervisor identity is ever placed in the exclusion list. |

### AC-15 · Terminal documents are immutable

| **Tests** | `TerminalReasonTests` · `ProductionArchitectureTests.No_state_machine_edge_leads_out_of_a_terminal_state` |
| **Asserted** | No `denied → proposed` or `denied → signed` edge; re-proposal always creates a new document linked by `supersededByApprovalId`. |
| **False pass** | Testing the *service* refuses re-proposal while the *state machine table* still permits the edge — the service is one caller of many. |
| **Guard** | Asserted against `ApprovalStateMachine` directly (by reflection where a probe method exists, by source pattern otherwise), not through a service call. |

### AC-16 · Structural contract test (§5.3.1b) — field paths

**Not implemented.** Requires a real approval document written by `authority-service` to Cosmos.
The criterion is that the written field-path set is *identical* to design §5.3, and that the
Python read models and `cosmos.tf` indexed paths are each a *subset*. **Pending — needs the
Cosmos emulator.** Flagged rather than approximated: a version of this test that reads the design
doc and compares it to a hand-written model would assert nothing about what is actually written.

### AC-17 · Remaining criteria not covered in Phase 1

Recorded honestly rather than approximated. Each is in `pending-integration.manifest.json`.

| Criterion | Why not covered |
|---|---|
| `/api/authority/*` reachable through the gateway | Needs the stack running |
| `banker-copilot-service` / SSE through nginx + Istio | Phase 2+ |
| All eleven authority event types in `event-processor` | Needs Redis + the consumer running |
| Agent cannot reach a mutating endpoint without a broker token (403) | Needs HTTP-level tests |
| Supervisor prompt-construction isolation | `banker-copilot-service` does not exist yet |
| `payloadHash` on the UI read model | No UI work yet |
| Trace persistence + offline replay | Phase 2+ |
| Distinct workload identity (#336) | Infra; needs a live cluster |
| §1.3 demo narrative end to end | Needs the full stack |
| OTEL span continuity | Needs the full stack |
| Seed data with two distinct identities | Needs seed data |

---

## 3. Tamper testing — which guards are *proven*

A guard that has never been observed failing is not a guard. `tamper-test.py` automates the loop:
break the guard, run one named test, require red, restore the file, verify the SHA-256 matches.

**17 guards attempted · 15 proven · 2 shown redundant · 0 unproven.**

| Guard | Owner | Test that caught it | Verdict |
|---|---|---|---|
| Rung combination is monotone (both folds broken together) | Turk | `RungCombinatorTests` | **PROVEN** |
| — outer fold alone (`rung = Max(rung, raised)`) | Turk | — | REDUNDANT |
| — inner fold alone (`var result = current`) | Turk | — | REDUNDANT |
| Co-signer slot excludes the requester | Turk | `L2_requires_two_distinct_identities_…` | **PROVEN** |
| L3 is not proposable | Turk | `L3_is_outside_the_harness_entirely` | **PROVEN** |
| Unknown action is denied, not defaulted | Turk | `An_unknown_action_is_refused_rather_than_defaulted` | **PROVEN** |
| Lifecycle has exactly five states | Turk | `The_lifecycle_has_exactly_five_states_and_no_expired_state` | **PROVEN** |
| Re-evaluation precedes the downstream call | Turk | `The_re_evaluation_call_precedes_the_downstream_call_…` | **PROVEN** |
| Denial reasons must be non-degenerate | Turk | `Degenerate_denial_reasons_are_rejected` | **PROVEN** |
| Denial validator has no code-level defaults | Turk | `The_validator_refuses_to_start_without_configuration` | **PROVEN** |
| `admin` does not map into the banker signer role | Turk | `An_admin_claim_does_not_map_into_…` | **PROVEN** |
| L2 co-signer set is narrower than the signer set | Turk | `The_L2_cosigner_set_is_narrower_…` | **PROVEN** |
| Only the gate can mint an execution authorization | Livingston | `ExecutionAuthorization_has_no_publicly_reachable_constructor` | **PROVEN** |
| A denied approval cannot exist without a reason | Livingston | `A_terminal_transition_cannot_be_constructed_without_a_reason` | **PROVEN (compiler)** |
| Money fields not exempt from the missing-field error | Livingston | `Removing_a_hashed_field_voids_the_signature_…` | **PROVEN** |
| `raiseBy` cannot be negative (runtime) | Livingston | `PolicyGrammarValidationTests` | **PROVEN** |
| Load-time grammar rejects a negative `raiseBy` | Livingston | `A_negative_adjustment_on_a_global_escalator_…` | **PROVEN** |

**No deliberate breakage remains.** Every mutation is reverted in a `finally` block with a
checksum assertion; `git status` confirms no modification to `src/authority-service/` or
`config/`, and no `TAMPER` marker survives outside test commentary.

### 3.1 Guards NOT tamper-tested (could not reach)

Honest list, since an untested guard is the point of this exercise:

- **The Cosmos write guard / ETag preconditions** — needs the emulator.
- **The expiry sweeper's actual query** — needs a running host.
- **Nonce single-use** — needs Redis.
- **Broker token enforcement (403 on direct call)** — needs HTTP tests.
- **Redaction at emit** — the trace pipeline does not exist yet.
- **Gateway routing / `proxy_buffering off`** — needs the stack.
- **The `TerminalReason` JSON converter's fail-closed behaviour** — reachable, not yet tampered.

---

## 4. Findings — reported, not fixed

Per my constraints I do not touch `src/authority-service/`, `config/` or infra. All findings are
demonstrated by a passing test that asserts the **current** behaviour and is written to be
inverted when fixed.

| # | Severity | Finding |
|---|---|---|
| **F-7** | **High** | `config/authority-policy.yaml` maps the claim value `user` into the **`banker` signer role** at seniority 1: `banker.claimValues: [banker, Banker, user, User]`. `user` is the role every ordinary **customer** holds. As written, a customer's own token satisfies an eligible signer slot for every L1 action — transfer reversals, account locks, balance adjustments. If the intent is "a banker's token may still carry a legacy `user` claim", the fix belongs in token issuance (`AuthService.Expand`, which already does this), not in the policy map — because the policy map cannot tell the two populations apart. |
| **F-7b** | **High** | The two role sources of truth **disagree**. `user-service/Services/RoleHierarchy.cs` gives `user` seniority **0** ("no banking authority"); `config/authority-policy.yaml` resolves `user` to seniority **1** ("may sign L1"). Each artifact is locally defensible; the composition is wrong. Nothing errors and nothing logs. There should be one source. |
| **F-2** | Medium | `ApprovalService.VerifyStoredHash` recomputes the payload hash from `approval.Payload` — the *stored* payload — which can only prove the record is self-consistent, never that what executes matches what was signed. **Mitigating:** `ExecuteAsync` accepts no payload, so there is no attacker-controlled input. The safety therefore rests on the **absence of a parameter**, which makes the parameter list a load-bearing security property. Now asserted by `The_execute_entry_point_accepts_no_caller_supplied_payload`. |
| **F-9** | Medium | `RungOrder.RaiseBy` computes `(int)from + steps`, which **overflows to a negative rung** for large `steps`; the clamp only tests the upper bound, so the negative falls through and is cast to a rung below L1. Escalation becomes downgrade by arithmetic. Not reachable today (load-time validation rejects negatives but not enormous values), but it is an unguarded edge on the one function the monotonicity proof rests upon. One-word fix: compute in `long`. |
| **F-1** | Medium | Escalator grammar drift. Epic §4.2 uses `raiseBy` + `minRung`; engine §3.2 uses `raise_to`/`min_signers`/`min_seniority`; the real YAML uses **both** `raiseBy`+`minRung` **and** `raiseTo`. The loader should **hard-error** on the unsupported spelling. An escalator that silently does nothing is far worse than one that refuses to load. |
| **F-4** | Low | `ReasonMaxRepeatUnit = 4` lets `"qwertyqwertyqwertyqwerty"` through every degeneracy rule. Raising the bound to 8 closes it (proven in-test). |
| **F-5** | Low | The epic never states the `pv1:` prefix; it exists only in engine §6.2.1. Any implementer working from the epic alone will produce a non-matching version string. |
| **F-6** | Low | (Found in my own oracle; **check `PayloadHasher` for the same shape.**) Deriving `policyVersion` from `JsonElement` raw text leaks whitespace into the hash, so pretty-printing the policy file would void every in-flight signature. |
| **F-3** | Low | (Own oracle; **check Turk's `PayloadHasher`.**) Money fields must not be exempt from the missing-declared-field hard error. |
| **F-10** | Info | `PolicyDecision` no longer carries `DistinctIdentitiesRequired`. Separation of duties is the requirement most likely to be checked by a caller holding only the decision, and it is now the only requirement not on it — callers must go back to the policy or walk the slots. |

---

## 5. Adversarial review — attempts to break the invariant

Concrete sequences by which a write might execute without a valid human signature at the correct
rung. Surfacing the attempt is the value; fixes are not required here.

### 5.1 The defence is one-and-a-half layers, by the epic's own admission

§4.4 specifies four layers. Layers 2 and 3 **cannot currently be built**:

- **#334** — all services share one JWT audience (`banking-demo`) and one symmetric **HS256**
  key. Any service holding the signing key can mint a token for any role, including
  `supervisor`. Layer 2 (identity separation) is therefore not enforceable, and **the single
  most valuable forgery target in the system is a symmetric key present in eleven pods.**
- **#336** — all eleven pods share one workload identity. Layer 3 (least-privilege data access)
  is not enforceable; anything that can reach Cosmos can reach the approvals container.

**Attack.** Compromise *any* service in the mesh → obtain the HS256 key → mint a `supervisor`
token with a distinct `sub` → co-sign an L2 approval you proposed. Separation of duties holds
(two distinct identities) but both are you. **Every test in this suite passes.** No test at this
layer can detect it; the control is cryptographic and it is currently absent. This is the single
largest gap in Phase 1 and it is *already known and filed* — the value here is stating that the
authority service's guarantees are conditional on it.

### 5.2 Race on the last signature slot

Two co-signers submit the final L2 signature simultaneously. Under a read-modify-write without
an ETag precondition, both read one filled slot, both write two, and the approval reaches
`signed` having recorded one identity twice — or with an unexamined third signature.

**Sharper variant:** the *requester* and a genuine co-signer race. If `mustDifferFrom` is checked
against a stale read, the requester's own signature can land in slot 1.

**Status:** the single-writer repository and ETag preconditions are the intended control.
`Only_the_write_guard_may_replace_an_approval_document` proves no *other* code path writes.
**Not proven: that the writer itself uses a precondition, and that the check is inside it.**
Needs a Cosmos-emulator concurrency test. **Highest-value untested attack.**

### 5.3 The sweeper-lag window

An approval passes `expiresAt`. The sweeper polls on an interval. Between expiry and the sweep,
the document still reads `pending`. Anything that checks *status* rather than *the clock* will
accept a signature or an execution inside that window.

**Status:** production has `ApplyLazyExpiryAsync` as step 2 of `ExecuteAsync`, before the status
check, and the oracle asserts a late signature is rejected with the sweeper never having run.
**Residual:** any *other* entry point — batch sign, a repair script, an admin action — that
checks status without the lazy expiry re-opens the window. The property is "every path checks the
clock", and only the execute path is verified.

### 5.4 Policy-reload timing (TOCTOU on `policyVersion`)

Re-evaluation loads the current policy, compares rungs, mints an authorization; the broker call
happens after. If the policy reloads between the comparison and the call, the action executes
under a version that was never evaluated. Window: milliseconds. Exploitability: low. But the
correct shape is to bind the resolved `policyVersion` into the authorization token and have the
executor assert it has not moved — otherwise the gate's guarantee is "the policy was acceptable
a moment ago".

### 5.5 Re-plan supersede window

The agent re-plans; the old approval is superseded and a new one created. Two questions the
tests do not answer: (a) is supersede atomic with respect to a signature landing on the old
approval, and (b) can a signature collected on the *old* payload be carried onto the new one? If
supersede copies signature slots, it launders a signature across a payload change — the exact
thing `payloadHash` exists to prevent. `SupersedeByReplan` in the oracle deliberately does not
copy signatures; **production behaviour is not verified.**

### 5.6 Execute replay and retry idempotency

`execute` is called twice. If the downstream call is not idempotent and the state transition to
`executed` happens after it, a retry moves money twice on one signature. Conversely, if
transitioning first, a genuine failure strands the approval. §5.1's answer — a failed execution
leaves `status = signed` because the signatures remain valid — is right, and it makes retry a
*designed* path, which means the retry path must re-enter the gate. The oracle proves the retry
is re-gated and voided by a tightening. **Production retry is not verified**, and idempotency of
the downstream call is not in scope of any test.

### 5.7 Nonce reuse / signature replay

Signing input includes `jti`, slot ordinal, approval id and nonce. Replay across slots and across
approvals is tested in the oracle. **Single-use enforcement is Redis-backed and untested.** If
the nonce store is best-effort (evicted under memory pressure, or fails open on a Redis
timeout), replay becomes possible precisely when the system is under stress. **Fail-open on the
nonce check is the specific thing to verify.**

### 5.8 Batch approval smuggling

Batch is capped at L1 (`batchApproval.maxRung: L1`, I-10). The attack is to get an item that
*would* escalate into a batch: submit N items that individually evaluate to L1, where one
carries a fact that only escalates on re-evaluation at execution time. If the batch executes as
a unit and the gate runs per-batch rather than per-item, the escalating item rides along.
**Untested.** The relevant assertion is that the execution gate runs **per item**, and that one
item's escalation does not silently drop that item while executing the rest.

### 5.9 Direct Cosmos write

Anything holding the shared workload identity (#336) can write the approvals container directly:
set `status: signed`, invent two signature objects, call execute. The gate re-evaluates *policy*
but the signatures are read from the document. **The gate does not verify that signatures were
ever collected through the signing path** — it verifies the quorum and the hash, both of which a
forged document satisfies. The only real controls are workload-identity separation (#336, absent)
and the audit trail (detective, not preventive). **This is the most complete bypass available
today** and it requires no race and no timing.

### 5.10 Unknown `terminalReason` injected into a document

A document is written with `terminalReason: "SOMETHING_ELSE"`. If the enum converter falls back
to a default rather than throwing, the denial is silently reclassified — most damagingly into a
bucket excluded from denial-rate metrics. The oracle asserts seven unknown values fail closed.
Production's converter is **reachable but not yet tamper-tested.**

### 5.11 Threshold override via environment

Thresholds resolve `env → default`, correctly producing a new `policyVersion` (which voids
in-flight signatures on escalation — the right behaviour). The attack is the opposite direction:
set `POLICY_LOAN_DUAL_CONTROL_AMOUNT` absurdly high so nothing ever reaches L2. Monotonicity is
preserved; the ladder is intact; it simply never fires. **No test asserts that a threshold is
within a sane band**, and no alert fires on a relaxing override. Monotonicity protects against
lowering a rung *given the facts* — it says nothing about redefining the facts.

### 5.12 The rung is right but the action is wrong

`hashFields` for `loan.decision.record` are `[applicationId, verdict, amount, rationale]`. Any
field **not** in that list can be changed after signature without voiding it — by design. The
question the tests cannot answer is whether the declared set is *complete* for every action: a
field that affects the downstream call but is not hashed is a free mutation. `The_hashed_field_set_itself_is_asserted`
pins today's set so a shrink is loud, but **only a human can decide whether the set is right.**
Recommend a review of every action's `hashFields` against its `target` call.

---

## 6. Recommendations

1. **Resolve F-7/F-7b before Phase 1 closes.** A customer token that maps to a banker signer role
   is the shortest path to violating the invariant, and it needs no attacker sophistication.
2. **Wire this project into CI.** Nothing forces these 209 tests to run. Three §10 criteria say
   "verified by a grep gate in CI" and that gate does not exist. A suite outside a gate is a
   suggestion.
3. **Add a Cosmos-emulator concurrency test** for the last-signature race (§5.2). It is the
   highest-value untested attack that is actually in scope for Phase 1.
4. **Bind `policyVersion` into the execution authorization** and assert it at the broker call
   (§5.4), closing the reload window structurally rather than by timing.
5. **Verify the nonce store fails closed**, not open, on a Redis error (§5.7).
6. **Make monotonicity's redundancy deliberate.** Two independent folds each prevent a descent,
   so a single-point regression is invisible. Either document the redundancy or remove one.
7. **Review every action's `hashFields` against its target call** (§5.12). No test can do this.
8. **Do not tick AC-13/AC-14/AC-16 in §10.** The gates exist locally but the criteria say CI, and
   AC-16 needs a real written document.

---

## 7. How to run

```bash
cd src/authority-service.Tests
dotnet test                      # 209 tests
python3 tamper-test.py           # 17 guards; restores every file and verifies checksums
```

`tamper-test.py` writes `tamper-results.json`. It is safe to run repeatedly: every mutation is
reverted in a `finally` block with a SHA-256 assertion, and it fails loudly if a restore does not
match.
