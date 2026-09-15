"""Issue #374 — the three trace-schema gaps closed for offline trajectory eval (#333).

§8.0 required these from day one; this pins the three additions end-to-end rather than at the
unit level alone, because a validator that accepts a shape nothing ever emits proves nothing:

1. ``traceId``/``spanId`` on every ``tool.started``/``tool.completed``/``tool.failed`` frame,
   correlating an agent's tool-call decision with the OTEL span across services.
2. A ``model.call`` frame carrying ``modelDeployment``/``promptTokens``/``completionTokens``/
   ``latencyMs`` for the planner's evidence-answer call and the supervisor's second opinion.
3. ``GET /api/copilot/traces`` — covered separately in ``test_bulk_trace_query.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.fanout import FanOutEngine, SecondOpinion
from app.planner.intent_model import EvidenceAnswer, IntentDecision
from app.planner.limits import FanoutLimits
from app.planner.model_call import ModelCallTelemetry
from app.planner.loop import Planner, PlannerRequest

from tests.conftest import judging_assessor, shipped_assessment_limits
from tests.test_fanout_engine import _FakeRegistry as _FanoutRegistry
from tests.test_fanout_engine import _RecordingExecutor, _Session as _FanoutSession
from tests.test_run_terminal_status import (
    _FAKE_TOKEN,
    _Authority,
    _Executor,
    _FakeRegistry,
    _Session,
    _Store,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# --------------------------------------------------------------------------------------------
# Gap 1 — traceId/spanId on tool frames, end-to-end through the real planner loop.
# --------------------------------------------------------------------------------------------


async def _drive(
    *,
    authority: _Authority,
    executor: _Executor,
    evidence_tools: tuple[str, ...] = (),
    action_id: str | None = "account.balance.adjust",
    correlation_id: str | None = None,
    intent_selector=None,
    answerer=None,
    objective: str = "Propose account.balance.adjust for human signature",
) -> list[dict[str, Any]]:
    registry = _FakeRegistry(evidence_tools)
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    planner = Planner(
        registry=registry,
        executor=executor,
        authority=authority,
        max_iterations=12,
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
        intent_selector=intent_selector,
        answerer=answerer,
        store=_Store(),
    )
    request = PlannerRequest(
        session=_Session(),
        run_id="run_under_test",
        objective=objective,
        action_id=action_id,
        payload={"amount": "245.00", "accountId": "acc_1"},
        facts={"transactionId": "tx_1"},
        bearer_token=_FAKE_TOKEN,
        correlation_id=correlation_id,
    )
    stream = runs.create("run_under_test", "sess_1")
    await planner.run(request, stream)
    return runs.sink._frames["run_under_test"]  # type: ignore[attr-defined]


def _tool_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in frames if f["kind"] in ("tool.started", "tool.completed", "tool.failed")]


async def test_tool_frames_carry_the_callers_correlation_id_as_trace_id():
    """A caller-supplied ``X-Correlation-ID`` becomes the run's traceId on every tool frame —
    the value already forwarded to authority-service — so an eval consumer can correlate a
    tool-call decision with the OTEL span across services (§8.0)."""
    frames = await _drive(
        authority=_Authority("admit", evidence=("get_flagged_transaction",)),
        executor=_Executor(),
        evidence_tools=("get_flagged_transaction",),
        correlation_id="corr-caller-supplied",
    )

    tool_frames = _tool_frames(frames)
    assert tool_frames, "no tool frames were emitted — the fixture drifted"
    assert {f["payload"]["traceId"] for f in tool_frames} == {"corr-caller-supplied"}
    assert all(f["payload"]["spanId"] for f in tool_frames)


async def test_tool_frames_get_a_generated_trace_id_when_the_caller_sent_none():
    """No ``X-Correlation-ID`` header must not mean no traceId — every tool frame still needs
    one, stable for the run, or an eval consumer cannot correlate at all."""
    frames = await _drive(
        authority=_Authority("admit", evidence=("get_flagged_transaction",)),
        executor=_Executor(),
        evidence_tools=("get_flagged_transaction",),
        correlation_id=None,
    )

    tool_frames = _tool_frames(frames)
    assert tool_frames
    trace_ids = {f["payload"]["traceId"] for f in tool_frames}
    assert len(trace_ids) == 1, "the generated traceId must be stable for the whole run"
    assert next(iter(trace_ids))


async def test_each_tool_call_started_completed_share_one_span_id():
    """``started``/``completed`` describe the SAME round trip and must join under one spanId;
    the propose call is a distinct round trip and must NOT share the read's spanId."""
    frames = await _drive(
        authority=_Authority("admit", evidence=("get_flagged_transaction",)),
        executor=_Executor(),
        evidence_tools=("get_flagged_transaction",),
    )

    read_started = next(
        f for f in frames if f["kind"] == "tool.started" and f["payload"]["name"] == "get_flagged_transaction"
    )
    read_completed = next(
        f for f in frames if f["kind"] == "tool.completed" and f["payload"]["name"] == "get_flagged_transaction"
    )
    propose_started = next(
        f for f in frames if f["kind"] == "tool.started" and f["payload"]["name"] == "propose_action"
    )
    assert read_started["payload"]["spanId"] == read_completed["payload"]["spanId"]
    assert read_started["payload"]["spanId"] != propose_started["payload"]["spanId"]


