from __future__ import annotations

import pytest

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.agent_mode import AgentMode


@pytest.mark.asyncio
async def test_agent_mode_transitions_once_and_emits_normal_scoped_event():
    sink = InMemoryTraceSink()
    stream = RunStreamRegistry(sink, replay_window=20).create("run_1", "session_1")
    mode = AgentMode()

    await mode.transition_to_execute(stream)

    assert mode.current == "execute"
    frames = await sink.read_run("run_1")
    assert len(frames) == 1
    assert frames[0]["kind"] == "mode_transition"
    assert frames[0]["runId"] == "run_1"
    assert frames[0]["sessionId"] == "session_1"

    with pytest.raises(RuntimeError, match="only once"):
        await mode.transition_to_execute(stream)

@pytest.mark.asyncio
async def test_emitted_invocations_reserve_execute_for_propose_action():
    stream = RunStreamRegistry(InMemoryTraceSink(), replay_window=20).create("run_2", "session_2")
    await stream.emit(
        "tool.started",
        {
            "toolCallId": "call_read", "name": "get_account", "toolId": "get_account",
            "mode": "plan", "traceId": "trace_1", "spanId": "span_1",
        },
    )
    await stream.emit(
        "tool.started",
        {
            "toolCallId": "call_propose", "name": "propose_action", "toolId": "propose_action",
            "mode": "execute", "traceId": "trace_1", "spanId": "span_2",
        },
    )

    invocations = [event for event in stream._recent if event.kind == "tool.started"]
    assert invocations
    assert all(
        event.payload["mode"] == "plan" or event.payload["name"] == "propose_action"
        for event in invocations
    )
