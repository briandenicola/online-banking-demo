---
date: 2026-09-15
author: Squad (Coordinator)
status: proposed
component: banker-copilot-service
issue: 371
---

# CodeAct and Foundry Hosted Agents are not drop-in replacements for the banker harness

## Decision

**CodeAct: no-go for direct adoption; needs-more-investigation for an explicit adapter.**
The Hyperlight sandbox is an execution-isolation boundary, not evidence that a model-authored
program is using this service's `ToolRegistry` and `ToolExecutor`. Adoption is acceptable only
if every model-reachable operation is deliberately adapted back through the existing service
contracts and per-invocation trace lifecycle.

**Foundry Hosted Agents: needs-more-investigation as a deployment target.** Hosted execution may
be usable for isolation, scale-to-zero, and operational telemetry, but the platform's session,
filesystem, and identity features cannot become a second application state or authorization
model. It is a no-go if hosted session identity or hosted role state is treated as authoritative
for banker access, Cosmos partitioning, or approval authority.

These are separate verdicts: CodeAct changes the tool-call execution and trace boundary; Hosted
Agents changes the runtime/deployment boundary.

## Evidence and existing invariants

The current service has a deliberately narrow contract:

- `config/copilot-tools.yaml` is the complete registered tool surface. `manifest.py` accepts only
  `GET` targets, read capability scopes, and an allowlisted schema; write-shaped keys are refused
  by name and unknown keys fail startup.
- `registry.py` reserves `propose_action` outside the manifest and calls
  `assert_zero_write_tools()` at registry construction. `executor.py` then repeats the read-method
  check on every invocation, validates arguments, confines path parameters, forwards the banker's
  bearer token, and applies redaction and evidence projection before results enter model context
  or persistence.
