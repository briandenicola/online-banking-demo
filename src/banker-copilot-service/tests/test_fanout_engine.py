"""The fan-out ENGINE, exercised end-to-end (epic §6.2/§6.3/§6.4).

Distinct from ``test_supervisor_blind_construction.py``, which proves the construction shapes.
This proves the coordinator that wires them into the planner: at L2 it spawns exactly one blind
supervisor, gives it the parent's reads minus ``propose_action``, runs it under the config
limits, emits the nested trace frames, and computes agreement AFTER both opinions are in hand.

The supervisor's reader is handed the banker's RAW inputs (payload/facts/context) and re-invokes
the read tools itself — a second, independent draw. It is never handed the primary's ``evidence``
dict. That is asserted here by giving the primary evidence a distinctive value and proving the
supervisor's own reads produce a different one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.fanout import FanOutEngine, SecondOpinion
from app.planner.limits import FanoutLimits

LIMITS = FanoutLimits(
    max_concurrent_subagents=4,
    max_subagent_depth=2,
    per_subagent_tool_budget=20,
    subagent_wall_clock_seconds=60,
)


# ---- Minimal fakes for the executor + registry surface the engine depends on ----


@dataclass
class _FakeResult:
    data: Any
    duration_ms: int = 1

    def summary(self) -> str:
        return "ok"


class _FakeTool:
    def __init__(self, tool_id: str, params: tuple[str, ...]) -> None:
        self.tool_id = tool_id
        self.parameters = {"properties": {p: {"type": "string"} for p in params}}


class _FakeRegistry:
    def __init__(self, tools: dict[str, _FakeTool]) -> None:
        self._tools = tools

    @property
    def tool_ids(self):
        return frozenset(self._tools)

    def get(self, tool_id: str):
        return self._tools.get(tool_id)


class _RecordingExecutor:
    """Records every (tool_id, arguments) so a test can prove WHAT the supervisor read and with
    which arguments — the only honest way to show it read the raw inputs, not the primary cache."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def invoke(self, tool_id: str, arguments: dict[str, Any], bearer: str) -> _FakeResult:
        self.calls.append((tool_id, dict(arguments)))
        return _FakeResult(data=self._responses.get(tool_id, {"ok": True}))


@dataclass
class _Session:
    id: str = "sess_1"
    context: dict[str, Any] = None  # type: ignore[assignment]
    actor_id: str = "usr_banker_1"
    actor_username: str = "banker@example.com"


@dataclass
class _Request:
    run_id: str
    objective: str
    payload: dict[str, Any]
    facts: dict[str, Any]
    bearer_token: str = "******"
    session: _Session = None  # type: ignore[assignment]


def _request() -> _Request:
    return _Request(
        run_id="run_1",
        objective="Review the flagged wire on account acc_11 and transaction tx_1.",
        payload={"transactionId": "tx_1", "accountId": "acc_11", "decision": "cleared"},
        facts={"amount": 250000},
        session=_Session(context={"txId": "tx_1"}),
    )


APPROVAL = {"id": "apr_1", "status": "pending", "requiredRung": "L2"}


def _engine(executor, registry, decider=None):
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    kwargs = {"registry": registry, "executor": executor, "runs": runs, "limits": LIMITS}
    if decider is not None:
        kwargs["decider"] = decider
    return FanOutEngine(**kwargs), runs


def _registry_and_executor():
    tools = {
        "get_flagged_transaction": _FakeTool("get_flagged_transaction", ("transactionId",)),
        "list_account_transactions": _FakeTool("list_account_transactions", ("accountId",)),
    }
    executor = _RecordingExecutor(
        {
            "get_flagged_transaction": {"beneficiary": "SUPERVISOR_SAW_THIS"},
            "list_account_transactions": [{"id": "tx_0"}],
        }
    )
    return _FakeRegistry(tools), executor


@pytest.mark.asyncio
async def test_l2_spawns_one_blind_supervisor_and_emits_nested_frames():
    registry, executor = _registry_and_executor()
    engine, runs = _engine(executor, registry)
    primary_evidence = {"get_flagged_transaction": {"beneficiary": "PRIMARY_SAW_THAT"}}

    stream = runs.create("run_1", "sess_1")
    result = await engine.run_second_opinion(_request(), stream, APPROVAL, primary_evidence)

    assert result is not None
    frames = [f for f in _frames(runs, "run_1")]
    kinds = [f["kind"] for f in frames]
    assert kinds.count("subagent.spawned") == 1
    assert "subagent.completed" in kinds
    assert "approval.updated" in kinds

    spawned = next(f for f in frames if f["kind"] == "subagent.spawned")
    # §6.3: the subagent is offered the parent's reads, never propose_action.
    assert "propose_action" not in spawned["payload"]["toolIds"]
    # §6.4(1): raw entity ids only.
    assert set(spawned["payload"]["entityIds"]) == {"acc_11", "tx_1"}
    assert spawned["payload"]["parentRunId"] == "run_1"


@pytest.mark.asyncio
async def test_supervisor_reads_raw_inputs_not_the_primary_cache():
    """The supervisor's evidence is its OWN draw. The engine gives its reader the banker's raw
    inputs and it re-invokes the tools; the primary's ``evidence`` dict is never passed in."""
    registry, executor = _registry_and_executor()
    engine, runs = _engine(executor, registry)
    primary_evidence = {"get_flagged_transaction": {"beneficiary": "PRIMARY_SAW_THAT"}}

    stream = runs.create("run_1", "sess_1")
    await engine.run_second_opinion(_request(), stream, APPROVAL, primary_evidence)

    # It actually invoked the tool with arguments bound from the raw payload — a real second draw.
    assert ("get_flagged_transaction", {"transactionId": "tx_1"}) in executor.calls
    # And the arguments came from the banker's inputs, never from the primary's cached value.
    for _tool, args in executor.calls:
        assert "PRIMARY_SAW_THAT" not in str(args)


