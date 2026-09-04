# Livingston — Banker Copilot Phase 2 QA findings

**Requested by:** Brian Denicola
**Branch:** `squad/332-banker-copilot` (no commits, no pushes)
**Plan:** `docs/design/banker-copilot-phase2-test-plan.md`
**Suite:** `src/banker-copilot-service.Tests/` — 215 passing, 2 expected failures, 0 skipped
**Tamper:** 13 guards, 13 PROVEN

---

## What I was testing

The Phase 2 invariant is **agents never approve**, enforced by the service split:
`banker-copilot-service` registers zero write tools, its only write affordance is
`propose_action`, and `authority-service` is the sole executor. I tried to break
that from every direction I could construct.

I could not. The split holds. Four independent guards prevent a write tool being
registered and each was broken individually to prove it is real. Seven decisions
that would let a proposal authorise itself — `execute`, `status`,
`requiredSigners`, `requiredRung`, `policyVersion`, `payloadHash`, `cosignerId` —
are refused **by name** rather than dropped, which is the difference between a
caller learning it is blocked and a caller believing it succeeded.

---

## Findings, in order of what I would act on

### 1. F2-7 — Path-parameter traversal *(open, medium-high)*

`build_request()` substitutes model-supplied arguments into a tool's URL path
with `str.replace()`, no encoding, no validation, and no parameter in the
shipping manifest declares a `pattern`. httpx normalises the result, so an id of
`../../admin/whatever` turns `http://svc/api/transactions/{id}` into
`http://svc/admin/whatever`. Verified directly.

Tool arguments are model-controlled and model context contains tool output, so
this is reachable by prompt injection. The declared path *is* the capability
scope; if an argument can leave it, the scope is advisory.

Blast radius today is GET routes on the six configured downstreams using the
banker's own token — a read-scope bypass, not a privilege escalation, and it
cannot reach `authority-service`, which is not a configured downstream. Fix is a
required `pattern` per path parameter in the loader (fails at startup, better) or
percent-encoding plus rejecting `/` and `..` at substitution time.

**Owner:** Turk.

### 2. F2-6 — Duplicate backlog on stream attach *(found and fixed this session)*

The stream yielded the replay backlog, then unconditionally re-subscribed and
yielded the whole backlog again. A 6-frame run delivered twelve frames on the
wire while its persisted trace held six. The live stream and the trace
disagreed — exactly the drift §8.0 exists to prevent — and the UI would render
every reasoning step twice.

Worth noting *how* it hid: an equality comparison between live and replayed
frames passes when both sides duplicate identically. It was caught by asserting
strict monotonicity of the resumed sequence, not by asserting equality. Turk
fixed it mid-session and the strict marker turned red on the fix, which is the
marker doing its job.

### 3. F2-5 — No invoke-time read-method guard *(open, medium)*

`ToolExecutor.invoke()` hands `tool.target.method` straight to `httpx.request()`.
Nothing at the point of action checks it is a read. The only protection is the
loader allowlist plus a one-off startup assertion — a single layer, far from the
action. Any `ReadTool` built by a path other than `load_manifest()` executes
whatever method it names. Not currently exploitable; no such path exists. But
§4.4 asks for defence in depth, and this is the layer that would survive a
mistake in the others.

**Owner:** Turk.

### 4. F2-4 — Epic §3.2/§3.3 and the shipping loader are mutually incompatible

The epic's tool schema uses `mode`, `actionId`, `authority`, `requiredEvidence`
and `idempotencyKeyFrom`. The loader refuses every one by name. Neither is a
superset of the other, so no single manifest satisfies both documents.

Per my own Phase 1 lesson I have **not** adjusted my expectations to match the
implementation — that is how I nearly shipped a test defending the vulnerable
role model. The test pins the incompatibility instead.

**Needs Danny to rule** which document is the contract; the loser gets amended.
The shipping loader is the stricter of the two, so this is a documentation split,
not a hole.

### 5. F2-2 / F2-3 — `CopilotEventEnvelope` drift *(medium, eval contract)*

Epic §8.0 names an `approval.voided` frame kind; the UI doc §4.2 — which §8.0
itself calls the contract of record — has `approval.terminal` and no `voided`.
§0.1 already ratified `denied` as the single terminal rejection state, so
"voided" is vocabulary that was ruled out. Separately, §8.0 requires token counts
"on model-call frames" and the closed §4.2 union contains no model-call kind, so
that requirement is unsatisfiable as written. #333 needs token accounting.