- `CopilotEventEnvelope` is the one schema for SSE and offline replay (#333). Tool calls are
  represented by `tool.started`, `tool.completed`, or `tool.failed`; `seq` is gapless and
  monotonic per run, and persisted frames carry top-level `runId`, `sessionId`, `seq`, `kind`,
  and `ts`.
- A session is the durable banker conversation and a run is one independently replayable planner
  execution. They must remain distinct.
- Cosmos partition values are service-owned contracts: `copilot-sessions` and
  `copilot-artifacts` use `/sessionId`, `copilot-traces` uses `/runId`, and
  `copilot-approvals` uses `/requesterId` and is never touched by this service.
- `user-service/config/role-hierarchy.yaml` is the single role policy. It computes
  `effectiveRoles` at token issuance: `supervisor` implies `banker`, while `admin` implies neither
  banking role nor banking seniority. Downstream services consume the claim rather than
  re-expanding the hierarchy. This is specifically intended to prevent the Phase 1 privilege
  escalation caused by duplicated role models.

Microsoft's Build 2026 announcement describes CodeAct as a model-authored Python program calling
`call_tool(...)` repeatedly inside a fresh Hyperlight micro-VM, and Foundry Hosted Agents as
scale-to-zero hosted agents with per-session VM isolation, persistent filesystem/session state,
and built-in OpenTelemetry/Application Insights wiring. Those descriptions establish useful
platform behavior, but do not establish an adapter to this repository's registry, executor,
Cosmos contracts, or role issuer.

Source: [Microsoft Agent Framework at Build 2026](https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-at-build-2026-announce/).

## CodeAct findings

### Does `call_tool()` still route through the manifest and `ToolExecutor`?

**Not by construction.** It does so only if the integration explicitly registers a wrapper for
each manifest-derived tool and that wrapper delegates to `ToolExecutor.invoke(...)`. The current
service's enforcement is attached to its own registry and executor, not to the name
`call_tool` or to the fact that code runs in a sandbox.

A native CodeAct provider can expose a separate host tool list, and a model-authored program can
otherwise reach whatever capabilities the host adapter exposes (including capabilities such as
filesystem or network access if enabled). Hyperlight reduces the blast radius of the execution
environment; it does not prove that the called operation is one of this service's read tools,
that the banker JWT was forwarded, or that redaction/evidence projection ran. A single batched
program is therefore not a reason to weaken or move the existing last-mile checks.

### Does `assert_zero_write_tools()` catch every path?

**No.** It checks the manifest-backed `ToolRegistry` once at startup. It catches a poisoned or
malformed registry entry and the reserved `propose_action` collision, but it cannot see tools
registered separately with a CodeAct provider, direct network calls made by generated code, or a
new host capability that never becomes a `ReadTool`. The existing per-call method check is also
only reached when the adapter actually calls `ToolExecutor.invoke(...)`.

The startup assertion remains necessary, but under CodeAct it is not sufficient. The complete
safety condition must cover both registration surfaces: the CodeAct tool list must be derived
from the validated registry, and every callback must delegate to the same executor. Any
write-shaped or direct-I/O capability must be refused before the agent can run.

### Can per-invocation envelope tracing survive batching?

**Only with an explicit adapter; otherwise fidelity is lost.** CodeAct changes the model loop from
one model turn per tool call to one program execution containing multiple calls. That does not
remove the need for one `tool.started`/terminal frame pair per inner invocation. The adapter
would have to allocate the existing run-scoped sequence for every call, emit frames as calls
start and finish, preserve call order and failure identity, and ensure that the payload is the
already-redacted/projected result rather than the raw sandbox value.

A single opaque `execute_code` frame would collapse which tool ran, in what order, with what
arguments/result, and where a failure occurred. That would break the live stream's incremental
semantics and make eval/replay #333 unable to distinguish a missing evidence call, a failed call,
a reordered call, or a successful call hidden inside a program. It must also not be represented as
an arbitrary `execute` tool invocation: the envelope contract reserves `execute` mode for
`propose_action`.

## Foundry Hosted Agents findings

### Does hosted filesystem/session persistence fit Cosmos partition discipline?

**Not automatically; it introduces a second session-like state unless explicitly demoted to
scratch state.** The hosted platform's persisted filesystem and session identity can survive
scale-to-zero, but the service already has an authoritative session/run model and deliberately
separates them. A platform session ID is not interchangeable with the service `sessionId`, and a
hosted run/container restart is not evidence that a Cosmos run should be resumed or recreated.

Blindly mapping hosted IDs to partition keys would be unsafe: the service's partition values are
not chosen by the deployment platform, and a wrong value produces empty reads rather than a clear
error. In particular, runs belong to the `/sessionId` partition in `copilot-sessions`, artifacts
also use `/sessionId`, traces use `/runId`, and approvals are outside this service. Hosted files
must therefore be treated as non-authoritative ephemeral/scratch state unless a separate design
proves ownership, retention, isolation, deletion, concurrency, and recovery semantics.

Safe adoption would require an explicit mapping at the boundary: the service creates and persists
its own session/run IDs, stores the hosted session ID only as non-authoritative correlation
metadata if needed, and resumes only from Cosmos documents validated against the service IDs and
partition values. It must not make filesystem restoration a substitute for trace or session
persistence.

### Does hosted identity duplicate or conflict with the user-service role model?

**It can, unless the identities are kept on separate planes.** Hosted Agent identity is useful for
running the workload and accessing platform resources; it does not establish that the human
banker is a `banker`, that a caller is a `supervisor`, or that an `admin` has banking seniority.
The platform's session identity must not mint or replace the banker's JWT, populate
`effectiveRoles`, satisfy an approval signature slot, or re-expand the hierarchy.

The Phase 1 failure mode is exactly a second role interpretation at a seam. The only accepted
banking authorization source remains `user-service`'s `effectiveRoles` claim from the shared
`role-hierarchy.yaml`; `authority-service` remains the owner of action policy and approval
execution. Hosted workload credentials may authorize service-to-service/platform operations, but
they must not be treated as the requester's banking identity. The original banker authorization
context must continue to govern downstream reads.

## Verdict and adoption gates

### CodeAct — **NO-GO now; NEEDS-MORE-INVESTIGATION for an adapter**

Do not replace the current planner/tool path with native CodeAct registration as a spike outcome.
Before reconsideration, prove with integration tests and trace fixtures that:

1. the CodeAct tool list is generated only from the validated manifest/registry;
2. every `call_tool()` callback delegates to `ToolExecutor`, preserving argument validation,
   path confinement, banker-token propagation, redaction, projection, timeout, and upstream error
   semantics;
3. no generated program has a direct write, direct upstream network, authority, filesystem, or
   other unreviewed capability; `propose_action` remains the only write-shaped affordance and
   still goes through its existing authority boundary;
4. each inner call produces the same per-invocation envelope frames, gapless run sequence,
   server timestamps, and replayable persisted shape as the current planner; and
5. batched success, failure, timeout, repeated-tool, partial-result, and cancellation cases are
   replay-equivalent for SSE and eval #333.

**Invariant:** every model-reachable operation is manifest-derived and read-only, except the
existing mediated `propose_action`; no operation bypasses `ToolExecutor`'s validation,
identity propagation, redaction/projection, or per-call trace contract.

### Foundry Hosted Agents — **NEEDS-MORE-INVESTIGATION**

Evaluate it as infrastructure only after validating, in the target hosting configuration:

- session restore, scale-to-zero, concurrent requests, crash recovery, and deletion/retention
  semantics against service-owned Cosmos sessions/runs/artifacts/traces;
- tenant/session VM isolation and whether hosted filesystem state can leak across service sessions;
- credential flow proving workload identity is distinct from the banker JWT and cannot impersonate
  a role or signature slot;
- observability correlation from hosted OTel/Application Insights to the existing `runId`,
  `sessionId`, and envelope sequence without replacing persisted trace frames; and
- explicit failure behavior when hosted state is absent, stale, or inconsistent with Cosmos.

**Invariant:** `banker-copilot-service` owns session/run identity and Cosmos partition-key values;
`user-service` remains the sole role/effective-role issuer; `authority-service` remains the sole
agent-originated write executor; and the canonical `CopilotEventEnvelope` remains the source of
truth for live stream and replay.

Until those gates are demonstrated, Hosted Agents may be considered a possible hosting option,
not a compatible replacement for the service's state or identity model.
