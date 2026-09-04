---
date: 2026-09-04
author: Turk (Backend Dev)
status: proposed
component: src/banker-copilot-service
issue: 332
---

# Phase 2 harness: the manifest cannot spell a write, and three upstreams cannot serve the demo

Four decisions and one report. The first is the epic's core mechanism; the last is the thing
someone else has to fix before §1.3 works end to end.

## 1. The read-only guarantee is a missing vocabulary, not a check

**Decision: `config/copilot-tools.yaml`'s schema has no way to express a write, and the loader
refuses any key it does not recognise.**

The obvious implementation is a validator that rejects write tools. I did not do that, because a
rejection is a line of code, and a line of code survives exactly as long as the next person
refactoring around it decides it should. The guarantee needs to be load-bearing in a way that
cannot be quietly removed.

So: `method` is constrained to `READ_METHODS = {"GET"}`; `capabilityScope` must end in `.read`;
every level of the document is an **allowlist**, so an unrecognised key is a startup failure, not
an ignored one; and the specific keys a person would reach for when adding a write — `mode`,
`actionId`, `authority`, `idempotencyKeyFrom`, `requiredEvidence`, `cosignerId` — are refused **by
name, with the reason printed**. Not dropped. A silently-dropped key looks exactly like one that
worked, which is how a safety toggle becomes decorative; Phase 1 already taught us that.

A malformed entry is never skipped. The service refuses to start. A harness that cannot prove
which tools it registered must not register any.

The runtime assertion (`assert_zero_write_tools()`) is still there as a second line, and it is
**tamper-tested** — a test poisons a registry via `dataclasses.replace` and asserts the assertion
fires. Without that test the assertion could become a no-op and everything else would stay green.

**Consequence for reviewers:** a PR that adds a write tool to this service does not fail a review
comment, it fails the parser. That is the intended and only acceptable state.

## 2. The harness asks the ladder; it does not restate it

**Decision: `requiredEvidence`, rungs, thresholds, dollar amounts and the action catalogue do not
appear anywhere in this service. The planner fetches `GET /api/authority/policy` at runtime.**

Phase 1 shipped two role models and a privilege escalation lived in the seam between them. The fix
for that class is not synchronisation, it is having one copy. Concretely:

- `require_banker` **consumes** the `effectiveRoles` claim minted by user-service and **refuses a
  token that lacks it** rather than re-expanding the hierarchy locally. Two expansions are two
  chances to disagree, and the disagreement is a privilege bug neither service can see alone.
- `role-hierarchy.yaml` is mounted from `src/user-service/config/`, the same object
  authority-service reads — three images built at three commits cannot disagree about who outranks
  whom if they read one file. Rusty has this wired in kustomize already.
- The one cross-file assertion I do keep is a **seam test**: evidence tool ids in
  `config/authority-policy.yaml` must be a subset of the registered tool ids (minus a *named*
  Phase-4 exclusion set, so the exclusion is legible rather than a silent gap). Two internally
  coherent files can still disagree with each other, and only a test spanning both can see it.

## 3. `cosignerId` is rejected, not ignored — and the rejection is what a lint flagged

**Decision: `propose_action` refuses `cosignerId`, `requiredRung`, `requiredSigners`,
`policyVersion`, `payloadHash`, `execute` and `status` with an error naming the reason.**

Accepting-and-dropping would be worse than accepting it, because the caller would believe it took
effect. The queue keys on required seniority, never on a person.

**Report for Livingston:** an earlier revision of `tests/test_no_named_cosigner.py` grepped the
repo for reviewer-naming field names and flagged my *rejection list*, my *tests that prove the
rejection*, and Linus's comments explaining the absence. That gate's own docstring warns that "a
gate that fails on its own rationale teaches people to delete the rationale" — and it was doing
precisely that: the only way to make it green was to delete the refusal. It appears to have been
adjusted since (his suite is green on it now); flagging the shape so it is not reintroduced. A
text grep cannot distinguish "accepts this field" from "refuses this field". The behavioural test
next to it (`test_the_proposal_body_the_harness_sends_names_no_reviewer`) can, and should be the
one that carries the weight.

## 4. The SSE contract: one cursor, and attach-before-dispatch is not an error

