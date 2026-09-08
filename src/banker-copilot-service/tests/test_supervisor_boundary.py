"""Blind construction pinned AT THE ROUTE BOUNDARY (epic §6.4, Phase 3 wiring).

``test_supervisor_blind_construction.py`` proves ``build_supervisor_input`` itself is blind — it
has no parameter a primary token could travel through. But that guarantee is held by exactly one
thing: the builder's signature. The moment a route CALLS it, the caller becomes the new attack
surface: ``FanOutEngine.run_second_opinion`` constructs the ``BankerIntent`` from a request, and a
dangerous edit that built that intent from the primary's output (its assessment, its reads, its
narrative) would leak — while every direct-builder test stayed green, because none of them exercise
the caller.

So these tests drive the REAL planner end-to-end and assert on WHAT THE SUPERVISOR IS ACTUALLY
HANDED (the ``SupervisorInput`` captured by a decider spy at the boundary), not on what the code was
written to ignore. The primary's work product is seeded with a distinctive sentinel that must appear
nowhere in the supervisor's spawn input.

The default decider is ``deterministic_decider`` — no model, no Foundry endpoint. That is what runs
in the demo. Here we inject a spy decider so the test can capture the exact spawn bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.fanout import FanOutEngine, SecondOpinion, SupervisorInput
from app.planner.limits import FanoutLimits
from app.planner.loop import Planner, PlannerRequest

# A token that exists ONLY in the primary's work product — never in the banker's original request.
# If it reaches the supervisor's spawn input, the caller leaked it.
PRIMARY_SENTINEL = "ZBORK7PRIMARYONLY"

LIMITS = FanoutLimits(
    max_concurrent_subagents=4,
    max_subagent_depth=2,
    per_subagent_tool_budget=20,
    subagent_wall_clock_seconds=60,
)


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


class _Executor:
    """Returns a tool result whose VALUE carries the primary sentinel. This is the primary's
    read — legitimately in the primary's own trace, and the supervisor may re-read the same tool
    itself. What it must NOT do is appear in the supervisor's SPAWN INPUT."""

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


class _Outcome:
    def __init__(self, rung: str, sentinel: str) -> None:
        self.status_code = 201
        self.body = {
            "id": "apr_1",
            "status": "pending",
            "requiredRung": rung,
            "baseRung": "L1",
            "policyVersion": "pv1:abcd",
            "requiredSigners": 2 if rung == "L2" else 1,
            "payloadHash": "sha256:deadbeef",
            # The primary's assessment. In production this echoes the banker's objective; here it
            # is deliberately POISONED with the sentinel to prove the caller builds the supervisor
            # intent from the banker's ORIGINAL request, not from this primary-influenced field.
            "agentAssessment": {"summary": f"primary concluded: {sentinel}", "recommendation": "proceed"},
        }

    @property
    def admitted(self) -> bool:
        return True


class _Authority:
    def __init__(self, rung: str, sentinel: str, evidence_tools: tuple[str, ...]) -> None:
        self._rung = rung
        self._sentinel = sentinel
        self._evidence_tools = evidence_tools

    async def policy_catalogue(self, bearer_token: str):
        return {
            "actions": [
                {"id": "transaction.flag.review", "requiredEvidence": list(self._evidence_tools)}
            ]
        }

    async def propose(self, body, *, bearer_token, session_id, agent_id, correlation_id):
        return _Outcome(self._rung, self._sentinel)


class _Store:
    async def save_artifact(self, artifact):
        return None


class _SpyDecider:
    """Captures the EXACT ``SupervisorInput`` the supervisor was handed at the boundary."""

    def __init__(self) -> None:
        self.spawn: SupervisorInput | None = None

    def __call__(self, spawn: SupervisorInput, own_evidence) -> SecondOpinion:
        self.spawn = spawn
        return SecondOpinion(
            recommendation="proceed",
            confidence=0.8,
            key_factors=tuple(sorted(k for k in own_evidence)),
            strongest_counter_argument="require the second human signature before executing.",
        )


def _frames(runs: RunStreamRegistry, run_id: str) -> list[dict[str, Any]]:
    return runs.sink._frames.get(run_id, [])  # type: ignore[attr-defined]


async def _drive(rung: str, decider) -> tuple[RunStreamRegistry, _Executor]:
    """Run the REAL planner for an action whose evidence tool returns the primary sentinel."""
    tools = {"get_flagged_transaction": _FakeTool("get_flagged_transaction", ("transactionId",))}
    registry = _FakeRegistry(tools)
    # The primary's read carries the sentinel in its VALUE.
    executor = _Executor({"get_flagged_transaction": {"beneficiary": PRIMARY_SENTINEL}})
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    fanout = FanOutEngine(
        registry=registry, executor=executor, runs=runs, limits=LIMITS, decider=decider
    )
    planner = Planner(
        registry=registry,
        executor=executor,
        authority=_Authority(rung, PRIMARY_SENTINEL, ("get_flagged_transaction",)),
        max_iterations=12,
        store=_Store(),
        fanout=fanout,
    )
    req = PlannerRequest(
        session=_Session(context={}),
        run_id="run_1",
        objective="Review the flagged wire on account acc_11 and transaction tx_1.",
        action_id="transaction.flag.review",
        payload={"transactionId": "tx_1", "accountId": "acc_11"},
        facts={"amount": 250000},
        bearer_token="******",
    )
    stream = runs.create("run_1", "sess_1")
    await planner.run(req, stream)
    return runs, executor


