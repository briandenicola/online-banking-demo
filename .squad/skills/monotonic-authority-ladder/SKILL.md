# Skill: Config-Driven Monotonic Authority Ladder

**When to use:** Any feature where an automated actor (agent, batch job, workflow) proposes
state-changing operations that a human must authorize, and where "how much authorization" varies
by amount, risk, or context. Also applies to non-agent approval workflows (maker-checker,
dual control, four-eyes).

**Do not use for:** simple RBAC. If the answer is a fixed "role X may do Y," use roles. This
pattern is for when the *number and seniority of approvers* varies with the payload.

---

## The three ideas worth stealing

### 1. Make "downgrade" unrepresentable, not merely forbidden

The usual failure is a rule engine where any rule can set the outcome — so
"escalations only raise authority" becomes a code-review discipline that eventually slips.

Instead, define a total order and give the rule grammar **only raising verbs**:

```yaml
rules:
  - when: <predicate>
    raise_to: L2          # the ONLY rung verb that exists
    min_signers: 2        # folded with max()
    min_seniority: 2      # folded with max()
```

```python
RUNG_ORDER = {"L1": 1, "L2": 2, "L3": 3}

rung    = action.base_rung
signers = action.base_signers
for rule in all_rules:                 # ALL evaluated; none short-circuits
    if predicate(rule.when, ctx):
        rung    = rung_max(rung, rule.raise_to)
        signers = max(signers, rule.min_signers or 0)

signers = max(signers, 1)              # FLOOR — applied AFTER all config input
```

Why this is a proof and not a convention:
- `max(x, y) >= x` ⇒ result is never below the base rung.
- `max` is commutative/associative ⇒ rule order cannot matter, no "last rule wins" hazard.
- `max(S ∪ {r}) >= max(S)` ⇒ firing *more* rules never lowers the outcome.
- The schema has no `lower_to`, `exempt`, `waive`, `skip` — a downgrade **cannot be written**.
- Floors applied after config ⇒ worst possible misconfiguration is "too strict."

**Anti-pattern:** an `exceptions:` or `waivers:` block "for edge cases." The moment it exists, the
monotonicity proof is gone and you are back to reviewing every rule by hand.

### 2. Threshold indirection — the "no magic numbers" mechanism

Never let a rule contain a literal. Every number is a *named* entry that declares its own env override:

```yaml
thresholds:
  transfer_l2_amount:
    kind: money            # money | count | ratio | duration_seconds
    currency_scale: 2
    default: "5000.00"     # STRING — YAML floats silently lose precision
    env: POLICY_TRANSFER_L2_AMOUNT
    description: "Amount at or above which a supervisor co-signs."

rules:
  - when: payload.amount >= threshold("transfer_l2_amount")
```

Rules:
- Resolution is **env → file default**, with *no third source*. A code-level fallback is how
  hardcoded values sneak back in.
- A reference to an undefined name is a **startup failure**, not a default. Fail closed.
- Surface the **env-var name** alongside the value in the approver's UI. "Why did this escalate?"
  becomes self-service instead of a support ticket.
- Snapshot the resolved values onto the approval record, so a decision is reproducible a year later
  even after the config changed.

**CI lint that makes it stick:** walk the parsed rule AST and fail on (a) any numeric literal not
wrapped in `threshold(...)`, (b) any threshold lacking `env`, (c) any unresolvable reference,
(d) any money `default` that is not a string, (e) numeric literals compared against payload fields
anywhere in the engine source.

### 3. Payload-hash binding beats intent binding

A signature that authorizes "a transfer" lets the proposer change the amount afterwards
(approved $5k, executed $50k). Bind the signature to a **hash of the exact payload**:

```
canonical = JCS(project(payload, action.hash_fields))   # RFC 8785, ordered projection
hash      = sha256("<scheme>.v1\n" + action_id + "\n" + canonical)
```

Non-obvious details that matter:
- **Project onto a declared field list**, not the whole body. Adding a non-material field later
  then doesn't invalidate in-flight approvals, and "what did the human agree to?" is a reviewable
  list rather than an emergent property of serialization.
- **Deviate from JCS for money.** JCS uses ES6 double serialization — unsafe for currency.
  Canonicalize money as fixed-scale decimal strings; reject floats outright in money positions.
  Kills the `7500` / `7500.0` / `7.5e3` ambiguity class.
- **Treat null and absent identically** (omit both). Otherwise `{"memo": null}` and `{}` hash
  differently for no semantic reason.
- **NFC-normalize strings** so visually identical Unicode can't produce two hashes.
- **Domain-separate by action id** in the hash prefix, so a signature for a cheap action can never
  be replayed against an expensive one.