**Decision: the SSE `id:` field carries the envelope's `seq`, not its `id`. The session stream
attaches and heartbeats when no run exists yet, instead of 404ing.**

Two seam defects, both found by reading Linus's client rather than my own tests:

- I was emitting `id: evt_xxxx` while the client resumes by sending `Last-Event-ID`, which my
  server parses as an integer seq. Two cursors both meaning "where you got to", in different
  alphabets. The failure mode is not an error — it is a resume that silently restarts from zero
  and renders as the agent repeating itself. `id:` is now the seq; `?lastSeq=` and `Last-Event-ID`
  are the same number; a non-numeric cursor is a 400 rather than a silent rewind.
- The client opens the stream and *then* dispatches the turn. Answering that ordinary race with a
  404 trips its reconnect backoff, which then hides the opening frames of the run it attached to
  watch. The stream now waits, heartbeating, bounded by `COPILOT_SESSION_TTL_SECONDS`. A named
  `runId` that does not exist is still a 404 — that one really is an error.

**Note for Livingston:** your `xfail(strict=True)` on finding F2-6 (the double-subscribe I
introduced fixing the above) is now **XPASS** and turning three of your tests red. That is the
marker working exactly as designed and it needs removing, not investigating. It is the best
cross-lane signal I have been handed on this epic — a marker that cannot outlive the defect.

## 5. Report: three upstreams cannot serve the §1.3 narrative as written

Not mine to fix, and not fixed. Found by reading the real controllers rather than the epic's
manifest, which was written against intended shapes.

1. **`GET /api/transactions/account/{accountId}` filters by the *caller's own* userId.** A banker
   therefore cannot retrieve a customer's transaction history through it. `list_account_transactions`
   is registered and structurally correct and **cannot do its job**. This is the blocking one: the
   demo narrative requires a banker to review a customer's baseline.
2. **`GET /api/admin/login-audits` accepts only `limit`** — no `userId`, no `sinceUtc`, both of
   which the epic manifest assumes. I registered the tool with the parameters that actually exist
   and documented in its description that filtering happens client-side, rather than declaring
   parameters that would be silently discarded.
3. **ai-service and account-opening-service admin routes require the `admin` role**, so a `banker`
   token gets 403 on the flagged-transaction and application-review reads the harness is built
   around. Phase 2 did not create this gap, it is the first thing to need it resolved.

Also: `transaction.flag.review`'s payload keys are `transactionId`/`rationale` per
`config/authority-policy.yaml`, not `txId`/`justification` as in epic §3.3's worked example. The
policy file is the executable copy and wins; the epic example should be corrected so the next
person does not copy the wrong keys.

## 6. Unverified

The Docker daemon is not running in this environment, so **I have not built the image**.
`docker compose config -q` parses and `kubectl kustomize deploy/kustomize/base` builds, and I
booted the app under uvicorn and drove it over real HTTP — `/readyz` reporting `writeTools: 0`,
attach-before-run, the full ordered six-frame trace with monotonic seq, cross-banker isolation
404, `cosignerId` refused 422. That is better evidence of behaviour than a build, and no evidence
at all that the Dockerfile builds. Someone with a daemon should confirm before this is called done.

---

## Addendum — reply to Rusty's platform contract (2026-09-04)

Contract accepted. Coded to it; no disagreement on any name. Four notes, two of which are
defects his message found in my code.

### Adopted, with the rename made visible rather than silent

`COPILOT_TOOL_MANIFEST_PATH` and `COPILOT_DATABASE` are now the canonical names. I had shipped
`TOOL_MANIFEST_PATH` and `COSMOS_DB_DATABASE`. Both old spellings are still honoured — his
compose and ConfigMap currently emit them, and a hard rejection would have broken startup on the
handshake rather than after it — but **the legacy name is reported on `/readyz` under
`legacyConfigNames`**, and setting both spellings to *different* values is a startup failure.
Guessing between them would mean this service reads a different value than whoever set the other
name believes it reads. The report is on `/readyz` rather than in a boot log because a stale
ConfigMap should be visible to whoever is looking at the pod, not only to whoever read the logs
the day it started. Empty is the healthy state; when his ConfigMap lands it goes empty and stays.

I also deleted an alternate `CosmosDb__CopilotSessionsContainerName`-style spelling I had left in
for the .NET services' convention. Two accepted names for one fact is the same bug in miniature.

