# Now — what the team is focused on

**Updated:** 2026-09-04
**Epic:** #332 Banker Copilot — a hosted agentic harness for the banker/admin side.
**Branch:** `squad/332-banker-copilot` (all work here; `main` holds the ratified design docs)

---

## The one invariant — never relitigate

**Agents never approve.** Every state-changing action carries a human signature.
Thresholds govern *how many* humans sign and *how senior* — never *whether* a human signs.

Corollaries that have already been ratified and must not be re-opened:
- **L1** acting banker signs · **L2** supervisor agent gives an independent second opinion AND a
  human supervisor co-signs from a *different identity* · **L3** outside the harness entirely
  (deletes, role promotion, adverse action, edits to the harness's own policy) — the agent may not
  even propose at L3.
- Escalators are **monotonic**: they only push a rung UP, never down. Structurally, not by convention.
- **Expiry is denial**, never auto-approval.
- The **two-service split IS the enforcement mechanism**: `banker-copilot-service` (Python, the agent
  loop) registers **ZERO write tools** — its only affordance is `propose_action`.
  `authority-service` (.NET) is the sole executor of agent-originated writes.

## Canonical vocabulary (Danny arbitrated — do not drift)

`supersededByApprovalId` · `PAYLOAD_SUPERSEDED` · entity noun is **approval**
(`proposal` retired; `proposed` survives as a status, `propose` as a verb) ·
action-type ids are `<domain>.<entity>.<verb>`.

**Lifecycle:** `proposed → pending → signed → executed`.
`denied` is the ONE terminal rejection state, carrying a mandatory closed-enum `terminalReason`:
`HUMAN_DENIED` · `POLICY_RUNG_ESCALATED` · `PAYLOAD_SUPERSEDED` · `TTL_EXPIRED`.
There is **no** `expired` state, **no** `voided` state, **no** `execution_failed` state.
Failed execution stays `signed` with `execution.state = failed`; retry needs no new signature but
DOES re-enter the policy gate.

**`policyVersion`:** derived from a content hash of the **resolved** policy (after env overrides),
not file bytes and not semver — because env-overridable thresholds change the ladder while leaving
the YAML byte-identical. Bound into the canonicalized payload hash (RFC 8785 JCS, money as decimal
strings). At execution, re-evaluate: higher rung → signature VOID and re-propose; unchanged or
lower → honor. **Never auto-downgrade.**

## Roster

Danny (Lead/arbiter) · Turk (Backend) · **Rusty (Platform/Infra — hired 2026-09-04 to fill the lane
Basher left)** · Linus (Frontend) · Livingston (QA) · Scribe (commits) · Ralph (monitor).
Ocean's Eleven casting universe. Scribe owns ALL commits — agents must not commit or push.

## Phase 1 — in flight right now

Exit criteria: curl an approval → watch it evaluate to L2 → sign twice from two distinct identities
→ watch the broker execute the downstream call. **Zero LLM involved.**

| Lane | Owner | State |
|---|---|---|
| `authority-service` core (policy engine, approval store, JCS hashing, §5.3.2 gate, sweeper, API) | Turk | in flight |
| Cosmos containers, workload identity (#336), banker/supervisor roles, event-processor audit (#335), gateway route | Rusty | **done** |
| Test plan, property-based rung tests, adversarial review, tamper-testing | Livingston | in flight |
| Approval-schema arbitration (epic §5.2 vs design §5.3) | Danny | in flight |

## Open items

- ~~Approval schema drift~~ **RESOLVED.** `docs/design/banker-copilot-policy-engine.md` §5.3 is
  authoritative; the epic's competing schema was deleted, leaving only a field *inventory*.
  **Layer boundary is now normative:** epic says what must be true, design says what it looks like
  on the wire, design + Terraform say how it is queried, and **no layer restates another**.
  `policy.policyVersion` nesting is correct — §5.3.1 constrains cardinality, not depth.
- ~~`cosignerId` pointer document~~ **OUT, on security grounds.** Keying a pointer on `cosignerId`
  requires naming the co-signer at proposal time, which converts "a second qualified human must
  review this" into "*this named person* must review this" — letting the requesting banker choose
  their own reviewer, i.e. the exact self-dealing L2 exists to prevent. `cosignerId` is deleted as
  a field. **The queue keys on required seniority, never on a person.**
- **Retired duplicate fields:** `execution.signedUnderPolicyVersion` (always equals
  `policy.policyVersion` under §5.3.2 — kept on audit *events*, since the rule is one copy per
  document, not per system) and `distinctIdentitiesRequired` (always equals `requiredSigners`;
  replaced by `mustDifferFrom`, because **a count is satisfied by arithmetic and a miscount passes
  silently, whereas naming the excluded identity is a set-membership test that fails loudly**).
- **§5.3.1b** compares **dotted field paths**, not names — `createdAt` and `proposedAtUtc` were each
  internally consistent, so there was no shared name to grep. The service's real document must
  **equal** the canonical set (only check that catches a .NET serializer mismatch); Python models
  and Terraform paths must each be a **subset**, failing closed.
- **#334 blocks the whole model** — all services share JWT audience `banking-demo` and signing is
  **symmetric HMAC**, so any service holding the validation secret can *mint* tokens, not just
  verify them. Until a mediator-only audience exists, the ladder is bypassable and epic §4.4's
  "four-layer defence" is honestly ~1.5 layers.
- **#336 partially done** — Rusty established the dedicated-identity pattern for `authority-service`
  only; the other services still share one UAMI.
- 4 pre-existing `CosmosSDKVersionTests` fail on a clean tree (hardcoded path) — unrelated, untouched.

## Related issues

#332 epic · #333 trajectory eval (placeholder) · #334 JWT audience/symmetric key · #335 audit gap
· #336 shared workload identity · #140 loan originations port (feeds the ladder its first real
high-value domain; Phase 2 UI boundary amendment proposed in a comment there)

## Standing rules from Brian

- No hardcoded IPs, CIDRs, thresholds or dollar amounts — configuration only.
- Tamper-test every guard: break it, confirm a test fails, revert. A guard never observed failing
  is not proven.
- Test both directions or you have tested neither.
- Commit and push completed work after each feature or issue.
- Don't overengineer.