- **Include the signer's slot ordinal in the signing input.** Without it, one captured signature can
  fill both slots of a dual-control approval — identities differ, but the crypto doesn't notice.
- **Exclude secrets from `hash_fields`** (e.g. a password-reset value). Hashing a secret puts a
  verifier for it into a long-retained audit record.
- **Recompute the hash at execution time** from the body you are actually about to send. This
  catches bugs, not just attacks, at the last possible moment.

---

## Bonus: expiry with semantics ≠ database TTL

If "expired" must mean something (denied, rejected, timed-out) rather than "gone," a native
delete-based TTL is the wrong mechanism — a deleted row is indistinguishable from one that never
existed.

Three-part pattern:
1. **Lazy read-side expiry is the safety control.** Every path that loads the record compares
   `expiresAt` to now *before* acting. Background-job lag can then never permit a late action.
2. **A sweeper is a housekeeper, not a guard.** It emits the state transition and the audit event.
   Never let one background job be both housekeeper and security control — that's a single point
   of failure wearing two hats.
3. **Native TTL only on terminal records**, for retention purge. Live records carry no TTL, so a
   stalled sweeper can never silently delete pending work.

---

## Checklist

- [ ] Rung/authority is a total order with a `max` fold and no lowering verb in the grammar
- [ ] Minimum-approver floor applied in code, after all config input
- [ ] Every threshold named, typed, env-overridable, string-defaulted for money
- [ ] Unknown action / unresolvable threshold ⇒ startup or request failure, never a default
- [ ] Fired rules produce human-readable reasons, frozen onto the record at decision time
- [ ] Signature binds payload hash + signer + slot ordinal + timestamp + single-use nonce
- [ ] Hash recomputed and re-verified at execution
- [ ] Re-plan creates a new record; payload of a pending record is never patchable
- [ ] Batch approval constrained to one action type, below threshold, never at the dual-control rung
- [ ] Expiry semantics separated from physical deletion
- [ ] CI lint enforces the no-literals rule
- [ ] Config example in the design doc is machine-parsed and cross-validated in CI

---

## 4. The temporal axis — config drift under an in-flight approval

Once approvals outlive a single request, a fourth question appears: **what happens to a signature
already given when the policy changes underneath it?**

Resist inventing a new rule. It is **the same monotonic rule, applied over time instead of over
context**: escalators only push the rung up; policy drift only invalidates, never rescues.

```
At execution time, re-evaluate under the CURRENT policy.
  required_rung > rung_the_signature_satisfied  -> VOID. Re-propose at the new rung.
  required_rung <= rung_the_signature_satisfied -> honour it. Execute.
```

No auto-downgrade. No auto-honouring an under-signed action. Note there is deliberately **no `else`
branch that adjusts anything** on the loosened path — a loosened policy is simply not an event. If
you find yourself writing `if stored_version != current_version:` as a *decision* rather than as a
bare audit annotation, the model has diverged.

### Version the policy by content hash of the RESOLVED config

```
policy_version = "pv1:" + sha256(canonical(resolved_policy))[:16]
```

- **Resolved, not the file bytes.** If thresholds are env-overridable (they should be, §2), a
  ConfigMap edit changes behaviour with a byte-identical file. A file hash reports "no change" and
  is actively misleading.
- **Not a hand-maintained semver.** It is a field someone must remember to bump in the same commit
  as the rule they changed. They will not, and the failure is silent.
- **Comparable but deliberately not ordered.** Equal/unequal only. Ordering invites
  `if current > signed` special-casing — the exact divergence the rule exists to prevent. Denying
  yourself an operator is legitimate when the operator's existence is what tempts the wrong code.
- Exclude provenance (`effective_from`, `owner`) so a redeploy of unchanged rules does not
  manufacture a new version. Keep a human label (`policy_id`) alongside: one identity for
  correctness, one for conversation.

### Bind the version into the signature preimage

Put it in the **domain-separation prefix**, next to the action id — not as a key in the projected
object, where a payload field of the same name could collide with it and where it would blur the
projection's meaning ("the business facts the human agreed to").

What this buys is narrow and worth stating precisely: re-evaluation is what stops an under-signed
write; the binding is what stops **tampering with the record of which ruleset applied**. Without it,
the stored version is an ordinary mutable field and anyone who can write the document can relabel a
signature. With it, editing that field breaks verification. It converts "this human signed under
this ruleset" from asserted to verifiable.

### ⚠️ The detail that makes it consistent — split which version each check reads

