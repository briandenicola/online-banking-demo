---
date: 2026-09-15
author: Investigation Specialist
status: proposed
component: banker-copilot-service/app/planner/fanout.py
issue: 367
---

# BackgroundAgentsProvider is not a drop-in replacement for the L2 second opinion

## Decision

**keep as-is** Do not replace the narrow L2 supervisor path with Microsoft Agent
Framework's `BackgroundAgentsProvider`. The provider is a general-purpose model-facing
parallel delegation facility; this code is a deliberately constrained, blind, read-only
second opinion. The current shape better preserves the four required invariants.

## What BackgroundAgentsProvider provides (documented facts)

Microsoft Agent Framework's Python provider registers model-facing lifecycle tools for
starting named child-agent tasks, waiting for the first completion, retrieving results,
listing tasks, continuing a task, and clearing completed tasks. Children run concurrently
in dedicated child sessions; results are returned to the parent as text. `wait_timeout_seconds`
is a positive bounded wait (default 300 seconds); expiry returns normally while tasks remain
running. The provider is experimental, has no model-facing cancellation tool, and requires
host-side release handling for parent-session teardown. Child agents must be trusted because
parent context can be delegated to them and their results re-enter parent context.

These facts come from the [Background Agents documentation](https://learn.microsoft.com/en-us/agent-framework/agents/background-agents?tabs=python),
which is linked by the [Harness concept documentation](https://learn.microsoft.com/en-us/agent-framework/concepts/harness?pivots=programming-language-python).
The Build announcement describes `BackgroundAgentsProvider` only as parallel delegation to
child agents, not as a banking-specific safety boundary:
[Agent Framework at Build 2026](https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-at-build-2026-announce/#agent-harness:-production-patterns-built-in).

## Comparison

### Current implementation

`run_second_opinion` constructs `SupervisorInput` from the original banker intent and raw
entity IDs; the primary result has no parameter or object reference through which to travel.
It derives the supervisor's tool set from the action's required evidence and the read-only
registry, re-runs those reads through `ToolEvidenceReader`, and gives the decider only the
supervisor input plus independently gathered evidence. The manifest has no write-tool shape:
only `GET` tools are accepted and unknown/write-shaped keys are rejected.

The supervisor is one mandatory, purpose-built L2 child, not an open delegation surface. Its
wall-clock budget is enforced with `asyncio.wait_for`; timeout emits the named
`subagent_timeout` failure and returns no opinion. Agreement is computed afterward as a
tri-state comparison, so a missing side is `not_comparable`, not dissent. The code comments
and limits module describe the orchestration as `asyncio.gather`-based, but the inspected
`fanout.py` currently contains no `asyncio.gather` call: this path spawns one supervisor and
awaits it under `wait_for`; its evidence-reader loop is sequential and budget-capped.

### Provider pattern

`BackgroundAgentsProvider` is genuinely broader and safer than ad-hoc unrestricted task
creation in a few respects: it supplies named-child identity, dedicated sessions, explicit
start/wait/result/cleanup lifecycle, and a provider-level wait bound. It can run multiple
independent tasks concurrently and preserve child context for continuation. Those are useful
general orchestration primitives.

They are not sufficient for this flow's contract. Provider task results are text reintroduced
into the parent context, while this supervisor returns a structural `SecondOpinion` and is
never allowed to inherit the primary's plan, narrative, recommendation, confidence, or cache.
The provider's task list and model-facing instructions would also create a wider delegation
surface than the one fixed L2 child. Its timeout leaves work running rather than producing the
current explicit terminal failure; cancellation and cleanup are host/session concerns. Most
importantly, the provider does not establish read-only tools, zero writes, config ownership,
or the structural blind-input guarantee—those would still have to be built around it.

The comparison above is partly an inference from the documented lifecycle and the inspected
code: using the provider *could* be made equivalent only by disabling/generalizing away much
of its model-facing behavior and adding wrappers for this repository's contracts. That would
increase, not reduce, the safety-critical surface.

## Invariants and ruling

| Invariant | Current path | Provider implication |
|---|---|---|
| Config-driven bounds from `config/harness-limits.yaml` | `FanoutLimits` supplies depth, per-child tool budget, and wall-clock seconds; no fan-out literals in `fanout.py`. | Provider's wait default/parallel task lifecycle are separate controls; adoption would need explicit mapping for every configured bound, including depth and tool budget. |
| Read-only child tools and zero-write manifest | Registry is filtered to read tools; `manifest.py` structurally permits `GET` only and refuses write-shaped keys. | Provider does not constrain child tools. A wrapper could pass the read registry, but the invariant would remain local code, not a provider guarantee. |
| Explicit named failure/timeout semantics | `subagent_timeout` is emitted; failed/missing opinions are not comparable; trace and approval shapes are repository-defined. | Provider exposes statuses and text results, but timeout leaves tasks running and has no model-facing cancellation. Translating statuses without changing semantics is non-trivial. |
| Narrow independent second-opinion purpose | Exactly one blind L2 child, fixed adversarial posture, own required reads, structural output, no primary channel. | Provider is intentionally general: multiple named children, continuation, parent-context result injection. It would genericize the very flow that must remain narrow. |

Therefore the provider offers useful primitives but no evidence of a clearly safe adaptation
that improves this implementation without weakening or duplicating its controls. Keep the
current implementation and its structural tests as the decision of record.

## Follow-up

None for this spike. If a future requirement calls for more than the single L2 second opinion,
open a separate design decision rather than broadening this path. Any proposal must first map
all four invariants above, preserve blind construction, retain structural `SecondOpinion`
output (not free-form child text), and define cancellation/timeout behavior before code is
changed.
