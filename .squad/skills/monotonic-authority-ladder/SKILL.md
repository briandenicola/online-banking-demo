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