### 6. F2-1 — Epic §3.3's worked manifest does not load *(low)*

Its `requiredEvidence` references three tools absent from its own six entries, so
fail-closed validation rejects it entirely. The example documenting the contract
cannot be loaded by an implementation of the contract. It is also the artefact
people copy.

---

## Acceptance criteria I am refusing to tick

Same rigour as Phase 1, same reasons where they still apply.

- **Traces durable and replayable from Cosmos** — no Cosmos here. The service
  itself logs "Traces from this process are NOT replayable". Fidelity is proven
  against the in-memory sink, which is not durability.
- **The copilot identity cannot write approvals** — asserted as Terraform *text*
  only. The RBAC grant is real when a subscription says so.
- **End-to-end propose → sign → execute** — `authority-service` is not running.
  The transport is proven against a recording double; the far end is not.
- **Three-pane UI renders a real run** — needs the stack up.
- **These tests run in CI** — **no workflow in `.github/workflows` builds or
  tests any service in this repository.** I refused three criteria for this in
  Phase 1. The reason has not changed, so neither has the refusal.

All five are in `pending-integration.manifest.json`, which **fails** rather than
skips, in both directions: a stale entry whose precondition is now met fails just
as loudly as a dependency that vanished.

---

## Three false passes I found in my own tests

The tamper run reported four guards REDUNDANT. In three cases the guard was fine
and *my test* could not see it:

1. `"/runId" in block` — the same Terraform block lists `/runId` among its
   indexing paths, so changing the partition key left the test green.
2. Grepping `copilotStream.ts` for `Authorization` — the file's own comment
   explains why `EventSource` cannot set that header, so the prose satisfied the
   grep with the header deleted.
3. Asserting only that a self-authorising field was "rejected" — an allowlist
   rejects unknown fields anyway, so deleting the reasoned by-name refusal was
   unobservable.

All three are the Phase 1 redundant-guard shape and all three were invisible
until something was deliberately broken. This is the argument for tamper-testing
in one paragraph: three of my thirteen assertions were decorative, and no amount
of reading them would have told me which three.

---

## The largest thing nobody is testing

**A read tool whose GET has a side effect.**

The manifest guarantees the *method*. It cannot guarantee the downstream's
honesty about it. A `/api/x/{id}/view` that marks something seen, or a report
route that writes an audit row with attributable effects, is a write the ladder
never sees — and it is invisible from the copilot side, because from here it is
a GET that returns JSON.

I cannot close this from `banker-copilot-service`. It wants a test in each
*downstream* suite asserting that its copilot-declared routes are side-effect
free, re-run when that service changes. Twelve routes across six services. I
would rather raise it than let "zero write tools" imply more than it proves.

---

## Nothing left behind

Working tree verified free of tamper residue. No production code modified: my
work is `src/banker-copilot-service.Tests/`, the plan doc, this file and my
history. Turk's own 110 tests still pass alongside my 215.

---

## Follow-up round — F2-5 and F2-7 verified fixed; three new items

### Closed

**F2-5 / F2-8 — invoke-time read-method guard.** Fixed in `executor.py`. Marker
removed. Tamper case `invoke-time-read-method` added and **PROVEN** — broken
deliberately *narrowly* (one method let through, the rest still refused), because
a suite that only ever tried POST would have stayed green against exactly that
shape of mistake.

**F2-7 — path-parameter traversal.** Fixed fail-closed at the loader, more
strongly than the finding asked: the manifest can no longer express an
unconstrained path parameter. Marker removed; seven tests added, including an
independent 20-value escape corpus and a probe-based anchoring proof. Tamper case
`path-pattern-anchoring-probe` PROVEN.

**Standing Phase 1 gap #334 — CLOSED.** Symmetric signing is retired; the harness
holds only the issuer's public key and aborts startup if it finds signing
material or the mediator client secret. New file `test_token_posture.py` (8
tests) plus two tamper cases, both PROVEN separately so neither is masking the
other. Foreign-key, HS256-confusion and `alg=none` forgeries are all refused —
the HS256 token is assembled from bytes, because PyJWT declines to *build* it and
that client-side courtesy is not a defence.