@pytest.mark.asyncio
async def test_agreement_is_computed_after_the_fact():
    """§6.4(6): agreement is a comparison the harness makes, not a value read off the supervisor.
    A supervisor that disagrees does not gate proceeding — the disagreement is recorded."""
    registry, executor = _registry_and_executor()

    def _dissenting(spawn, own_evidence):
        return SecondOpinion(
            recommendation="hold",
            confidence=0.9,
            key_factors=("beneficiary-unverified",),
            strongest_counter_argument="The beneficiary could not be independently verified.",
        )

    engine, runs = _engine(executor, registry, decider=_dissenting)
    stream = runs.create("run_1", "sess_1")
    result = await engine.run_second_opinion(_request(), stream, APPROVAL, {"get_flagged_transaction": {}})

    # Primary proposed (recommendation "proceed"); supervisor said "hold" → disagreement.
    assert result.agrees_with_primary is False
    completed = next(f for f in _frames(runs, "run_1") if f["kind"] == "subagent.completed")
    assert completed["payload"]["agreesWithPrimary"] is False


@pytest.mark.asyncio
async def test_no_grandchildren_the_depth_ceiling_refuses_a_third_level():
    """§6.3: depth 2 is the ceiling. A subagent that tried to fan out again (depth 3) is refused
    structurally, so 'no grandchildren' is a bound rather than a hope."""
    registry, executor = _registry_and_executor()
    engine, runs = _engine(executor, registry)
    stream = runs.create("run_1", "sess_1")

    # depth=2 would make the child depth 3, above the ceiling of 2 → None, and nothing spawned.
    result = await engine.run_second_opinion(
        _request(), stream, APPROVAL, {"get_flagged_transaction": {}}, depth=2
    )
    assert result is None
    assert executor.calls == []


@pytest.mark.asyncio
async def test_tool_budget_caps_the_supervisor_reads():
    """§6.3: the per-subagent tool budget is a real ceiling. With a budget of 1, only the first
    read tool is invoked even though the action required two."""
    registry, executor = _registry_and_executor()
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    tight = FanoutLimits(
        max_concurrent_subagents=4,
        max_subagent_depth=2,
        per_subagent_tool_budget=1,
        subagent_wall_clock_seconds=60,
    )
    engine = FanOutEngine(registry=registry, executor=executor, runs=runs, limits=tight)
    stream = runs.create("run_1", "sess_1")

    await engine.run_second_opinion(
        _request(),
        stream,
        APPROVAL,
        {"get_flagged_transaction": {}, "list_account_transactions": []},
    )
    assert len(executor.calls) == 1


def _frames(runs: RunStreamRegistry, run_id: str) -> list[dict[str, Any]]:
    # InMemoryTraceSink keyed by run_id; read the persisted documents back for assertions.
    sink = runs.sink
    return sink._frames.get(run_id, [])  # type: ignore[attr-defined]


# ---- Loop-level gate: the fan-out fires at L2 and NEVER at L1 (§6.2) ----


class _RecordingFanout:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run_second_opinion(self, request, stream, approval, primary_evidence, depth=1):
        self.calls.append(approval.get("requiredRung"))
        return None


class _Outcome:
    def __init__(self, rung: str) -> None:
        self.status_code = 201
        self.body = {
            "id": "apr_1",
            "status": "pending",
            "requiredRung": rung,
            "policyVersion": "pv1:abcd",
        }

    @property
    def admitted(self) -> bool:
        return True


class _FakeAuthority:
    def __init__(self, rung: str) -> None:
        self._rung = rung

    async def policy_catalogue(self, bearer_token: str):
        # No required evidence → the plan is just [artifact, propose].
        return {"actions": [{"id": "transaction.flag.review", "requiredEvidence": []}]}

    async def propose(self, body, *, bearer_token, session_id, agent_id, correlation_id):
        return _Outcome(self._rung)


class _FakeStore:
    async def save_artifact(self, artifact):
        return None


async def _run_planner_at(rung: str) -> _RecordingFanout:
    from app.planner.loop import Planner, PlannerRequest

    registry, executor = _registry_and_executor()
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    fanout = _RecordingFanout()
    planner = Planner(
        registry=registry,
        executor=executor,
        authority=_FakeAuthority(rung),
        max_iterations=12,
        store=_FakeStore(),
        fanout=fanout,
    )
    req = PlannerRequest(
        session=_Session(context={}),
        run_id="run_1",
        objective="Review flagged wire",
        action_id="transaction.flag.review",
        payload={"transactionId": "tx_1"},
        facts={"amount": 250000},
        bearer_token="******",
    )
    stream = runs.create("run_1", "sess_1")
    await planner.run(req, stream)
    return fanout


@pytest.mark.asyncio
async def test_the_planner_fans_out_at_l2():
    fanout = await _run_planner_at("L2")
    assert fanout.calls == ["L2"]


@pytest.mark.asyncio
async def test_the_planner_never_fans_out_at_l1():
    """§6.2: L1 is single-signature and never triggers a second opinion — batching or
    duplicating a second opinion defeats it. The gate is ``requiredRung == 'L2'``."""
    fanout = await _run_planner_at("L1")
    assert fanout.calls == []