| Check | Which version | Why |
|---|---|---|
| Signature / hash recompute | the version **stored on the record** | Verifies *what was signed*. Historical fact; cannot change. |
| Authority re-evaluation | the **current**, freshly loaded version | Decides *whether it may still execute*. Present-tense judgement. |

Share one input between them and every policy edit — including a comment reflow — fails hash
comparison for every pending record, silently converting the rule into "any edit invalidates
everything." **Signature verification is archaeology; authority is live.**

### Key invalidation off the re-evaluated OUTCOME, never off version inequality

This is the single most likely misimplementation. Keying off inequality voids all pending work on
every edit; keying off "does this now require more authority?" confines the blast radius to records
that actually cross a newly-tightened value, and makes loosening and cosmetic churn free.

| What changed | Records affected |
|---|---|
| Comments, descriptions, provenance | none |
| A threshold *raised* (loosened) | none |
| A threshold *lowered* / new escalator | only those whose payload crosses the new value |
| Action removed or moved to the forbidden tier | all pending of that type |

### Operational obligations this creates

1. **Simulate blast radius before rollout.** Evaluation is pure over data already on the record, so
   "what would this change cost?" is answerable by replay. Expose it as a dry-run endpoint returning
   the affected set *with reasons*. Wire it to the config-change path. It must **warn, never block** —
   gating a policy *tightening* behind pending work runs the incentive exactly backwards.
2. **Notify eagerly, guarantee lazily.** Sweep on reload to *tell people*; keep the check at use
   time as the *correctness guarantee*. Same separation as expiry — never one mechanism doing both.
3. **Audit the discard explicitly.** Emit an event carrying the full set of discarded signatures
   (who, which slot, when) plus both versions. "A machine threw away a human's approval" is exactly
   what an incident review asks about; it must not be reconstructible only by inference.
4. **No bulk re-approve.** Bulk *re-proposal* is fine; bulk *signing* is not. A "re-approve all"
   button reconstitutes blanket approval by the back door, at the moment of maximum approval
   fatigue. Watch for this general shape: a cleanup affordance that quietly undoes the control the
   system was built around.
5. **Distinguish the states in the UI.** "Invalidated by policy change", "expired", and "denied by a
   human" are three different facts and must not collapse into one grey *unavailable*. The
   user-facing string should name the threshold and its env key, never a generic error.

### Checklist additions

- [ ] Policy version = content hash of the **resolved** config; provenance fields excluded
- [ ] Version bound into the signature preimage, in the prefix, not the payload object
- [ ] Hash recompute reads the **stored** version; re-evaluation reads the **current** one
- [ ] Invalidation keyed off re-evaluated **rung**, not version inequality
- [ ] Loosened-policy path has no branch at all (no downgrade, no signature removal)
- [ ] Dry-run impact endpoint exists and warns rather than blocks
- [ ] Discard event carries every discarded signature and both versions
- [ ] No bulk re-sign anywhere in the API shape

---

## 5. Terminal-state design — collapse redundant states, but pay the debts

Approval records accumulate terminal states: denied, expired, superseded, voided-by-policy. The
instinct is one state per outcome. **Prefer one terminal state plus a closed discriminator enum.**

```
proposed -> pending -> signed -> executed
                  \-> denied  (+ mandatory terminalReason from a closed enum)
```

A state and an adjacent discriminator that encode the same fact are redundant, and the redundancy
is nearly free to remove *before* queries, dashboards and UI branches are written against it — and
a migration afterwards. **Collapse everywhere at once:** a principle applied to one case but not its
identical twin is worse than not applying it, because the next reader cannot tell which rule is real.

This buys a uniform vocabulary and one place the distinction lives. It also incurs four debts that
must be paid explicitly, or the collapse is a net loss.

### Debt 1 — the removed structure was carrying a meaning

When "expired" was its own state, *expiry means denied, never auto-approved* was self-evident.
Folded into `denied + TTL_EXPIRED`, it becomes an invariant a future reader can lose track of.
**Where you removed a structure that carried a meaning, write the meaning down louder, in the place
the structure used to be.**

### Debt 2 — the surviving field is now a much weaker filter

`status='denied'` used to be one of five meaningful buckets; now it is one large bucket that means
nothing without the discriminator. Any query, metric, or alert filtering on it alone is probably a
bug — blending timeouts into a "denial rate" makes an operational problem look like human judgement.
Audit for this after the collapse; do not merely document it.

### Debt 3 — index shape changes

