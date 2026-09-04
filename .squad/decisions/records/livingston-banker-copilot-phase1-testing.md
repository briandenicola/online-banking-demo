---
date: 2026-09-04
author: Livingston (Tester/QA)
status: proposed
component: authority-service, tests, config, user-service
issue: 332
---

# Phase 1 testing: what I found trying to break "agents never approve"

209 tests written and passing, 17 guards tamper-tested, one test-plan document
(`docs/design/banker-copilot-phase1-test-plan.md`). Everything below is **reported, not fixed** —
`src/authority-service/`, `config/` and infra are not mine to change. Each finding is demonstrated
by a passing test that asserts the *current* behaviour and is written to be inverted when fixed,
so none of them can rot into a claim nobody can check.

---

## Decisions I made that others should know about

### 1. The specification is an executable oracle, in a separate directory from production tests

Most of this suite was written before `authority-service` existed. Rather than pseudocode, I built
a spec-derived reference implementation (`Spec/`) of the lifecycle, canonicalisation, hashing,
execution gate and store, behind an `IPolicyEvaluator` seam.

It earned its keep — it surfaced three specification defects before any production code existed.
But a green oracle test proves the **specification is coherent**, never that anyone implemented
it. `Spec/` + `Engine/` + `Store/` are the oracle; **`Production/` is the only code that can fail
because of someone else's work.** Please keep that separation; collapsing it would make the suite
look twice as strong as it is.

### 2. No skipped tests. A ledger that fails instead.

`[Fact(Skip = "waiting for Turk")]` is invisible in a green run and stays skipped after the
blocker clears. Instead, `pending-integration.manifest.json` enumerates every blocked dependency,
and `IntegrationReadinessTests` **runs every time and fails when a claim stops being true**. It
fired correctly when Turk's service and Rusty's wiring landed mid-session.

It is now two-directional: `status: landed` entries flip from tripwire into regression guard, so
the day someone deletes the `ApprovalVoidedByPolicyChange` audit case or renames the gateway
route, a test says so.

### 3. Structural proof wherever it is available

Where possible a property is made **unrepresentable** rather than checked: `Approval.Status` is
derived (a reasonless `denied` cannot be constructed), `ExecutionAuthorization` has a private
constructor mintable only by the nested re-evaluation gate (a bypass does not compile). Two
tamper cases came back **PROVEN_BY_COMPILER**, which is a stronger result than a red test and is
my answer to "assert the absence of a path rather than the presence of a check".

### 4. Two test projects exist against one service

Mine (`authority-service.Tests`, 209) and Turk's (`authority-service.UnitTests`, 99). Both green,
no overlap in intent — his are unit tests of his implementation, mine are spec-oracle plus
differential/structural tests. They should be folded together, but not by either of us
mid-flight. Flagging for whoever closes Phase 1.

---

## Findings

### F-7 / F-7b — an ordinary customer's token satisfies a banker signature slot · **HIGH**

`config/authority-policy.yaml`:

```yaml
signerRoles:
  banker:
    claimValues: [banker, Banker, user, User]
    seniority: 1
```

`user` is the role every ordinary **customer** of this application holds. As written, a customer's
own token resolves to the `banker` signer role at seniority 1, and `banker` is an eligible signer
for every L1 action — transfer reversals, account locks, balance adjustments.

**F-7b makes it sharper: the two role sources of truth disagree.**

| Artifact | Says about `user` |
|---|---|
| `src/user-service/Services/RoleHierarchy.cs` | seniority **0** — no banking authority |
| `config/authority-policy.yaml` | resolves to `banker`, seniority **1** — may sign L1 |

Each file is locally defensible. The **composition** is wrong, and this is exactly the class of
bug §5.8.2 warns about: nothing errors, nothing logs, and the authority ladder simply has a rung
with the entire customer base standing on it. No single-service test could see it.

If the intent was "a banker's token may still carry a legacy `user` claim", the fix belongs in
token issuance — `AuthService.Expand` already does this expansion — not in the policy map, because
the policy map cannot tell the two populations apart.

Tests: `ProductionRoleModelTests.FINDING_F7_*` and `FINDING_F7b_*`.

**Recommendation: resolve before Phase 1 closes.** It is the shortest path to violating the
invariant and it requires no attacker sophistication.

### F-2 — the stored-payload hash check is self-referential · MEDIUM

`ApprovalService.VerifyStoredHash` recomputes the payload hash from `approval.Payload` — the
*stored* payload. That can only ever prove the record is self-consistent; it cannot prove that
what is about to execute matches what was signed.

**Mitigating, and it is the real control:** `ExecuteAsync` accepts **no payload parameter**. There
is no caller-supplied input for a mutation to arrive through, so the stored payload *is* the
executed payload by construction. The safety comes from the **absence of a parameter**, which
makes the parameter list a load-bearing security property. It now has a test
(`The_execute_entry_point_accepts_no_caller_supplied_payload`) that fails if someone later adds a
helpful `updatedPayload` overload.

Not a live vulnerability. Raised because the check reads like a defence and is not one, and
someone will eventually rely on it.

### F-9 — `RungOrder.RaiseBy` overflows into a negative rung · MEDIUM

```csharp
var target = (int)from + steps;
return target >= (int)Rung.L3 ? Rung.L3 : (Rung)target;
```

For a large `steps`, `(int)from + steps` overflows to a **negative** number. The clamp only tests
the upper bound, so the negative falls straight through and is cast to a rung below L1.
**Escalation becomes a downgrade by arithmetic** — the one outcome I-4 declares structurally
impossible.

Reachable only via a policy carrying an absurd `raiseBy`; load-time validation rejects negative
values but not enormous ones. So it is not an attack today. It is an unguarded edge on the single
function the monotonicity proof rests upon, and the fix is one word: compute in `long`.

