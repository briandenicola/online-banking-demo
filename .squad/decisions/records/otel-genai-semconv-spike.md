---
date: 2026-09-15
author: Danny (Lead/Architect)
status: proposed
component: banker-copilot-service/app/events/envelope.py
issue: 369
related: [333, 371]
---

# OpenTelemetry / GenAI semantic-convention alignment for `CopilotEventEnvelope`

## Decision

**Defer alignment as a first-class trace schema to the hosted-agents migration; do not
implement an exporter in this spike.** The existing envelope is the durable contract for two
materially different consumers: the live SSE UI and #333 offline trajectory/eval replay. OTel
GenAI conventions are a useful interoperability projection, but they are not a lossless
replacement for the event ledger. An additive exporter may be revisited after the hosted-agents
shape and #371 are decided, with explicit redaction and replay-fidelity tests.

This is a recommendation, not an implementation. No production files were changed.

## Sources and current repository facts

* [Microsoft Agent Framework Harness](https://learn.microsoft.com/en-us/agent-framework/concepts/harness?pivots=programming-language-python)
  (retrieved 2026-09-15): the Python harness composes chat client, pipeline, context providers,
  middleware/decorators, streaming UX, and optional compaction, modes, approvals, background
  agents, and looping. OpenTelemetry observability is enabled by default in the harness; the
  Python factory also permits disabling it. This is framework observability, not a statement
  that a harness event stream can replace this repository's replay ledger.
* [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
  (retrieved 2026-09-15): the page has moved to the dedicated
  [semantic-conventions-genai repository](https://github.com/open-telemetry/semantic-conventions-genai)
  and is no longer maintained at the old URL. The linked section pages likewise redirect. A
  current search result for the repository identifies the principal agent/LLM vocabulary,
  including `gen_ai.operation.name` (for example `invoke_agent`, `chat`, or
  `generate_content`), agent identity attributes, conversation identity, provider/model
  identity, and token usage. Exact stability/version status must be pinned when implementation
  begins; do not infer it from this redirect.
* `src/banker-copilot-service/README.md`, especially “Traces: one schema, two consumers”:
  the envelope is emitted once for SSE and persisted replay; `seq` is monotonic/gapless per
  run; modes and terminal reasons are closed; redaction happens at emit; sink failure marks
  `trace_degraded` rather than pretending the replay is complete.
* `src/banker-copilot-service/app/events/envelope.py:21-249`: `EVENT_KINDS`, `RUN_MODES`, and
  `TERMINAL_REASONS` are closed sets. `to_wire()` is the UI object; `to_document()` is a
  deliberate superset with unconditional top-level `runId`, `sessionId`, `seq`, `kind`, and
  `ts`, plus optional `parentRunId`. Tool frames validate mode and permit `execute` only for
  `propose_action`; approval terminal, mode transition, compaction, and evidence-progress
  payloads have strict shape validation.
* `src/banker-copilot-service/app/events/bus.py:1-120`: one emit path allocates sequence,
  persists, then fans out to subscribers. Persistence failure does not stall the banker but
  marks the run degraded.
* `docs/epics/banker-copilot.md:98-100, 1803-1817, 1900-1912, 2400-2408` and
  `docs/design/banker-copilot-phase2-test-plan.md:147-170`: #333 is separate from the epic but
  requires structured traces from day one. Replay tests require non-empty sequences, exact SSE
  versus persisted sequence and payload equality, document-as-wire-superset, gapless sequence,
  trustworthy/degraded declaration, and cursor resume fidelity. The epic also calls out
  `traceId`/`spanId`, model/deployment/token counts, and `parentRunId` as *additional* trace
  information—not permission to replace the envelope.

## What maps cleanly

The mapping is clean only as a **secondary OTel projection**:

| Envelope fact | Plausible OTel projection | Caveat |
|---|---|---|
| One run / planner invocation | `invoke_agent` span; `runId` and `sessionId` as correlation attributes | A span has lifecycle/status, not a gapless event sequence. Avoid putting raw IDs into high-cardinality metric labels. |
| Model round trip in planner | LLM span/operation such as `chat` or the provider's supported generation operation; model/provider/deployment and token usage attributes | The convention records model-call observability, not the exact prompt/evidence transcript needed by eval. |
| Tool invocation | Tool span/operation (where supported), with tool identity and parent context | `plan` versus the sole `execute`/`propose_action` rule is a repository safety invariant and must remain an explicit attribute or event payload. |
| Supervisor/subagent relationship | Child span linked/parented to the run; `parentRunId` remains an envelope field | Span parentage can describe timing/tree structure but cannot replace the explicit replay field or distinguish all event states. |
| Browser → services correlation | W3C trace context plus `runId`/`sessionId` correlation | OTel context propagation is useful across HTTP, but browser context is not durable replay provenance by itself. |

The names and attributes should be treated as convention-versioned projection code, not copied
verbatim into `CopilotEventEnvelope.kind`. The envelope's kinds (`mode_transition`,
`evidence_compacted`, `evidence_progress`, `approval.terminal`, etc.) are product/control-plane
facts; they are not all GenAI operations.

## Answers to the three questions

### 1. Is this a clean mapping, or does eval information get lost?

It is a clean mapping for **operational spans**, not for the canonical trace. A run can be
represented by an agent span with nested model/tool spans, and the existing epic's desired
`traceId`/`spanId`, model, deployment, and token fields fit naturally as correlation metadata.

It is not lossless for #333 if the envelope is converted to OTel events/spans and then discarded.
OTel does not inherently preserve the envelope's gapless `seq`, exact SSE payloads, closed
terminal reason (`HUMAN_DENIED` versus `TTL_EXPIRED` versus policy escalation), strict mode
transition, evidence-required/satisfied/discretionary separation, compaction IDs and estimates,
redacted artifact payloads, or the `trace_degraded` trust declaration. Span timing and status
also cannot prove that every emitted frame was durably persisted. Those are precisely the facts
covered by the replay-fidelity tests and by evaluator discrimination between model behavior and
policy/human outcomes.

Therefore: **keep the envelope as source of truth; export a derived OTel view.** An OTel exporter
must never be the only sink for replay.

### 2. Is there an exporter/redaction consistency risk?

Yes, and it is the principal implementation risk. The envelope applies redaction at emit before
both persistence and SSE. OTel SDK/exporter instrumentation is a separate path. Agent Framework
observability is enabled with `enable_sensitive_data=False` in `src/ai-service/app/services/anomaly_service.py:112-123`,
but that setting and the ai-service's custom debug logging are not a repository-wide guarantee:

* `ai-service` exports OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set
  (`src/ai-service/app/config.py:45-58`) and instruments FastAPI/HTTPX
  (`src/ai-service/app/main.py:10-40`).
* It consumes `gen_ai.operation.name`, `gen_ai.usage.input_tokens`, and
  `gen_ai.usage.output_tokens` from Agent Framework spans for token accounting
  (`src/ai-service/app/services/anomaly_service.py:47-91`).
* `ai-service/app/config.py` also contains an opt-in Foundry HTTP debug hook that logs request
  bodies and headers (with targeted redaction), demonstrating that telemetry and diagnostic
  paths can diverge.
* The .NET `prompt-eval-service` calls shared `AddBankingOpenTelemetry("prompt-eval-service")`
  (`src/prompt-eval-service/Program.cs:17-18`); shared instrumentation currently configures
  ASP.NET Core/HTTP client spans and an optional OTLP exporter
  (`src/shared/Observability/ObservabilityExtensions.cs:30-55`), not a replay-aware GenAI
  projection.

If banker-copilot adds OTel, exporting raw `payload`, prompts, evidence, tool arguments, model
outputs, approval data, or artifacts can bypass envelope redaction, expose banking data, and
create an exporter-dependent eval transcript. Conversely, over-redaction can make an OTel span
useless for cross-service diagnosis. The safe design is a single allowlisted, already-redacted
projection: identifiers, operation names, status, timing, bounded counts, and non-sensitive
metadata only; no second ad-hoc redactor and no exporter callback that rereads the unredacted
model/tool objects. Exporter failure must be non-blocking and observable, just as trace sink
failure is, without altering `seq` or SSE behavior.

### 3. Is the value hosted-agents-only, or independently useful cross-service?

It is **not hosted-agents-only**, but the highest-risk/most immediate alignment is coupled to
hosted agents. Independent value exists now for cross-service correlation: browser/gateway →
banker copilot → ai-service/prompt-eval-service → authority/downstream calls; common operation
names and W3C trace context can shorten latency/error diagnosis, correlate model token usage,
and compare service boundaries in Azure Monitor/OTLP. Existing ai-service already emits and
consumes GenAI-style attributes, while prompt-eval-service and shared observability provide a
place for common distributed tracing.

However, #371 (the separate hosted-agents spike) is a dependency for deciding which framework
lifecycle, span ownership, provider instrumentation, session/run identity, and sensitive-data
settings banker-copilot will actually have. This report does not duplicate #371. Implementing a
banker-specific exporter before that decision risks tracing transient internals twice or
codifying a span model that hosted agents will replace. Cross-service value is real, but it can
be captured later through a stable adapter once #371 settles.

## Recommendation and bounded follow-up

**Recommendation: defer to the hosted-agents migration (#371), while preserving the envelope as
canonical.** This is preferable to “adopt now” because there is no urgent evidence that OTel
must become the replay format, and an early exporter creates a concrete redaction and semantic
version-drift risk without satisfying #333's requirements.

When #371 is resolved, the follow-up should be narrowly scoped:

1. Pin the exact GenAI semantic-convention version and supported Agent Framework instrumentation;
   document operation/span ownership for run, model, tool, supervisor, authority, and downstream
   calls.
2. Add an **additive** exporter/processor at the `RunStream` emit boundary (or an equivalent
   stable adapter), projecting only an allowlist of redacted metadata. Never replace the durable
   `TraceSink`, alter `to_wire()`/`to_document()`, or add open-ended event kinds.
3. Define low-cardinality attributes and correlation policy (`runId`/`sessionId` as span
   attributes where appropriate, W3C propagation, no banking values or raw prompts in span
   attributes/events). Preserve `parentRunId` and explicit plan/execute semantics.
4. Test that redaction is identical or stricter for SSE, Cosmos replay, and OTLP; exporter
   outages do not fail a run; and replay byte/field fidelity remains unchanged. Add tests for
   token/model metadata and for `trace_degraded` versus exporter degradation separately.
5. Validate one end-to-end trace across banker-copilot, ai-service, prompt-eval-service,
   authority, and a downstream read/write boundary in a collector-backed environment.

No code change is justified in this SPIKE. The next architectural decision is the hosted-agents
shape (#371), after which an additive interoperability layer can be evaluated against the above
invariants.