One predicate on a default-indexed field becomes two predicates plus a sort. Cosmos (and most
document stores) will not use a composite index unless **every filter and ORDER BY path appears in
it, in order** — so `(status, discriminator, terminalAt)` becomes newly required. Missing it means a
cross-partition scan: free at demo volume, expensive later, and only visible in production.
**Any time a filter goes from one predicate to two, re-derive the composite index.** Also ensure the
sort field is now reliably populated — it was probably nullable-and-ignored before.

### Debt 4 — retain event names

If an append-only audit stream already emits `SomethingExpired`, **keep the event name** even though
the state is gone. Renaming an event type is a breaking change for consumers, for zero benefit. The
event name records *what happened*; the reason field records *what it means*. They may diverge.

### Two traps in the enum itself

**A value containing an id, timestamp, or count is not an enum value.** `"superseded_by:<newId>"`
defeats the enum, defeats indexing, and defeats aggregation. Split it: constant in the reason field,
variable data in its own field (`supersededBy`). Grep for interpolation whenever someone declares an
enum "closed."

**Document stores cannot enforce enums — say so instead of writing "enforced at the persistence
layer."** No CHECK constraints, no column types, no server-side schema. What works, in descending
order of weight:

1. **Funnel all writes through one repository type**, with an architecture test forbidding raw
   container writes anywhere else. This is the layer doing the real work.
2. A typed enum with a serializer that **throws on unknown values in both directions**.
3. A guard query that alerts and **deliberately does not self-heal** — a silent repair erases the
   evidence of whatever wrote the bad value.
4. **Readers fail closed:** an unrecognised value means "refuse to act," never "proceed."

Being honest about what a datastore cannot do is more useful than a reassuring sentence that will
be believed.

### Two status-ish fields will collide

Adding `executed` as a lifecycle state next to an existing `execution.state` needs an explicit
mapping table. The load-bearing call: **a failed execution does not advance the lifecycle.** It
stays `signed`; signatures remain valid and a retry needs no new human. Making failure terminal
either strands valid signatures or forces a "reopen" transition — and reopening a terminal state is
the exact edge a closed enum exists to prevent.

---

## 6. Two recurring arguments, and the answers that hold

### "Can step-up auth / MFA count as the second approval?"

**No.** Separation of duties means separation of *people*.

- **MFA proves *who* is signing. It says nothing about *how many* people reviewed.** Different
  controls, different questions; neither substitutes for the other.
- **The failure is total, not local.** The moment step-up can stand in for a second human, the
  second rung becomes the first rung wearing a hat — for every action, not just the one where the
  exception was granted.
- **It defeats exactly the attacks the rung exists to stop.** In self-dealing, coercion, and session
  compromise, the attacker holds the identity and can satisfy step-up by definition.

Enforce it structurally: the evaluator builds `mustDifferFrom`, and no policy verb can empty it —
same shape as having no rung-lowering verb.

### "Should we show the payload hash in the UI, or is that developer clutter?"

**Show it, permanently.** It costs one line and it is the most legible security property in the
system: everything else is policy the user must trust, and the hash is the one thing they can *see*
is the same on the card they read and the action that executed. The decisive reason is usually the
third one, though: if the hash changes when authority is re-evaluated, a user asked to sign the
"same" thing twice sees an arbitrary demand — unless they can see two different values. Remove the
hash and the re-sign flow looks like a bug. Compute the truncated display form **server-side**; the
client should never be in the business of truncating a security value.

## 7. Free-text justification fields (denial reasons, override rationales)

If the text feeds downstream labelling or review, require it and validate **server-side**. Naive
"minimum N characters" is under-specified in three ways that matter:

1. **Normalize before measuring.** NFC, trim, then collapse internal whitespace runs *for
   measurement only* (store the original). Otherwise `"a" + 19 spaces + "b"` passes.
2. **Measure grapheme clusters**, not bytes or UTF-16 code units — or a reason in Japanese or Arabic
   needs three times the substance, and one emoji counts as five characters.
3. **Add a repeated-unit check.** Length + distinct-character rules are both satisfied by
   `asdfasdfasdfasdfasdf`. "Is the string a whole-number repetition of a unit of length ≤ N?" is the
   rule that actually stops keyboard mashing.

Plus a minimum count of Unicode-letter characters to kill digit/punctuation padding. Every one of
these numbers is a named config value with an env override — the specified minimum is a *default*,
not a literal in the validator.

**State the limit.** This stops *lazy* input, never *determined* garbage: a fluent, plausible,
entirely fabricated sentence passes every rule and no regex will separate it from a real one. If the
data must be trustworthy rather than merely non-empty, that is a sampling/review problem. Say so, or
someone will assume the data is clean because the endpoint has rules.
