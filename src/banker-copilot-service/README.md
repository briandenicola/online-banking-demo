# banker-copilot-service

The agentic harness for the Banker Copilot (epic #332, Phase 2). Python 3.11 / FastAPI,
listening on **8005**, reached through the gateway at **`/api/copilot/`**.

## What this service is

It is the thing that *cannot act*.

`authority-service` (Phase 1, .NET) owns the authority ladder and is the **sole executor of
agent-originated writes**. This service runs the planner loop, calls read-only tools, and —
when the conversation reaches a state-changing conclusion — hands a **proposal** to
`authority-service` and stops. A human signs, or nothing happens.

> Agents never approve. Every state-changing action carries a human signature. Thresholds
> govern how many humans sign and how senior — never *whether* a human signs.

## How that is enforced

Not by a runtime check that someone can delete. By the **shape of the manifest schema**.

`config/copilot-tools.yaml` is the only place a tool can come from, and the loader in
`app/tools/manifest.py` gives it no way to *spell* a write:

| Enforcement | Where |
| --- | --- |
| `method` must be in `READ_METHODS = {"GET"}` | `manifest.py` |
| `capabilityScope` must end in `.read` | `manifest.py` |
| `mode`, `actionId`, `authority`, `idempotencyKeyFrom`, `requiredEvidence`, `cosignerId` are **refused by name, with a reason** | `_REFUSED_TOOL_KEYS` |
| Any unrecognised key at any level is refused | allowlist, not denylist |
| `propose_action` is a reserved tool id no manifest entry may claim | `registry.py` |
| Registered write-tool count is asserted zero at startup | `assert_zero_write_tools()` |

The refusals are *loud*. A silently-dropped key looks exactly like one that works, which is
how a safety toggle becomes decorative. A malformed entry does not get skipped — the
**service refuses to start**. A harness that cannot prove which tools it registered must not
register any.

`assert_zero_write_tools()` is itself tamper-tested (`tests/test_zero_write_tools.py`
poisons a registry via `dataclasses.replace` and asserts the assertion fires), because
otherwise it could quietly be a no-op and every other test would still be green.

Tool-set assertions use **set equality**, not counts. A count is satisfied by arithmetic and
a miscount passes silently; set membership fails by name.

## The sole write affordance

`propose_action` → `POST {AUTHORITY_SERVICE_URL}/api/authority/approvals`.

It returns an approval id and a status. It cannot execute. It does not know how to.

**`cosignerId` does not exist.** It is not optional, not ignored, not accepted-and-dropped —
it is **rejected with an error naming the reason**. Letting a banker name their reviewer at
proposal time lets them choose someone who will say yes, which is precisely the self-dealing
that L2 co-signature exists to prevent. The queue keys on **required seniority**, never on a
person. The same applies to `requiredRung`, `requiredSigners`, `policyVersion`,
`payloadHash`, `execute` and `status`: those are the ladder's to decide, and a caller that
offers them is either confused or attacking.

## Deliberate non-duplication

Duplication is the bug. Phase 1 shipped two independent role models and a privilege
escalation lived in the seam between them for hours. So:

- **Required evidence, rungs, thresholds, dollar amounts and the action catalogue are NOT in
  this repo's manifest.** The planner asks `GET /api/authority/policy` at runtime.
- **Roles are not re-derived.** `require_banker` consumes the `effectiveRoles` claim minted
  by `user-service` and *refuses a token that lacks it* rather than re-expanding the
  hierarchy itself. Two expansions are two chances to disagree.
- `role-hierarchy.yaml` is **mounted from `src/user-service/config/`**, the same object
  `authority-service` reads. Three images built at three commits cannot disagree about who
  outranks whom if they read one file.
- `tests/test_zero_write_tools.py` cross-checks the evidence tool ids in
  `config/authority-policy.yaml` against the registered tools — the class of defect that
  exists only *between* two internally coherent files.

## Sessions and runs are different things

A **session** is the conversation: durable, resumable, owned by a banker, holds message
history and artifacts. A **run** is one turn of the planner: has a seq-ordered event stream,
terminates, and is the unit of trace replay. One session has many runs. They are not
unified, and unifying them would make it impossible to replay a single turn.

## Traces: one schema, two consumers

`CopilotEventEnvelope` (epic §8.0, `app/events/envelope.py`) is emitted **once** and serves
both the live SSE stream and offline eval replay (#333). The eval contract lands *with* the
harness, not bolted on afterwards, because a trace format retrofitted to a running system
records what the system happened to emit rather than what evaluation needs.

- Monotonic `seq` per run, allocated before persistence, so replay ordering is authoritative
  and the client can dedupe and resume.
- `kind` and `terminalReason` are **closed enums**. An unknown kind raises.
- Persisted to the `copilot-traces` container (PK `/runId`); on sink failure the run
  continues but is marked `trace_degraded` — a degraded trace is reported, never faked.
- Redaction is applied **at emit**, because persisted traces outlive the session. The
  JSONPath subset is deliberately tiny and **rejects anything it cannot evaluate** (notably
  `$..field`), since a redaction rule that silently matches nothing is indistinguishable
  from one that worked.

## Streaming

`GET /api/copilot/sessions/{id}/stream` is SSE, consumed by the UI with **`fetch`**, not
native `EventSource` — `EventSource` cannot carry a bearer token. The gateway sets
`proxy_buffering off`. Clients resume with `?afterSeq=`.

## Configuration

No IPs, CIDRs, thresholds or dollar amounts in code. All of it is config.

| Variable | Meaning |
| --- | --- |
| `AUTHORITY_SERVICE_URL` | The one write path. |
| `DOWNSTREAM__<SERVICE>` | Read-tool upstreams. **UPPER_SNAKE after the prefix is mandatory** — Kubernetes `envFrom` silently drops ConfigMap keys containing hyphens, so `DOWNSTREAM__account-service` would vanish without an error. The loader maps `_` back to `-`. |
| `COPILOT_TOOL_MANIFEST_PATH` | Manifest location. Missing/invalid → refuse to start. (Legacy `TOOL_MANIFEST_PATH` still honoured, but reported on `/readyz`.) |
| `COPILOT_DATABASE` | Cosmos database name. (Legacy `COSMOS_DB_DATABASE` honoured and reported.) |
| `COPILOT_PORT` | Listen port; defaults to 8005, the port the gateway route points at. |
| `ROLE_HIERARCHY_PATH` | Shared role model. Missing, or missing `banker` → refuse to start. |
| `JWT_KEY` / `JWT_ISSUER` / `JWT_AUDIENCE` | Simple-mode token validation. |
| `AZURE_CLIENT_ID` | **Presence selects Entra mode; absence selects simple mode.** The chosen mode is logged at startup — in Phase 1 an ambient `AZURE_CLIENT_ID` silently flipped a service onto Entra and the resulting 500 named neither. |
| `COSMOS_DB_ENDPOINT` | Unset → in-memory stores, logged as such. |
| `COPILOT_SESSIONS_CONTAINER`, `COPILOT_ARTIFACTS_CONTAINER`, `COPILOT_TRACES_CONTAINER` | Container names, config-driven so a rename happens once. |
| `COPILOT_SSE_HEARTBEAT_SECONDS`, `COPILOT_SSE_REPLAY_WINDOW`, `COPILOT_SESSION_TTL_SECONDS`, `COPILOT_PLANNER_MAX_ITERATIONS`, `COPILOT_UPSTREAM_TIMEOUT_MS` | Runtime bounds. |
| `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT` | Planner model. Absent → deterministic planner, logged. |

Retired keys are **rejected at load**, not ignored (`ConfigurationError`). A silently-ignored
safety toggle is worse than no toggle. Renamed keys are a softer case: the old spelling is
honoured, but it is **named on `/readyz` under `legacyConfigNames`** rather than accepted in
silence, and setting both spellings to *different* values is a startup failure — guessing would
mean this service reads a different value than whoever set the other name believes.

### Storage shape, and why the partition keys are not ours to choose

| Container | Partition key | Written by us? |
| --- | --- | --- |
| `copilot-sessions` | `/sessionId` | yes (sessions and runs, discriminated by `docType`) |
| `copilot-artifacts` | `/sessionId` | yes |
| `copilot-traces` | `/runId` | yes |
| `copilot-approvals` | `/requesterId` | **no — we never touch it, in any mode** |

`runId`, `sessionId`, `seq`, `kind` and `ts` are **top level and unconditional** on every
persisted trace frame, and `to_document()` raises if `sessionId` is missing. Cosmos will not use
a composite index unless every filtered and ordered path appears in it, so nesting one of these
under a wrapper does not raise — the query quietly full-scans, or returns nothing. Nothing the
indexes rely on lives inside `payload`, which is excluded from indexing.

**Persisted documents are camelCase**, stated once per entity in `_SESSION_FIELDS`,
`_RUN_FIELDS` and `_ARTIFACT_FIELDS` rather than at each call site. The earlier code built
documents with `asdict()` (snake_case) and hand-patched a few camelCase keys on top, which
produced documents carrying both spellings of one fact — and, where the patching was forgotten,
an artifact document with no `runId` and no `sessionId` at all. Reads refuse a document missing
any mapped path rather than half-populating an object.

The same hazard governs partition-key *values*: a mismatch is answered with **zero rows and no
error**. An empty artifact pane and a run that genuinely produced no artifacts are
indistinguishable from inside this process. `copilot-sessions` is partitioned by `/sessionId`, so
a **run**'s partition is its *session*, not its own id — `get_run` takes an optional session id
and only falls back to a cross-partition query when the caller genuinely does not know it.

`FOUNDRY_PROJECT_ENDPOINT` / `FOUNDRY_MODEL` are the canonical model-access names, matching
ai-service. `AZURE_AI_PROJECT_ENDPOINT` / `AZURE_AI_MODEL_DEPLOYMENT` are honoured and reported.

## Endpoints

```
GET  /healthz  /readyz                       # readyz reports writeTools:0, methods, modes
GET  /api/copilot/tools
POST /api/copilot/sessions
GET  /api/copilot/sessions/{id}
POST /api/copilot/sessions/{id}/messages
POST /api/copilot/sessions/{id}/runs
POST /api/copilot/sessions/{id}/propose
GET  /api/copilot/sessions/{id}/stream       # SSE
GET  /api/copilot/runs/{id}
GET  /api/copilot/runs/{id}/trace            # replay
```

## Running

```bash
docker compose up banker-copilot-service        # port 8005, gateway /api/copilot/
cd src/banker-copilot-service && python -m pytest tests/ -q
```

## Known gaps in the upstreams (found by reading the real controllers)

The epic's manifest was written against intended shapes. The deployed services differ, and
these gaps block the §1.3 narrative end-to-end. **None are fixed here** — they are other
services' lanes.

1. **`GET /api/transactions/account/{accountId}` filters by the caller's own userId.** A
   banker therefore cannot see a customer's transactions through it, so the read tool as
   specified cannot do its job. This is the most consequential of the four.
2. **`GET /api/admin/login-audits` accepts only `limit`** — no `userId`, no `sinceUtc`, both
   of which the epic manifest assumes.
3. **ai-service and account-opening-service admin routes require the `admin` role**, so a
   `banker` token gets 403. An upstream authorization gap this phase exposes.
4. **`transaction.flag.review` payload keys are `transactionId`/`rationale`** per
   `config/authority-policy.yaml`, not `txId`/`justification` as in epic §3.3's example. The
   policy file wins; the manifest and planner follow it.

## Cosmos path-set contract

`tests/test_cosmos_path_contract.py` parses `infra/cloud/cosmos.tf` and checks, per container, that
the partition-key path Terraform declares is present on every document this service writes, that
every Terraform-indexed path is a subset of the written paths (fail closed), that no snake_case
escapes into a document, that no index points inside an excluded subtree, and that `None`-valued
fields still persist as present paths.

Partition keys are **derived from Terraform, never restated in Python**. Cosmos returns zero rows
rather than an error on a field-path mismatch, and answers a mis-indexed `ORDER BY` by full scan, so
these mistakes have no runtime signal at all — the test is the only place they surface.

Session documents therefore carry `bankerId` and `updatedAt` at the top level, backing the
`(bankerId ASC, updatedAt DESC)` index behind the session list. `updatedAt` is advanced inside
`save_session`, not by callers.

## Path confinement

Every path parameter in the tool manifest must declare `type: string` and an anchored `pattern`;
the loader refuses to start otherwise. It does not read the pattern — it compiles it and proves it
rejects a corpus of values that leave a path segment (`..`, `a/b`, encoded separators, query and
fragment splices, the empty string). JSON Schema `pattern` is a search rather than a full match, so
an unanchored expression matches a traversal substring and looks correct on review.

Substitution additionally percent-encodes with `safe=""` and rejects segment breakers outright, and
`ToolExecutor.invoke()` re-checks the read-method allowlist at the point of action. The declared
path is the tool's capability scope; if an argument can leave it, the scope is advisory.