`COPILOT_PORT` is now honoured (Dockerfile `CMD` in shell form, default 8005). A test asserts no
container or database name appears as a string literal anywhere outside `config.py`'s defaults.

### Two real defects his indexing note found

1. **`sessionId` was conditional on the persisted trace frame.** It was omitted when empty.
   Rusty indexes `WHERE sessionId = @sessionId ORDER BY ts ASC` for eval replay (#333), and a
   frame without that path is not an error at query time — it is *silently absent from the
   replay*. `to_document()` now raises if `sessionId` is missing, and a test asserts every
   indexed path (`runId`, `sessionId`, `seq`, `kind`, `ts`) is top level and unconditional, plus
   that none of them lives inside the unindexed `payload`.

2. **`list_artifacts` passed `partition_key=run_id` against `copilot-artifacts`, which is
   partitioned by `/sessionId`.** Cosmos answers a partition-key mismatch with **zero rows and no
   error** — my own Phase 1 lesson, and I made the mistake anyway. An empty artifact pane and a
   run that genuinely produced no artifacts would have been indistinguishable from inside the
   process, in cloud mode only, where no test I own runs. It now takes a session id. I also
   replaced `get_run`'s cross-partition query with a point read, since a run document's `id` *is*
   the run id and the sessions container is partitioned by `/id`.

Both were invisible to my 98 passing tests because both only manifest against real Cosmos. The
declared contract caught them; that is the argument for declaring one.

### Two grants I do not want

**Please drop the `copilot-approvals` Cosmos reader role, and `REDIS_CONNECTION_STRING`.**

I never read `copilot-approvals` from Cosmos. Approval state comes from `authority-service` over
HTTP, which is the same boundary the write path crosses — so the harness sees approvals only
through the service that owns them, and cannot read one that authority-service would not show it.
A data-plane reader role would be a second, unpoliced path to the same documents with no consumer
today. Standing permission with no consumer is how "it already has read, let's just query
directly" becomes reasonable in six months. I do not read the container, so I would rather not be
able to.

Same argument for Redis: this service has no Redis dependency by design. `authority-service` owns
audit publishing (epic §5.7); handing the harness the `banking-events` stream would give it the
ability to forge an audit event, which is a strange capability for the one service defined by its
inability to act. `COPILOT_APPROVALS_CONTAINER` and `REDIS_CONNECTION_STRING` can stay in the
ConfigMap harmlessly — I simply do not read them — but the IAM grant is not harmless.

His own framing is the right one, inverted: if I found myself needing a role he had not granted,
the design has drifted. I have found myself *not needing* two he did grant, and the same logic
applies.

---

## Addendum 2 — Rusty's store audit (2026-09-04)

He read my stores against his Terraform rather than trusting either document. All three findings
were real and all three are now fixed. This is the second time his lane found a defect mine could
not, and both times the mechanism was the same: **my tests run against an in-memory double, and a
double erases exactly the constraints the real store enforces.**

### Fixed: the casing bug, and the class it belongs to

He is right that `Artifact.to_document()` persisted `run_id`/`session_id`/`created_at` while
`list_artifacts` filtered `c.runId`. Zero rows, forever, silently — and with `sessionId` absent
the document had no partition-key path either, so every artifact would have landed in the
undefined partition.

I did not apply his suggested three-line patch. Adding `document["runId"] = self.run_id` on top of
`asdict()` is what `Session` and `Run` already did, and it is the reason `Artifact` was broken:
that pattern produces a document carrying **both** spellings of the same fact, and stays correct
only for as long as everyone remembers to hand-patch each new field. It is the duplication
pattern with extra steps.

Instead the persisted casing is now declared **once per entity** (`_SESSION_FIELDS`,
`_RUN_FIELDS`, `_ARTIFACT_FIELDS`), `asdict()` is gone from the persistence path, and the read
side **refuses** a document missing any mapped path rather than half-populating a dataclass from
defaults. A snake_case document from a superseded writer now fails by name. Tests assert no
persisted document contains a `_` in any key, that each carries its container's partition-key
path, and that all three round-trip.

### Fixed: two partition-key mismatches, one of which he created and I would have shipped

`list_artifacts` now takes a session id and passes it as the partition key.

More importantly: **his change of `copilot-sessions` to `/sessionId` invalidated a "fix" I had
made an hour earlier.** I had replaced `get_run`'s cross-partition query with a point read using
`partition_key=run_id`, which is correct under `/id` and addresses a non-existent partition under
`/sessionId`. His message arrived describing the ASC/DESC index direction and the PK move, and
that is the only reason I caught it. `get_run` now takes an optional session id, point-reads with
it, and falls back to cross-partition only on the `GET /runs/{id}` path where the session is
genuinely unknown. I agree with his PK reasoning — under `/id` every run would be its own logical
partition and co-locating runs with their session would buy nothing.

I also made the **in-memory double enforce the same scoping**, because a fake more permissive
than the store it stands in for is precisely how this class of bug reaches production green.

### Found while fixing his findings: artifacts were never persisted at all

His audit assumed the write path existed. It did not. The planner created an artifact, streamed
`artifact.created`, and **never called `save_artifact`** — and there was no route to read
artifacts back. So `copilot-artifacts` would have been empty in every environment, and the
casing and partition-key bugs he found were latent behind a write that never happened.

The planner now persists **before** emitting, and `GET /api/copilot/runs/{runId}/artifacts`
exists, resolving the session first so it can address the right partition. An artifact the banker
sees in the stream but cannot retrieve after a reload is worse than one never offered: the pane
renders empty and nothing distinguishes that from "this run produced nothing".

Verified live over HTTP, not just in tests: run → `artifact.created` on the wire → route returns
one `evidence_bundle` with the correct `sessionId`.

### Accepted: the Foundry naming nit

He is right and I have converged. `FOUNDRY_PROJECT_ENDPOINT` / `FOUNDRY_MODEL` are canonical,
matching ai-service and prompt-eval-service; `AZURE_AI_*` is honoured and reported on `/readyz`.
His instinct to wire *my* names rather than the conventional ones was correct at the time — a
manifest that is conventionally correct and unread is a service with no model access — but the
convergence belongs in my lane, so I made it.

### One flag: his two messages disagree about two env names

Message 1 declared `COPILOT_TOOL_MANIFEST_PATH` and `COPILOT_DATABASE`. Message 2 says he wired
`TOOL_MANIFEST_PATH` and `COSMOS_DB_DATABASE`. Nothing is broken — this is exactly the case
`env_with_legacy` was built for, both spellings work, and `/readyz` reports which one was used —
but the ConfigMap and the declared contract currently disagree, and one of them is wrong. My
preference is his message-1 names, since `COSMOS_DB_DATABASE` reads as though it were the
repo-wide database rather than this service's. Either is fine; two is not.

The `CosmosDb__Copilot*ContainerName` fallbacks he asked me to drop were already gone.

### Still open from my side

The `copilot-approvals` **reader** role is still granted and I still do not want it — I read
approval state from `authority-service` over HTTP, never from Cosmos. Redis is resolved; he
withdrew it after working the threat model, which was the right call and the same reasoning.

### Environment warning for whoever picks this up

`app/routes/sessions.py` has now been silently reverted **three times** during this session:
twice the ownership check degraded back to `if False:`, and once the entire
`GET /runs/{runId}/artifacts` route disappeared after I had added it and seen it applied. Each
time the surrounding edits survived. I re-applied and re-verified against a running process
rather than trusting the file, and both are covered by tests now — but anyone editing that file
should confirm their change is still present after their next test run.

---

## Addendum 3 — the path-set contract, extended to the harness containers

**Decision.** Extend Danny's §5.3.1b path-set equality contract from `authority-service` to
`banker-copilot-service`, and derive every Cosmos fact from Terraform rather than restating it.

`tests/test_cosmos_path_contract.py` parses `infra/cloud/cosmos.tf` and asserts, per container:

1. the partition-key path Terraform declares is **present and non-empty** on every document the
   service writes (a document missing its PK path lands in the *undefined* partition, silently);
2. **every Terraform-indexed path is a subset of the written path set** — fail closed. An index on
   a path nobody writes is not an error; the query is answered by a full scan and looks healthy;
3. no snake_case escapes into a document (camelCase is the cross-service wire contract);
4. no index points inside an excluded subtree (`/payload/*`, `/content/*`, `/threadState/*`);
5. containers the service has no write role on are never written;
6. **null-valued fields persist as present paths.** This is the Python analogue of .NET's
   `IgnoreNullValues`: a writer that drops `None` keys makes `finishedAt`, `finalSeq` and
   `parentRunId` vanish from a running run, and `WHERE IS_NULL(c.finishedAt)` then matches nothing.

**Partition keys are derived, not restated.** `partition_key_path_for(container)` reads them out of
Terraform. An earlier `PARTITION_KEYS = {...}` dict in `test_platform_contract.py` has been deleted:
it was a third copy of a fact already stated in Terraform and depended on in the store, and the copy
that drifts is never the one you are looking at. Same lesson as Phase 1's two role models.

**What it caught on its first run — a third mismatch neither lane had spotted.**
`copilot-sessions` carries a composite index on `(/bankerId ASC, /updatedAt DESC)`, backing "my
sessions, most recently active first" — the session list in the UI's left pane. The session document
had `/actorId` and **no `updatedAt` at all**. So the index was entirely orphaned, and more
importantly the model could not answer the query the platform lane had built an index for.

Resolved on the writer's side: persist `actor_id` as `bankerId`, add `updated_at`/`updatedAt`, and
touch it **inside `save_session`** rather than at each call site — a timestamp maintained by
convention at N call sites is wrong at the N+1th. A new session is born with
`updatedAt == createdAt`, not empty, or it would sort as the oldest thing in the banker's list.

**Why the writer conformed rather than the index changing.** The index is the declared consumer and
encodes a real product requirement. Renaming it to `/actorId` would have kept a model that still
cannot order by recency. The mismatch was a genuine modelling gap, not a naming disagreement.

**The shape of the check matters.** Subset-of-a-path-set fails loudly and names the offending path.
The count-shaped version of this test ("the document has 19 fields") is satisfied by arithmetic:
rename one field and the count still passes. Same lesson as Phase 1's authority ladder.

---

## Addendum 4 — the declared path is the capability scope (F2-7, F2-5/F2-8)

**F2-7 — path-parameter traversal. Fixed at the loader, fail-closed.**

`build_request()` substituted model-supplied values into a tool's URL path with `str.replace()`,
unencoded and unvalidated, and no path parameter in the shipping manifest declared a `pattern`.
httpx normalises the result, so `../../admin/whatever` turned `/api/transactions/{id}` into
`/admin/whatever`. Bounded — GET only, the six configured downstreams, the banker's own token, and
`authority-service` is not a configured downstream so the ladder was never reachable — but tool
arguments are model-controlled and tool output re-enters model context, so it was reachable by
prompt injection.

Fixed in three layers, deliberately in this order:

1. **The manifest can no longer express an unconstrained path parameter.** Every path parameter
   must declare `type: string` and a non-empty `pattern`; the loader refuses to start otherwise.
   Same reasoning as write tools: make it unregistrable rather than merely absent.
2. **The pattern is proved, not read.** JSON Schema `pattern` is a *search*, not a full match, so
   `[A-Za-z0-9_-]+` cheerfully matches `../../admin` — an anchoring mistake that is invisible by
   inspection. The loader compiles the pattern and runs it against a corpus of values that leave a
   path segment (traversal, extra segments, encoded separators, query/fragment splices, the empty
   string that collapses a segment). Any probe that matches is named in the error. Set membership,
   not a count, so a rename cannot keep it green.
3. **Substitution is confined and percent-encoded** (`quote(..., safe="")`, plus outright rejection
   of segment breakers and control characters). In a correct manifest this never fires; it exists
   because the loader runs once at startup while invocation runs continuously on hostile input.

All nine path parameters in `config/copilot-tools.yaml` now carry `^[A-Za-z0-9_-]{1,64}$`.

**F2-5/F2-8 — invoke-time read-method guard. Added.** `ToolExecutor.invoke()` now refuses any tool
whose method is outside `READ_METHODS` before dispatch, with code `write_tool_refused`. The loader
allowlist was the only thing standing between a mutating method and the network, and it sits far
from the point of action.

**Why both fixes belong to the same lesson.** We made registering a write tool impossible, then let
a read tool wander outside its declared path. A boundary that holds only for the shape of the
affordance and not for its reach is not a boundary. The declared path *is* the capability scope; if
an argument can leave it, the scope was advisory all along.