Test: `RungCombinatorTests.FINDING_F9_*`. (I hardened my own oracle so it can act as the
reference; production is untouched.)

### F-1 — escalator grammar drift · MEDIUM

Epic §4.2 uses `raiseBy` + `minRung`. Engine §3.2 uses `raise_to` / `min_signers` /
`min_seniority`. The shipping YAML uses **both** `raiseBy`+`minRung` **and** `raiseTo`.

Pick one and make the loader **hard-error** on the other. An escalator that silently does nothing
because its key was not recognised is far worse than one that refuses to load — it presents as a
policy that is in force when it is not.

### F-4 — the denial-reason repeat-unit bound is too small · LOW

`Denial:ReasonMaxRepeatUnit = 4` means `"qwertyqwertyqwertyqwerty"` (6-character repeat unit)
clears every degeneracy rule while being exactly as meaningless as `"aaaaaaaa"`. Raising the bound
to 8 closes it — **proven in-test**, not asserted. `ProductionDenialReasonTests.FINDING_F4_*`
demonstrates both the escape and the fix. Left alone because the bound is config and config is
ratified.

### F-5 · F-6 · F-3 — smaller, but F-6 and F-3 are worth checking in `PayloadHasher`

- **F-5:** the epic never states the `pv1:` prefix; it exists only in engine §6.2.1. Anyone
  implementing from the epic alone produces a non-matching version string.
- **F-6:** deriving `policyVersion` from `JsonElement` raw text leaks whitespace into the hash —
  **pretty-printing the policy file would void every in-flight signature.** Found and fixed in my
  oracle; please confirm production derives from canonicalised values.
- **F-3:** money fields must **not** be exempt from the missing-declared-field hard error. Found
  and fixed in my oracle; the worst possible field to exempt. Please confirm `PayloadHasher`.

### F-10 — `PolicyDecision` no longer carries the distinct-identity requirement · INFO

Separation of duties is the requirement most likely to be checked by a caller holding only the
decision, and it is now the only requirement not on it. Callers must go back to the policy or walk
`SignerSlots[].MustDifferFrom`.

To be clear, **the underlying change is right**: retiring rung-level `distinctIdentities` and
having the loader *reject* it — rather than ignore it — avoids an operator setting it to `1` and
believing they relaxed dual control. A dead knob that looks live is worse than no knob. I only
note the ergonomic consequence.

---

## The gap that is nobody's bug, and is the biggest one

**§4.4 specifies a four-layer defence. It is currently one and a half layers**, by the epic's own
admission (#334, #336).

- **#334** — every service shares one JWT audience and one **symmetric HS256 key**. Any service
  holding that key can mint a token for any role, including `supervisor`.
- **#336** — all eleven pods share one workload identity. Anything that can reach Cosmos can reach
  the approvals container.

**The complete bypass this permits, today, with no race and no timing:** write an approval
document directly — `status: signed`, two fabricated signature objects — then call execute. The
gate re-evaluates *policy*, and verifies *quorum* and *hash*, all of which a forged document
satisfies. **The gate does not verify that the signatures were ever collected through the signing
path.** Alternatively, mint a `supervisor` token with a distinct `sub` and co-sign your own L2
proposal: separation of duties holds — two distinct identities — but both are you.

**Every test in my suite passes in both scenarios.** No test at this layer can detect it; the
control is cryptographic and it is absent. I am not raising this as new — both issues are filed —
but the authority service's guarantees are *conditional* on them, and that conditionality should
be stated wherever Phase 1 is signed off.

---

## Other attacks worth someone's attention

Full detail in §5 of the test plan. The three I would prioritise:

1. **Race on the last signature slot** (§5.2). Two co-signers submit the final L2 signature
   simultaneously; without an ETag precondition inside the single writer, one identity can be
   recorded twice. I proved no *other* code path writes approvals, but **not** that the writer
   itself uses a precondition. Highest-value untested attack that is genuinely in Phase 1 scope.
   Needs a Cosmos-emulator test.
2. **Nonce single-use fails open** (§5.7). If the Redis-backed nonce check fails open on a
   timeout or eviction, signature replay becomes possible **precisely when the system is under
   stress**. Untested.
3. **Batch approval smuggling** (§5.8). Batch is capped at L1. If the execution gate runs
   per-batch rather than per-item, an item that only escalates at execution-time re-evaluation
   rides along. The assertion needed is that the gate runs **per item**.

Also flagged: policy-reload TOCTOU between re-evaluation and the broker call (bind `policyVersion`
into the authorization token to close it structurally); whether re-plan supersede can launder a
signature across a payload change; and that **monotonicity protects against lowering a rung given
the facts, but says nothing about a relaxing threshold override** — set
`POLICY_LOAN_DUAL_CONTROL_AMOUNT` high enough and L2 simply never fires, with the ladder intact
and no alert.

---

## Two process recommendations

**1. Wire this into CI.** Three §10 criteria say "verified by a repo grep gate **in CI**". No
workflow in this repository builds or tests any .NET project. I implemented the gates
(`Contracts/RepoGateTests.cs`) and they run locally — but nothing forces them to run, and a suite
outside a gate is a suggestion. **AC-13, AC-14 and AC-16 should not be ticked** in §10 as things
stand.

**2. Keep tamper-testing.** `src/authority-service.Tests/tamper-test.py` is repeatable and safe:
it mutates, runs one named test, requires red, restores, and asserts SHA-256. 15 of 17 guards
proven; the other 2 were shown **redundant** (production protects monotonicity twice, so breaking
either fold alone is undetectable). Guards that were never observed failing — the Cosmos write
guard, the sweeper query, nonce single-use, broker-token enforcement — are listed unproven in
§3.1 of the test plan rather than quietly assumed.