async def test_a_failed_tool_call_still_carries_trace_and_span_id():
    frames = await _drive(
        authority=_Authority("admit", evidence=("get_flagged_transaction",)),
        executor=_Executor(fail=True),
        evidence_tools=("get_flagged_transaction",),
    )
    failed = next(f for f in frames if f["kind"] == "tool.failed")
    assert failed["payload"]["traceId"]
    assert failed["payload"]["spanId"]


# --------------------------------------------------------------------------------------------
# Gap 2 — model.call telemetry, end-to-end through the real planner and fan-out engine.
# --------------------------------------------------------------------------------------------


async def test_evidence_answer_emits_a_model_call_frame():
    """The planner's evidence-answer round trip (§8.0 row 5) must land its cost/latency on a
    ``model.call`` frame the run actually emits, not just on a dataclass nobody reads."""

    async def selector(*_args, **_kwargs):
        return IntentDecision(
            kind="read",
            read_plan=({"toolId": "get_flagged_transaction", "arguments": {"transactionId": "tx_1"}},),
            answer_goal="Explain the flagged transaction.",
        )

    async def answerer(*_args, **_kwargs):
        return EvidenceAnswer(
            answer="The wire was flagged because its amount is unusual.",
            cited_evidence_ids=("get_flagged_transaction",),
            model_call=ModelCallTelemetry(
                model_deployment="gpt-4o-eval",
                latency_ms=842,
                prompt_tokens=612,
                completion_tokens=48,
            ),
        )

    frames = await _drive(
        authority=_Authority("admit", evidence=("get_flagged_transaction",)),
        executor=_Executor(),
        evidence_tools=("get_flagged_transaction",),
        action_id=None,
        intent_selector=selector,
        answerer=answerer,
        objective="Why was tx_1 flagged?",
    )

    model_calls = [f for f in frames if f["kind"] == "model.call"]
    assert len(model_calls) == 1
    payload = model_calls[0]["payload"]
    assert payload == {
        "modelDeployment": "gpt-4o-eval",
        "latencyMs": 842,
        "promptTokens": 612,
        "completionTokens": 48,
    }


async def test_evidence_answer_model_call_omits_token_counts_the_sdk_did_not_provide():
    """Some SDK responses carry no usage data at all. Absent, never a fabricated 0."""

    async def selector(*_args, **_kwargs):
        return IntentDecision(
            kind="read",
            read_plan=({"toolId": "get_flagged_transaction", "arguments": {"transactionId": "tx_1"}},),
            answer_goal="Explain the flagged transaction.",
        )

    async def answerer(*_args, **_kwargs):
        return EvidenceAnswer(
            answer="The wire was flagged because its amount is unusual.",
            cited_evidence_ids=("get_flagged_transaction",),
            model_call=ModelCallTelemetry(model_deployment="gpt-4o-eval", latency_ms=310),
        )

    frames = await _drive(
        authority=_Authority("admit", evidence=("get_flagged_transaction",)),
        executor=_Executor(),
        evidence_tools=("get_flagged_transaction",),
        action_id=None,
        intent_selector=selector,
        answerer=answerer,
        objective="Why was tx_1 flagged?",
    )

    payload = next(f for f in frames if f["kind"] == "model.call")["payload"]
    assert payload == {"modelDeployment": "gpt-4o-eval", "latencyMs": 310}
    assert "promptTokens" not in payload
    assert "completionTokens" not in payload


LIMITS = FanoutLimits(
    max_concurrent_subagents=4,
    max_subagent_depth=2,
    per_subagent_tool_budget=20,
    subagent_wall_clock_seconds=60,
)