### A defect in my own suite — the third this epic

My F2-5 test reached into `registry._by_id`, a private attribute `ToolRegistry`
does not have. It raised `AttributeError` whether the guard worked or not: it
could not pass when the code was right, and could not fail for the *right reason*
when the code was wrong. **A test that cannot pass proves as little as one that
cannot fail.** Rewritten against `registry.manifest.tools` and tamper-tested, so
I have now watched it go red for the correct reason.

Related, same root: the rogue tool was hand-constructed and broke when
`display_name` was added. It is now derived from a real shipping tool via
`dataclasses.replace` — valid in every respect except the property under test.
**Do not transcribe production types into tests.**

My fixtures were also still exporting `JWT_KEY` and minting HS256 after the RS256
migration landed. That is the same failure class one level up: test scaffolding
asserting against a configuration that no longer ships. It was caught only because
the service refuses to start rather than ignoring the retired variable.

### New findings

**F2-9 (low, mitigated) — CI runs this suite before its dependencies exist.**
`src/*/tests` expands `banker-copilot-service.Tests` before
`banker-copilot-service` (`.` is 0x2E, `/` is 0x2F), and installs persist across
iterations, so this suite ran with only pytest present. Verified in a clean venv,
not reasoned about. It surfaced as a **collection error**, which reads as a broken
build rather than a finding — the worst way for a security suite to fail, because
it invites someone to disable it. Mitigated by adding `requirements.txt`, which
the job honours; the ordering fragility is the workflow's and I have not touched
it. Pinned by a test so the reasoning is re-derived if the order changes.

**F2-10 (medium) — the CI quarantine patterns match nothing.** The blocking
`ui-app` job ignores `src/components/{DocumentUpload,AgentPipeline}.test.tsx`,
but both files live under `src/components/account-opening/`. Neither pattern
matches, so both pre-existing failing suites still run in the blocking job — and
also in the non-blocking quarantine job, whose substring pattern does work. So
they run twice and fail the build once. Verified with `craco test --listTests`
using the exact patterns.

Same shape as F2-7 one layer up: `--testPathIgnorePatterns` takes **regexes**,
not paths. It reads in review as "those two are handled" while the gate is red
for precisely the reason someone believed they had handled. Recorded as a strict
xfail; asserted by applying the runner's own regex semantics rather than by
checking the string names a file.

### Ledger — promoted honestly

`ci-runs-any-of-this` is **removed**. Its premise ("no workflow builds anything")
became false, the ledger failed it in the correct direction, and the coverage
moved to `tests/production/test_ci_runs_this_suite.py` (11 tests): a workflow
parses, a pytest step's glob expansion actually includes this project, the four
build jobs are not `continue-on-error`, the .NET job covers the Phase 1
`authority-service.Tests`, and this project can install its own dependencies.

**Still not ticked, and the refusal is unchanged by CI arriving:**
`cosmos-trace-durability`, `workload-identity-federation`,
`authority-service-round-trip`, `ui-three-pane-e2e`, `real-model-tool-choice`,
`gateway-applied`. Every one is blocked on something that does not exist in this
environment — a running Cosmos, a live `authority-service`, a real model, a
deployed gateway — not on anyone not having written it. CI existing does not make
any of them reachable.

The "these tests run in CI" criterion is marked ⚠️ rather than ✅: the workflow
exists and the Python job is green in a clean-venv simulation, but the ui-app job
is red because of F2-10.

### Note on the repository state

The working tree is mid-merge — `.squad/agents/basher/history.md` (DU) and
`.squad/skills/redis-stream-consumer-resilience/SKILL.md` (AA) are unmerged. Not
mine to resolve, and I have committed nothing; flagging it because a CI run from
this tree would not reflect what anyone intends to merge.

### Verification

- Suite: **266 passed, 2 xfailed (both F2-10), 0 skipped, 0 errors.**
- Same result in a venv built only from this project's `requirements.txt`.
- Tamper harness: **17 of 17 PROVEN**, none REDUNDANT, none UNREACHABLE.
- `session-ownership` is proven but weakly: the broken guard makes the request
  *hang* rather than return the wrong answer. It counts, but a hang is a less
  crisp red than an assertion, and it is worth knowing that is what one would see.
- All four tampered anchors confirmed restored; no residue in the working tree.