@pytest.mark.asyncio
async def test_the_supervisor_spawn_input_carries_no_primary_token():
    """THE caller pin. The supervisor's spawn input, captured at the boundary during a real run,
    contains the banker's own entity ids (anti-vacuous) and NONE of the primary's sentinel."""
    spy = _SpyDecider()
    await _drive("L2", spy)

    assert spy.spawn is not None, "the supervisor never ran — the L2 fan-out did not fire"
    handed = spy.spawn.serialize()
    # Anti-vacuous: the supervisor really was handed the banker's request (its own ids), so the
    # absence of the sentinel below is a real result, not an empty haystack (Phase 1 lesson #1).
    assert "acc_11" in handed and "tx_1" in handed
    # The pin: nothing from the primary's poisoned assessment or its reads reached the spawn.
    assert PRIMARY_SENTINEL not in handed


@pytest.mark.asyncio
async def test_no_supervisor_authored_frame_echoes_the_primary_sentinel():
    """Secondary scan. The sentinel legitimately appears in the PRIMARY's own tool.completed
    frame (the primary really read it). It must appear in NONE of the supervisor-authored frames:
    the spawn, its progress, its completion, or the opinion it contributes to the approval."""
    spy = _SpyDecider()
    runs, _ = await _drive("L2", spy)
    frames = _frames(runs, "run_1")

    supervisor_kinds = {"subagent.spawned", "subagent.progress", "subagent.completed"}
    supervisor_frames = [f for f in frames if f["kind"] in supervisor_kinds]
    assert supervisor_frames, "no supervisor frames were emitted"
    import json

    for frame in supervisor_frames:
        assert PRIMARY_SENTINEL not in json.dumps(frame["payload"]), (
            f"{frame['kind']} echoed the primary sentinel"
        )

    # ``approval.updated`` carries the whole ApprovalRequest, which LEGITIMATELY includes the
    # primary's own agentAssessment (the contract keeps the primary opinion on the approval). The
    # blind guarantee is narrower and sharper: the SUPERVISOR's appended opinion — its verdict,
    # rationale, factors and cited evidence — must contain no primary token.
    updated = next(f for f in frames if f["kind"] == "approval.updated")
    supervisor_opinion = next(
        o for o in updated["payload"]["request"]["opinions"] if o["role"] == "supervisor"
    )
    assert PRIMARY_SENTINEL not in json.dumps(supervisor_opinion)

    # And the primary DID surface it — proving the sentinel was live and the scan is meaningful.
    assert any(
        PRIMARY_SENTINEL in __import__("json").dumps(f["payload"])
        for f in frames
        if f["kind"] == "tool.completed" and f.get("payload", {}).get("result") is not None
    )


@pytest.mark.asyncio
async def test_l1_does_not_spawn_the_supervisor_at_all():
    """§6.2: L1 is single-signature and never fans out. The decider spy is never called."""
    spy = _SpyDecider()
    runs, _ = await _drive("L1", spy)

    assert spy.spawn is None, "the supervisor ran for an L1 action — batching a second opinion defeats it"
    kinds = [f["kind"] for f in _frames(runs, "run_1")]
    assert "subagent.spawned" not in kinds


@pytest.mark.asyncio
async def test_the_second_opinion_never_advances_the_approval_toward_execution():
    """The invariant. Whatever the supervisor says — even a maximally-confident 'proceed' — its
    opinion is EVIDENCE for a human, never a signature. It must not sign, terminalise, or execute
    anything; the approval leaves the fan-out exactly as pending as it arrived."""

    def _enthusiastic(spawn, own_evidence):
        return SecondOpinion(
            recommendation="proceed",
            confidence=1.0,
            key_factors=("all-clear",),
            strongest_counter_argument="none",
        )

    runs, _ = await _drive("L2", _enthusiastic)
    frames = _frames(runs, "run_1")
    kinds = [f["kind"] for f in frames]

    # No terminal/execution transition was emitted by the second opinion.
    assert "approval.terminal" not in kinds

    updated = next(f for f in frames if f["kind"] == "approval.updated")
    request = updated["payload"]["request"]
    # The supervisor added an OPINION (evidence), not a signature, and did not advance the state.
    assert request["status"] == "pending"
    assert not request.get("signatures")
    supervisor_opinion = next(o for o in request["opinions"] if o["role"] == "supervisor")
    assert supervisor_opinion["verdict"] == "APPROVE"  # it agreed — and STILL nothing executed.