APPROVAL = {"id": "apr_1", "status": "pending", "requiredRung": "L2", "agentAssessment": {"recommendation": "proceed"}}


def _decider_with_telemetry(recommendation: str, model_call: ModelCallTelemetry):
    def _decider(spawn, own_evidence):
        return SecondOpinion(
            recommendation=recommendation,
            confidence=0.8,
            key_factors=("beneficiary-unverified",),
            strongest_counter_argument="The beneficiary could not be independently verified.",
            model_call=model_call,
        )

    return _decider


async def test_supervisor_second_opinion_emits_a_model_call_frame():
    """The supervisor's independent second-opinion round trip (§8.0 row 5) must land on the
    child (subagent) trace, alongside its own ``tool.completed`` reads."""
    tools = {"get_flagged_transaction": _fanout_tool("get_flagged_transaction", ("transactionId",))}
    registry = _FanoutRegistry(tools)
    executor = _RecordingExecutor({"get_flagged_transaction": {"beneficiary": "SUPERVISOR_SAW_THIS"}})
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    decider = _decider_with_telemetry(
        "proceed",
        ModelCallTelemetry(model_deployment="gpt-4o-eval", latency_ms=511, prompt_tokens=980, completion_tokens=64),
    )
    engine = FanOutEngine(registry=registry, executor=executor, runs=runs, limits=LIMITS, decider=decider)
    stream = runs.create("run_1", "sess_1")

    request = _FanoutRequest(
        run_id="run_1",
        objective="Review the flagged wire on account acc_11.",
        payload={"transactionId": "tx_1", "accountId": "acc_11", "decision": "cleared"},
        facts={},
        session=_FanoutSession(context={"txId": "tx_1"}),
        correlation_id="corr-parent",
    )
    result = await engine.run_second_opinion(
        request, stream, APPROVAL, required_evidence_tool_ids=("get_flagged_transaction",)
    )
    assert result is not None

    child_frames = runs.sink._frames["run_1::supervisor"]  # type: ignore[attr-defined]
    model_calls = [f for f in child_frames if f["kind"] == "model.call"]
    assert len(model_calls) == 1
    assert model_calls[0]["payload"] == {
        "modelDeployment": "gpt-4o-eval",
        "latencyMs": 511,
        "promptTokens": 980,
        "completionTokens": 64,
    }

    # And the read that ran alongside it correlates with the same parent traceId.
    read_frames = [f for f in child_frames if f["kind"] == "tool.completed"]
    assert read_frames
    assert all(f["payload"]["traceId"] == "corr-parent" for f in read_frames)


async def test_a_decider_with_no_model_behind_it_emits_no_model_call_frame():
    """A scripted/deterministic decider makes no model round trip — nothing to attribute, so
    no ``model.call`` frame should appear."""
    tools = {"get_flagged_transaction": _fanout_tool("get_flagged_transaction", ("transactionId",))}
    registry = _FanoutRegistry(tools)
    executor = _RecordingExecutor({"get_flagged_transaction": {"beneficiary": "x"}})
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    engine = FanOutEngine(registry=registry, executor=executor, runs=runs, limits=LIMITS)
    stream = runs.create("run_1", "sess_1")

    request = _FanoutRequest(
        run_id="run_1",
        objective="Review the flagged wire on account acc_11.",
        payload={"transactionId": "tx_1", "accountId": "acc_11", "decision": "cleared"},
        facts={},
        session=_FanoutSession(context={"txId": "tx_1"}),
    )
    await engine.run_second_opinion(request, stream, APPROVAL, required_evidence_tool_ids=("get_flagged_transaction",))

    child_frames = runs.sink._frames["run_1::supervisor"]  # type: ignore[attr-defined]
    assert not [f for f in child_frames if f["kind"] == "model.call"]


# ---- small local helpers to avoid depending on private test-module internals ----


class _FanoutTool:
    def __init__(self, tool_id: str, params: tuple[str, ...]) -> None:
        self.tool_id = tool_id
        self.parameters = {"properties": {p: {"type": "string"} for p in params}}


def _fanout_tool(tool_id: str, params: tuple[str, ...]) -> _FanoutTool:
    return _FanoutTool(tool_id, params)


@dataclass
class _FanoutRequest:
    run_id: str
    objective: str
    payload: dict[str, Any]
    facts: dict[str, Any]
    session: Any
    bearer_token: str = "******"
    correlation_id: str | None = None
