# Now — what the team is focused on

**Updated:** 2026-09-08 (Monday)
**Epic:** #332 Banker Copilot — a hosted agentic harness for the banker/admin side.
**Branch:** **`332-beta`** — the integration branch. **All work merges here. `main` is not touched.**
`squad/332-phase3-supervisor` (PR #352) is contained in it and is no longer where work happens.

---

## THE BRANCH RULE (Brian, 2026-09-08) — read before you push anything

> *"i want 332-beta to be the branch that all work to be merged into. Nothing to touch main until
> i deploy and test and validate the feature works as i want in 332-beta."*

**`332-beta` is the only integration target.** Every branch — squad lanes, dependabot, fixes found
during deployment testing — merges into `332-beta`. Nothing merges to `main`, and `main` is not a
base for new work. The gate to `main` is **Brian's own validation of the deployed feature**, not
CI, not a passing suite, and not a coordinator's judgement that it looks done.

`332-beta` was cut from `squad/332-phase3-supervisor` (which already contained `main` and the
Phase 2 branch) and holds **16 merged PRs**: #352 plus 15 dependabot.

- **#346/#347/#348 conflicted** — `agent-framework-core` and `agent-framework-foundry` each rewrite
  the same two-line block of the same `pyproject.toml` in three services. Resolved to the **union**
  (core 1.17.0 + foundry 1.11.0). The resolution asserts both sides are byte-identical before
  collapsing the conflict, so it cannot silently discard a real difference.
- **#340 (AzureRM `~> 4` → `~> 5`) is deliberately OUT.** A provider major is a state migration, not
  a dependency bump: the environment's state was written by v4, and every `terraform output` that
  `task cloud:deploy` reads (ACR name, Cosmos endpoint, workload-identity client ids) would then run
  against a provider that may demand a state upgrade first. Now pinned in `.github/dependabot.yml`
  by provider name — **note the existing `terraform-minor-patch` group does NOT suppress majors**;
  ungrouped majors still arrive as their own PR, which is exactly how #340 appeared.
- **No PR is open against `main`, and none will be.** Brian, 2026-09-08: *"no PRs will be open
  against main."* All 16 were **closed, not retargeted** — GitHub rejects a base change once the
  head is already contained in the new base (`There are no new commits between base branch
  '332-beta' and head branch ...`), so closing with a comment pointing at `332-beta` is the only
  available move. The commits are all in `332-beta`; nothing was lost. #340 was closed with
  `@dependabot ignore this major version`.
- **Dependabot is PAUSED** — `open-pull-requests-limit: 0` on all 28 entries in
  `.github/dependabot.yml`, because a bump arriving mid-validation changes the code under test
  without changing what is being tested, and the ACR images would quietly stop matching the branch.
  **Security updates are deliberately NOT paused.** Resume by deleting those 28 lines — but note
  Dependabot targets the repo's DEFAULT branch, so resuming while `main` is default puts new PRs
  straight back on `main`.
- `authority-service` and `banker-copilot-service` had **no dependabot coverage at all** until
  2026-09-08 — the sole executor of agent-originated writes and the component a prompt-injection
  payload reaches first were the two services receiving no updates. Now covered (nuget/pip/docker).

---

## READ THIS FIRST — where we actually are (2026-09-08, late afternoon)

**Testing target is AZURE, not local.** Brian, today: *"we're in phase 3 and I want to test it in
Azure - not locally (I don't know why the last session kept wanting to test locally)."* Earlier
revisions of this document sent readers to `task local:run`. **That was wrong.** Verification runs
against the deployed cluster: `https://onlinebankingdemo.bjdazure.tech` (public DNS, valid TLS,
no `-k` needed), namespace `banking-demo`, AKS `model-osprey-55220-aks`, RG `model-osprey-55220-rg`.

**Do not merge to `main`.** The gate is Brian's own validation of the deployed feature.

### The two findings that dominate everything else

**1. The supervisor was a script, not a model. FIXED, deployed, live.**

`deterministic_decider` returned `"proceed"` whenever its own reads succeeded. The primary
*proposed* the action, so its position was also `"proceed"`. **Agreement was therefore 100% by
construction** — disagreement was only reachable via an infrastructure read failure — and the UI
rendered this as a `0.8`-confidence independent review. Check 4.2's failure mode, exactly as
`planner_mode()`'s own docstring predicted: *"Reviewers checking supervisor disagreement would have
been measuring a script and reading it as agreement."*

Fixed in `87a0ee4`: `app/planner/supervisor_model.py` (`FoundryDecider`, fail-closed to `hold` /
`confidence 0.0` / `supervisor_unavailable` on every failure path), wired in `lifespan.py`, gated
by a **declared** `COPILOT_SUPERVISOR_MODE` that raises rather than silently degrading. 32 tests,
four guards tamper-tested. Live inference proven from inside the pod (private endpoint
`10.23.4.20` → workload identity → RBAC → `gpt-5.4-mini`). Pod startup logs
`"supervisor_mode": "foundry"`.

> **Related, still unruled:** the **planner itself has never called a model either.**
> `FoundryChatClient` is imported at `loop.py:43` with `# noqa: F401` and nothing else.
> `Planner.run` uses `_plan_steps()`, a deterministic policy-derived plan. That may be correct by
> design — steps *are* policy-derived — but `planner_mode: foundry` proves config exists, not that
> a model runs. **Brian has not yet ruled on whether this matters for the demo.**

**2. THE CURRENT BLOCKER — no Copilot run can complete at all.**

Four read tools point at **admin-only** upstream endpoints, and the copilot calls upstream with the
**banker's** bearer token:

| toolId | upstream | blocks |
|---|---|---|
| `list_login_audits` | `/api/admin/login-audits` (user-service) | **`user.unlock` (L2)** |
| `get_scored_transaction` | `/api/admin/scored-transactions/{txId}` (ai-service) | **`transaction.score.override` (L2)** |
| `get_flagged_transaction` | `/api/admin/flagged-transactions/{txId}` | `transaction.flag.review` (L1) |
| `list_flagged_transactions` | `/api/admin/flagged-transactions` | case discovery |

Proven live, trace `run_5ed954af071b4ebc`:
`list_login_audits → "upstream returned 403"` → `step.failed "evidence gathering failed"` → run
failed. Chain: evidence 403s → planner never proposes → no approval → `requiredRung` never `L2` →
**the mandatory fan-out never fires → the supervisor model is never invoked.** Confirmed by zero
`"Supervisor second opinion"` lines in the pod despite runs being driven at it.

**Both L2 actions are blocked, so check 4.2 is unmeasurable until this is fixed.** Turk owns it.
Candidate mechanism already in the codebase: every tool declares a `capabilityScope`
(`identity.read`, `risk.read`, …) and `config/authority-policy.yaml` has a `capabilityScopes`
section. **Do not fix this by granting `banker` admin** — that is the god-rights failure in a new
costume, and `RoleHierarchy.cs:64-71` (admin = seniority 0, implies nothing) is ratified and must
not be modified.

**This is very likely the real cause of the empty copilot queue (#356), not missing seed data.**
The queue was assumed to need data; in fact no run could ever complete to put anything in it.
Both halves are now in flight — Turk on authorization, Rusty on `task demo:seed|show|reset`.

### Do this, in this order

1. **Land Turk's authorization fix**, then confirm a run reaches a proposal. Signal:
   `kubectl logs -n banking-demo -l app=banker-copilot-service | grep -c "Supervisor second opinion"`
   must be **> 0**.
2. **Land Rusty's `task demo:seed`** (#356) so the two L2 actions have real subjects — specifically
   a genuinely *locked* user and a *scored* transaction. **Brian runs the first seed himself.**
3. **Then measure §4.2.** Livingston's harness is committed (`9073b78`) and re-runnable. Standard:
   30+ runs, and **`hold` + `confidence 0.0` + `supervisor_unavailable` is a FAILED MODEL CALL, not
   a disagreement** — it must be counted as a third category or the number lies again.
4. **§7.2, 7.4–7.7 need Brian at a browser with two identities.** 7.4 is a visual judgement only he
   can make. Blocked until seed data lands.

Checklist lives at `docs/design/banker-copilot-deployment-verification.md`.

### Verification scoreboard (live, this session)

~24 pass · **4.2 blocked** · 4.1 source-confirmed · **6.2 documented** (see below) · 9 cut ·
7.2/7.4–7.7 pending Brian at a browser.

**6.2 — ruled document-don't-build, done in `2ed48a0`.** `event-processor` has *no persistence
whatsoever*: `go.mod` carries Redis/OTEL/`azidentity` only, and `processMessage` emits `slog`
records to stdout. Its README claimed Cosmos audit-log storage in **five** places. That made it the
dangerous class of defect — not incomplete but *lying* — so the claims were corrected and the
checklist's unpassable "Audit rows appear" restated. **Do not cite this service as the audit system
of record.**

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

## Phase 3 — COMPLETE (in PR, not yet merged)

Supervisor agent with **blind construction** (it must not see the proposing agent's reasoning) ·
fan-out engine · co-signature flow · supervisor queue (cross-partition, **no pointer doc** — the
`cosignerId` pointer was deleted because it let a banker choose their own reviewer) ·
payload-mutation void path · L1-only batch approval.

### Delivered

- **Blind construction (headline).** `src/banker-copilot-service/app/planner/fanout.py`.
  `build_supervisor_input(intent)` takes **one** parameter, so the primary's output has no
  argument to travel through. Independence is a property of the signature, not a promise to
  ignore an argument. `BankerIntent` is a frozen dataclass carrying only the banker's own words
  and the raw entity ids — verified there is no smuggling channel through it either.
- **Fan-out engine** with all bounds from `config/harness-limits.yaml`, fail-closed, no fallback
  literals. Harness still boots `writeTools: 0`.
- **Co-sign queue seniority** derived from `rungs.L2.cosignerRoles`, not a magic `2`.
- **Out-of-band notification sinks** (`INotificationSink`), config-driven, naming the *kind* of
  signer awaited, never a person; never gates state.
- **Co-signature UI**, signing identity display-only behind server-supplied `callerMaySign`.
- **Payload-supersede void path**: no signature survives a replan; both L2 slots re-open.

### Verified state (all green locally)

| Suite | Result |
|---|---|
| .NET (6 projects) | **482 passed** — authority `.Tests` 224, `.UnitTests` 129, account 29, prompt-eval 31, transfer 19, user 50 |
| Python (6 services) | **865 passed** — banker-copilot 177, `.Tests` 298, account-opening 169, ai 130, chatbot 56, budget 35 |
| ui-app (blocking) | **19 suites / 206 tests** |

`transaction-service.Tests` still blocked **locally only** by a root-owned `obj/`
(`sudo rm -rf src/transaction-service.Tests/obj`). CI is unaffected.

### What coordinator verification found — read this before trusting a green suite

Every lane's claims were re-tested rather than accepted, and **four guards were correct in logic
but held by no test**:

1. `isBatchEligible` has four conditions. Each could be broken alone with the full suite green;
   only breaking two together went red. Worst was `callerMaySign === true` → `!== false`, which
   differs on exactly one input — `undefined`. An **absent authorization field would have read as
   permission**, the same shape as the Cosmos zero-rows mismatch and the `envFrom` hyphen drop.
2. The two execution-time re-verifications in `ApprovalService.cs` (quorum at ~L520, SoD at ~L532)
   could **each be deleted with all 350 .NET tests passing**, while `ApprovalsController.cs:116`
   exposes `POST /{id}/execute` publicly. The path was: propose L2 → sign once → call execute.
   Both are now pinned by `authority-service.UnitTests/ExecuteReVerificationTests.cs`, which drives
   `/execute` directly and asserts on the **downstream side effect** (broker never called), not the
   status code — so a refactor that returns 409 *after* executing still fails. Includes a positive
   control proving the refusals come from the checks and not the fixture.

**Standing rule this produced: a guard protected only in aggregate is a guard that erodes
silently.** Where several conditions defend one invariant, each needs a test that fails for its own
reason. Prove it by tampering each condition alone and reading the diagonal.

### Honest non-ticks

- ~~`fanout.py` is imported by **nothing outside its own tests** — no route reaches
  `build_supervisor_input`. The engine is built and unit-proven; **wiring is Phase 4**.~~
  **FALSE — struck 2026-09-08.** It was already wired at `6b0db49`: `loop.py:197` calls
  `run_second_opinion`. This claim originated in a QA report, was repeated by the coordinator
  without verification, and Turk disproved it with the line number. Recorded rather than deleted
  because the *failure mode* matters: an unverified claim was restated until it read as fact.
- No Foundry endpoint here: the fan-out loop under a real model is unexercised, as is whether the
  supervisor ever genuinely *disagrees*. A 100%-agreement supervisor is a rubber stamp and would
  present as success — this is item 4.2 of the deployment checklist and the highest-value thing to
  watch on Monday.
- No running backend: live SSE and co-signature round-trips remain unproven.
- **F3-1 (latent, accepted):** `PolicyLoader` never validates `Batchable`, so marking an L2 action
  batchable would load without error. Deliberately left open — see
  `turk-phase3-batch-l1-only.md`. Pinned by a config tripwire, not a false-pass test.

#334 is no longer a blocker; it landed in Phase 2.

Carry-over, still open: Linus's comparison recorder has **no call sites and no exporter**.
Instrument Classic Admin and the harness together in one pass, never separately, or the two
surfaces get different counting rules and the comparison Phase 5 exists to enable is worthless.

---

## Weekend of 2026-09-06/07 — six commits since Phase 3, all pushed, all in PR #352

`6b0db49` Phase 3 · `c1ddd12` mutation repair · `0392969` `a0d0589` `c523311` envelope ·
`86bbf9b` SSE mapper · `125cdcd` container build.

### The wire contract — SETTLED. Do not relitigate.

There is **ONE mapper**: `toApproval` at `src/ui-app/src/api/authorityWire.ts:292`. REST called it
7×; **SSE bypassed it entirely — zero calls. That asymmetry was the root defect.** `86bbf9b` routes
SSE through it. The supervisor rides as `agentAssessment.supervisor`, and `toAssessments`
(`authorityWire.ts:232-259`) derives `role` **structurally from the key**, which kills the role bug
by construction rather than by a check.

**The backend must NOT client-shape the payload.** This was litigated and settled the hard way:
the coordinator ruled that it should, Turk overturned the ruling with code, and the coordinator
verified all three of his claims and conceded. Backend shaping forces either a duplicated
`flattenPayload` in Python or an emitted `payload: []` — and **`[].every()` is `true` in
JavaScript**, so an empty payload makes `disclosureSatisfied` *vacuously true* and silently
defeats the disclosure gate. Backend emits **wire** shape. The UI maps. Once.

The handshake is frozen in `tests/fixtures/copilot-wire-envelopes.json` — **a single shared
statement of the shape, read by both the Python and the UI tests**, holding a real primary-`APPROVE`
vs supervisor-`DECLINE` disagreement. Verified to **throw when absent** (deleted it to check).
Regenerate only via `COPILOT_REGEN_GOLDEN=1`, and **never to make a test pass** — that inverts it
from an oracle into a mirror.

### Mutation testing — repaired, and it found something real

Three faults: mutmut was installed **unpinned** so 3.x arrived silently and broke a 2.x invocation
(now `mutmut==3.7.0`); **`|| true` masked the failure**, making a run that never started look
identical to one with nothing to report (removed — verified mutmut exits 0 with survivors and
non-zero only when it cannot run); and `conftest.py` computed `REPO_ROOT` by fixed depth while two
sibling modules **restated** it at a different depth, all three breaking when mutmut 3.x copies
source into a deeper `mutants/` sandbox. Now one walk-up helper that **raises** when it finds no
marker; the duplicates **import** it.

First real run: **873 mutants, 517 killed, 356 survived.** One was a genuine defect — in
`_confine_to_one_segment` (`app/tools/executor.py:92`), flipping `or`→`and` makes the
control-character check **unsatisfiable**, and all 177 tests stayed green. Now pinned with each half
of the `or` isolated plus a positive control.

**Equivalent mutant, recorded so nobody wastes a day on it:** `quote(raw, safe="")` → `quote(raw)`
survives *correctly* — `/` is already refused by `_SEGMENT_BREAKERS`, so no input distinguishes them.

### Container build — was broken repo-wide, and NOT by this epic

`user-service` failed identically on `main`. Three compounding causes: `src/shared/Auth` was
referenced by all six .NET csprojs and COPYed by none of their Dockerfiles; the `.dockerignore`
allowlist never listed `authority-service`, `banker-copilot-service`, `src/shared/Auth`, or the
config files; and `shared/Auth` embeds `config/jwt-audiences.yaml` resolving to `/config` in-image,
so allowlisting was necessary but not sufficient — nothing COPYed it there. `125cdcd` fixes all
three. Result: **all 13 images, zero errors.**

**ACR remains UNPROVEN.** Images were built **locally with BuildKit**. `az acr build` compiles
ignore rules to anchored regexes in Python (`_archive_utils.py`) with different semantics, and our
allowlist re-includes *individual files* inside a directory excluded by `*`. Rules deliberately
carry **no trailing slashes** (`az acr build` only strips them for `!` negations, so `foo/`
silently never matches — this once took a context from 323 MiB to 0.2 MiB). That reasoning is
sound but **untested**. One `task cloud:build` against `modelosprey55220acr` settles it; watch that
the upload context stays ~1 MiB.

### Verified baselines as of `125cdcd` (re-measured, not carried forward)

| Suite | Result |
|---|---|
| .NET | **482 passed** |
| Python — banker-copilot | **193 collected** (was 177 at Phase 3) |
| ui-app blocking | **20 suites / 212 tests** (was 19/206), using CI's exact quarantine regexes |

---

## Monday 2026-09-08 — deploy for testing

**Environment is built.** Azure logged in (`BJD_Core_Subscription`,
`ccfc5dda-43af-4b5e-8cc2-1dda18f2382e`), kubectl context `model-osprey-55220-aks`, ACRs include
**`modelosprey55220acr`** (Premium, same RG as AKS). Docker 27.3.1 running locally; all 13 images
built. **The stack has never been started.**

**Use `task`, never ad-hoc commands.** `task local:run` = `docker compose --env-file .env up -d
--build` **with an `_init-env` dependency**. Bare `docker compose up -d` skips both the env file and
`_init-env` — the coordinator made exactly this mistake on Friday. Targets live in
`tasks/Taskfile.{local,cloud,e2e,lint}.yml`.

**KNOWN DOC BUG, not yet fixed:** `docs/design/banker-copilot-deployment-verification.md` §"Running
the stack" says `task build` then `docker compose up -d`. **That is the wrong command** and it will
teach every reader the same mistake. Fix it to `task local:run`. Brian was asked and the session
ended before he answered — **confirm with him first.**

### Change control — Brian's rules, in force

- **Confirm before ANY action touching his machine or Azure** — builds, containers, deploys,
  deletes. Reading files unprompted is fine. This rule exists because the coordinator removed 16 of
  his containers, built 13 images and tried to start the whole stack, none of it asked for. He said:
  *"i don't want you to go off ever and do things without my oversight."*
- **PR always. Never merge to `main` directly, and not at all until end-to-end testing passes.**
- **Skip coverage metrics entirely** — mutation testing only.
- Ensure a fix lands **in the code**, not just in local machine state.
- Don't overengineer.

### Still unproven — the honest list

- The stack has never run. Live SSE, co-signature round-trip, and Cosmos trace durability are all
  unexercised over HTTP.
- Whether the supervisor genuinely disagrees (§4.2). **Failure here presents as success.**
- ACR build path (above).
- Two pre-existing health endpoints fail open (`budget-service`, `chatbot-service`) — flagged,
  out of scope, do not scope-creep into them.
- `.squad/decisions/inbox/` (gitignored) holds Turk's and Linus's decision records; they should be
  promoted into tracked `records/` and indexed.

---

## Standing notes

- Background agents do NOT survive a CLI crash; work on disk does. Recovery is: read this file,
  run the builds/tests, re-spawn lanes with full context.
- **Docker images HAVE now been built** (all 13, `125cdcd`) — the older note saying otherwise is
  superseded. They have still never been *started*.
- **THE RECURRING LESSON — duplication is the bug.** Every major defect this epic has produced lived
  in a **seam between two independently-stated facts, each internally coherent**: two statements of
  the repo root; two statements of the approval envelope; the demo fixture stating the shape the
  reducer wanted while the service stated another. The fix is never to reconcile the two copies —
  it is to **delete one side** so there is nothing left to drift.
- **The fail-open-on-absent-field family — found ~6 times now.** `callerMaySign === true` vs
  `!== false` (differs only on `undefined`); a role-less assessment rendering as primary;
  `[].every()` being `true`; `NullAuditPublisher` logging no warning; Cosmos returning zero rows
  rather than an error. Counter-example done right: `manifest.py:287` defaults to `True`
  *specifically so that absence raises*. When you see a new field, ask what an **absent** one does.
- **A guard protected only in aggregate erodes silently.** Where several conditions defend one
  invariant, each needs a test that fails for **its own reason**. Break each condition **alone** and
  read the diagonal.
- **Verify, don't relay.** Two claims in this file's history were wrong because a report was
  repeated without checking (`fanout.py` unwired; the backend-shaping ruling). Both were caught by a
  specialist who brought line numbers. Bring line numbers.
- Unproven and honestly flagged: Cosmos trace durability, workload-identity RBAC, authority
  round-trip, UI e2e, real-model tool choice, deployed gateway, and the SSE path (needs one
  `curl -N`). **Docker daemon and images are no longer a blocker — see Monday section.**
