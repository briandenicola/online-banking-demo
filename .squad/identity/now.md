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

## Phase 1 — COMPLETE (committed `c0389be`, pushed)

Exit criteria: curl an approval → watch it evaluate to L2 → sign twice from two distinct identities
→ watch the broker execute the downstream call. **Zero LLM involved.**

| Lane | Owner | State |
|---|---|---|
| `authority-service` core (policy engine, approval store, JCS hashing, §5.3.2 gate, sweeper, API) | Turk | **done** |
| Cosmos containers, workload identity (#336), banker/supervisor roles, event-processor audit (#335), gateway route | Rusty | **done** |
| Test plan, property-based rung tests, adversarial review, tamper-testing | Livingston | **done** |
| Approval-schema arbitration; Phase 5 coexistence | Danny | **done** |
| Feature-flag scaffolding + comparison methodology | Linus | **done** |

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

---

## Phase 1 verified state (as of commit `c0389be`)

- `authority-service` builds clean, **0 warnings / 0 errors** (.NET 10)
- `authority-service.UnitTests` (Turk): **121/121 pass**
- `authority-service.Tests` (Livingston): **199/199 pass**
- `user-service.Tests`: 46 pass, **4 pre-existing failures** in `CosmosSDKVersionTests` —
  it hardcodes `RepositoryRoot = "/home/brian/code/online-banking-demo"` but this checkout is
  `foundry-online-banking`. Unrelated to this epic; do not "fix" by editing our code.
- `event-processor`: builds and tests pass
- `docker compose config` and `kubectl kustomize` validate

### Security fixes that landed in Phase 1 (found by testing services TOGETHER)

Each file was internally coherent; the bugs only existed in the seam between them.
- `banker.claimValues` included `user`/`User` → a retail customer's token satisfied an L1 slot
- `admin` at seniority 3 (above supervisor) and in `L2.cosignerRoles` → one admin identity could
  satisfy BOTH L2 signatures
- Cross-role claim aliases (`manager`→supervisor, `administrator`→admin)
- `admin` on all seven capability scopes
- Env-overridable `supervisor_seniority` → an operator could lower dual control to peer level
  without touching a role file
- No proposal floor → a customer could seed a supervisor's queue

**Root cause:** one `seniority` integer carried two different meanings (platform power vs banking
authority). Now split into `outOfHarness` + `platformRoles` vs banking `seniority`.
**Durable fix:** `authority-service` consumes `role-hierarchy.yaml` and **fails closed at startup**
on divergence. The role model is no longer stated in two places.

## Phase 5 — CHANGED (Brian, 2026-09-04)

No longer "admin tab retirement." The tabs **stay**, behind a runtime feature flag, so the two
experiences can be compared. This makes the "harness is better" claim falsifiable rather than
rhetorical, and gives a control group for §9 risk #1 (approval fatigue).

- The flag is a **presentation toggle, NOT a security control.** No compensating control behind it.
- Accepted caveat (#337, closed as accepted): admin tabs are a write path that does not traverse
  the ladder. Does NOT violate the invariant — a human at a tab is a human acting directly.
  **Audit parity is deliberately out of scope. Brian: "since this is demo, i'm okay with that gap."**
- We may therefore NOT claim "every mutating action is audited" — it is false. The comparison is
  about **experience, not governance**.
- Admin tabs' entire mutating surface is 3 call sites in `AdminUserManagementTab.tsx`
  (delete, lock/unlock, reset-password). All 4 writes are **never-published**, a different class
  from the published-but-unaudited events Rusty fixed.

## Next: Phase 2 — Harness shell, single-threaded

`banker-copilot-service` (FastAPI) scaffold · tool manifest registry, fail-closed · read tools only
· `propose_action` as the SOLE write affordance · planner loop + SSE · `/copilot` three-pane UI ·
`CopilotEventEnvelope` persisted to `copilot-traces` (§8.0) — the eval contract lands WITH the
harness, not later · gateway `/api/copilot/` with buffering off.

**Exit:** the flagged-wire narrative §1.3 steps 1–5 end to end.

Carry-over into Phase 2: Linus's comparison recorder has **no call sites and no exporter** yet —
deliberately deferred so both surfaces get identical counting rules in one pass. Instrument Classic
Admin and the harness together, never separately.

---

## Phase 2 — COMPLETE (in PR, not yet merged)

Brian: **PR always — never merge directly.** Phase 2 ships as a pull request from
`squad/332-banker-copilot`.

| Lane | Owner | Landed |
|---|---|---|
| `banker-copilot-service` (FastAPI): tool manifest, read tools, `propose_action`, planner loop + SSE, `CopilotEventEnvelope` | Turk | yes |
| Cosmos `copilot-sessions`/`artifacts`/`traces`, workload identity, `/api/copilot/` gateway, compose+kustomize | Rusty | yes |
| `/copilot` three-pane UI, live trace pane, approval card with payload hash | Linus | yes |
| Phase 2 test plan, zero-write-tools proof, envelope replay fidelity, adversarial review | Livingston | yes |

**#334 (RS256/asymmetric tokens) was pulled forward into Phase 2** at Brian's direction and has
landed — confirmed the hard way, when QA's own fixtures were still minting HS256 and the service
refused to start. The fail-closed design caught QA.

### Verified test state

| Suite | Result |
|---|---|
| `authority-service` build | clean, 0 warnings |
| `authority-service.UnitTests` | 121/121 |
| `authority-service.Tests` | 199/199 |
| `banker-copilot-service` | 162 passing |
| `banker-copilot-service.Tests` | 266 passing, 0 skips, 17/17 tamper cases proven |
| `user-service.Tests` | 50/50 |
| `account-service.Tests` | 29/29 |
| `event-processor` | builds, vets, tests pass |
| `ui-app` | 18 suites / 181 tests; 2 pre-existing suites quarantined |

**CI is green.** All four blocking jobs pass on PR #338. The fifth job, `ui-app quarantined
suites`, is red by design (`continue-on-error: true`) so two pre-existing failures stay visible
and countable rather than deleted.

**Still not runnable on this machine:** `transaction-service.Tests` has a root-owned `obj/` from
an old containerised build. Needs `sudo rm -rf src/transaction-service.Tests/obj`. CI runs it
fine. The `obj.root2` workaround directory became root-owned itself — do not add a ninth alias
to `Directory.Build.props`, delete the originals.

### What CI found on its first run

Four of five jobs failed, and **none of the failures were caused by this epic**. All were
pre-existing conditions nobody could see, because three of these suites had never run anywhere.

- **6 Redis TLS security tests** (issue #38) opened files under a hardcoded
  `/home/brian/code/online-banking-demo` — one machine, and the repo's *former* name. They had
  never verified anything anywhere else. **Third instance** of this exact defect.
- **7 transfer-service failures** from three stale contracts: a loose Redis mock returning null,
  tests predating a fail-closed account-ownership check, and an assertion on a `Pending` status
  the service no longer produces. The controller's ownership check had **no test at all** —
  deleting it would have taken the suite from red to red.
- **9 user-service failures locally, 0 in CI** — the inverse defect. After #334 the issuer reads
  ambient `AZURE_CLIENT_ID` to choose cloud vs local mode, so the suite failed for anyone with
  Azure credentials exported and passed on CI, which has none. It was reporting a property of the
  developer's shell.
- **npm ci** — `react-scripts@5` peer-conflicts with typescript 6.

**The lesson to carry forward:** a test that has never run is not a passing test. Prefer failing
loudly over skipping, and never let a suite's outcome depend on ambient environment.

### Security defects found and fixed in Phase 2

- **F2-7 / F2-8 path traversal** — a tool's declared path could be escaped (`../../admin/...`),
  reachable by prompt injection. The obvious fix would have been a silent no-op: **JSON Schema
  `pattern` is a search, not a full match**, so `[A-Za-z0-9_-]+` happily matches `../../admin`.
  The loader now compiles patterns and proves they reject an escape corpus.
- **F2-10 CI quarantine no-op** — `--testPathIgnorePatterns` takes regexes, not paths. Same shape
  as F2-7, one layer up: a string that looks like a path, evaluated as a pattern, failing open.
- **Vacuously-passing security audit** — `CosmosSDKVersionTests` hardcoded an absolute path *and*
  returned success when the file was missing. Issue #35's audit had passed on every machine but
  its author's. Four of us dismissed it as environmental for hours.
- **`authority-service` was never in the image build task** — undeployable, and 320 passing tests
  never noticed.

### Testing policy (Brian's ruling)

**Mutation testing only. Coverage metrics are not tracked at all.** Coverage was green across every
one of the five tests that could not fail for the right reason. Nightly Stryker/mutmut on the
security-critical paths; no break threshold yet, by design.

Mutation testing catches only tests that *cannot* fail. A test asserting the **wrong thing**
survives it cleanly — that class needs spec-derivation discipline and is not automatable.

---

## Next: Phase 3 — Supervisor agent and co-signature

Supervisor agent with **blind construction** (it must not see the proposing agent's reasoning) ·
fan-out engine · co-signature flow · supervisor queue (cross-partition, **no pointer doc** — the
`cosignerId` pointer was deleted because it let a banker choose their own reviewer) ·
payload-mutation void path · L1-only batch approval.

#334 is no longer a blocker; it landed in Phase 2.

Carry-over, still open: Linus's comparison recorder has **no call sites and no exporter**.
Instrument Classic Admin and the harness together in one pass, never separately, or the two
surfaces get different counting rules and the comparison Phase 5 exists to enable is worthless.

---

## Standing notes

- Background agents do NOT survive a CLI crash; work on disk does. Recovery is: read this file,
  run the builds/tests, re-spawn lanes with full context.
- Unproven and honestly flagged: Cosmos trace durability, workload-identity RBAC, authority
  round-trip, UI e2e, real-model tool choice, deployed gateway, and the SSE path (needs one
  `curl -N` at MVP). Docker images have never been built — no daemon in this environment.
