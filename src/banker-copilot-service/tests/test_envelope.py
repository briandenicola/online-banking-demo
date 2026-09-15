"""`CopilotEventEnvelope` — the one schema serving both the live stream and eval replay."""

from __future__ import annotations

import asyncio
import re

import pytest

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.events.envelope import (
    EVENT_KINDS,
    TERMINAL_REASONS,
    CopilotEventEnvelope,
    EnvelopeError,
    utc_now_iso,
)

#: Mirrors docs/design/banker-copilot-ui.md §4.2 exactly. Compared as a SET so a kind added on
#: one side and not the other fails by name, in both directions.
UI_CONTRACT_KINDS = frozenset(
    {
        "run.started",
        "plan.proposed",
        "plan.revised",
        "step.started",
        "step.completed",
        "step.failed",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "subagent.spawned",
        "subagent.progress",
        "subagent.completed",
        "approval.required",
        "approval.updated",
        "approval.terminal",
        "artifact.created",
        "artifact.updated",
        "run.error",
        "run.done",
        "heartbeat",
        "mode_transition",
        "evidence_compacted",
        "evidence_progress",
        "sensitive_read_recorded",
        "model.call",
    }
)


def test_event_kinds_match_the_ui_contract_exactly():
    assert EVENT_KINDS == UI_CONTRACT_KINDS


def test_terminal_reasons_are_the_closed_enum():
    assert TERMINAL_REASONS == frozenset(
        {"HUMAN_DENIED", "POLICY_RUNG_ESCALATED", "PAYLOAD_SUPERSEDED", "TTL_EXPIRED"}
    )


def test_unknown_kind_is_refused():
    with pytest.raises(EnvelopeError, match="unknown event kind"):
        CopilotEventEnvelope(
            id="evt_1", seq=1, run_id="run_1", kind="approval.voided", ts=utc_now_iso()
        )


def test_denied_terminal_frame_requires_a_terminal_reason():
    """Without it, replay scores a policy-driven void as the banker rejecting the agent."""
    with pytest.raises(EnvelopeError, match="terminalReason"):
        CopilotEventEnvelope(
            id="evt_1",
            seq=1,
            run_id="run_1",
            kind="approval.terminal",
            ts=utc_now_iso(),
            payload={"state": "denied"},
        )


def test_terminal_frame_rejects_a_state_outside_the_lifecycle():
    for bad_state in ("expired", "voided", "execution_failed"):
        with pytest.raises(EnvelopeError):
            CopilotEventEnvelope(
                id="evt_1",
                seq=1,
                run_id="run_1",
                kind="approval.terminal",
                ts=utc_now_iso(),
                payload={"state": bad_state},
            )


@pytest.mark.parametrize("reason", sorted(TERMINAL_REASONS))
def test_every_terminal_reason_is_accepted(reason):
    envelope = CopilotEventEnvelope(
        id="evt_1",
        seq=1,
        run_id="run_1",
        kind="approval.terminal",
        ts=utc_now_iso(),
        payload={"state": "denied", "terminalReason": reason},
    )
    assert envelope.payload["terminalReason"] == reason


def test_ts_is_server_utc_iso8601():
    envelope = CopilotEventEnvelope(
        id="evt_1", seq=1, run_id="run_1", kind="heartbeat", ts=utc_now_iso()
    )
    assert re.match(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z$", envelope.ts)


def _drain(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_seq_is_monotonic_and_gapless_per_run():
    async def scenario():
        registry = RunStreamRegistry(InMemoryTraceSink(), replay_window=100)
        stream = registry.create("run_a", "sess_a")
        for _ in range(5):
            await stream.emit("heartbeat", {"serverTs": utc_now_iso()})
        return [event.seq for event in stream._recent]

    seqs = asyncio.run(scenario())
    assert seqs == [1, 2, 3, 4, 5]


def test_seq_is_scoped_to_the_run_not_the_session():
    """A session with two runs has two independently replayable traces.

    If seq were session-scoped, replaying run B alone would start at an arbitrary number and
    its gap detection would be meaningless.
    """

    async def scenario():
        registry = RunStreamRegistry(InMemoryTraceSink(), replay_window=100)
        run_a = registry.create("run_a", "sess_shared")
        run_b = registry.create("run_b", "sess_shared")
        await run_a.emit("heartbeat", {})
        await run_a.emit("heartbeat", {})
        first_b = await run_b.emit("heartbeat", {})
        return run_a.last_seq, first_b.seq

    a_last, b_first = asyncio.run(scenario())
    assert (a_last, b_first) == (2, 1)


def test_every_emitted_frame_is_persisted_as_emitted():
    """Epic §8.0: persisted as the frame is emitted, never reconstructed after."""

    async def scenario():
        sink = InMemoryTraceSink()
        registry = RunStreamRegistry(sink, replay_window=100)
        stream = registry.create("run_p", "sess_p")
        await stream.emit("run.started", {"intent": "x"})
        await stream.emit(
            "tool.started",
            {
                "name": "get_account",
                "toolId": "get_account",
                "mode": "plan",
                "traceId": "trace_x",
                "spanId": "span_x",
            },
        )
        await stream.emit("run.done", {"status": "completed", "finalSeq": 3})
        return await sink.read_run("run_p")

    frames = asyncio.run(scenario())
    assert [frame["seq"] for frame in frames] == [1, 2, 3]
    assert [frame["kind"] for frame in frames] == ["run.started", "tool.started", "run.done"]
    assert {frame["runId"] for frame in frames} == {"run_p"}


def test_persisted_frame_is_a_superset_of_the_wire_frame():
    """The UI frame and the trace frame are one schema. A replay must reconstruct exactly what
    the banker saw, so the persisted document may add provenance but may never reshape."""
    envelope = CopilotEventEnvelope(
        id="evt_x",
        seq=7,
        run_id="run_x",
        kind="tool.completed",
        ts=utc_now_iso(),
        payload={
            "toolCallId": "call_1",
            "name": "get_account",
            "mode": "plan",
            "durationMs": 12,
            "traceId": "trace_x",
            "spanId": "span_x",
        },
        session_id="sess_x",
    )
    wire = envelope.to_wire()
    document = envelope.to_document(parent_run_id="run_parent")

    assert set(wire).issubset(set(document))
    for key, value in wire.items():
        assert document[key] == value
    assert document["parentRunId"] == "run_parent"


def test_a_sink_failure_degrades_the_run_rather_than_silently_losing_frames():
    """A trace with silently missing frames is worse than no trace: #333 would replay it as
    though it were complete."""

    class BrokenSink(InMemoryTraceSink):
        async def append(self, envelope, parent_run_id):
            raise RuntimeError("cosmos unavailable")

    async def scenario():
        registry = RunStreamRegistry(BrokenSink(), replay_window=100)
        stream = registry.create("run_d", "sess_d")
        await stream.emit("heartbeat", {})
        return stream.trace_degraded, stream.last_seq

    degraded, last_seq = asyncio.run(scenario())
    assert degraded is True
    assert last_seq == 1


def test_replay_window_shortfall_is_detected_rather_than_papered_over():
    async def scenario():
        registry = RunStreamRegistry(InMemoryTraceSink(), replay_window=3)
        stream = registry.create("run_w", "sess_w")
        for _ in range(10):
            await stream.emit("heartbeat", {})
        return stream.replay_available_from(1), stream.replay_available_from(9)

    stale, fresh = asyncio.run(scenario())
    assert stale is False
    assert fresh is True


def test_mode_transition_is_closed_and_exactly_shaped():
    envelope = CopilotEventEnvelope(
        id="evt_mode",
        seq=1,
        run_id="run_mode",
        session_id="sess_mode",
        kind="mode_transition",
        ts=utc_now_iso(),
        payload={"from": "plan", "to": "execute"},
    )
    assert envelope.to_wire()["payload"] == {"from": "plan", "to": "execute"}

    for payload in (
        {"from": "execute", "to": "plan"},
        {"from": "plan", "to": "execute", "extra": True},
        {"from": "plan", "to": "foundry"},
    ):
        with pytest.raises(EnvelopeError):
            CopilotEventEnvelope(
                id="evt_mode",
                seq=1,
                run_id="run_mode",
                kind="mode_transition",
                ts=utc_now_iso(),
                payload=payload,
            )


def test_tool_invocation_requires_mode_and_execute_is_reserved_for_proposal():
    with pytest.raises(EnvelopeError, match="requires mode"):
        CopilotEventEnvelope(
            id="evt_tool",
            seq=1,
            run_id="run_tool",
            kind="tool.started",
            ts=utc_now_iso(),
            payload={"name": "get_account"},
        )
    with pytest.raises(EnvelopeError, match="only propose_action"):
        CopilotEventEnvelope(
            id="evt_tool",
            seq=1,
            run_id="run_tool",
            kind="tool.started",
            ts=utc_now_iso(),
            payload={"name": "get_account", "mode": "execute"},
        )


def test_tool_invocation_requires_trace_id_and_span_id():
    """§8.0: eval needs to correlate an agent's tool-call decision with the OTEL span across
    services, which is unreadable if either id can be silently absent."""
    base_payload = {"name": "get_account", "mode": "plan"}
    with pytest.raises(EnvelopeError, match="traceId"):
        CopilotEventEnvelope(
            id="evt_tool", seq=1, run_id="run_tool", kind="tool.started", ts=utc_now_iso(),
            payload=dict(base_payload, spanId="span_1"),
        )
    with pytest.raises(EnvelopeError, match="spanId"):
        CopilotEventEnvelope(
            id="evt_tool", seq=1, run_id="run_tool", kind="tool.completed", ts=utc_now_iso(),
            payload=dict(base_payload, traceId="trace_1"),
        )
    # Present and non-empty on all three tool frame kinds is accepted.
    for kind in ("tool.started", "tool.completed", "tool.failed"):
        CopilotEventEnvelope(
            id="evt_tool", seq=1, run_id="run_tool", kind=kind, ts=utc_now_iso(),
            payload=dict(base_payload, traceId="trace_1", spanId="span_1"),
        )


def test_model_call_requires_deployment_and_latency():
    with pytest.raises(EnvelopeError, match="modelDeployment"):
        CopilotEventEnvelope(
            id="evt_m", seq=1, run_id="run_m", kind="model.call", ts=utc_now_iso(),
            payload={"latencyMs": 120},
        )
    with pytest.raises(EnvelopeError, match="latencyMs"):
        CopilotEventEnvelope(
            id="evt_m", seq=1, run_id="run_m", kind="model.call", ts=utc_now_iso(),
            payload={"modelDeployment": "gpt-4o"},
        )
    with pytest.raises(EnvelopeError, match="non-negative"):
        CopilotEventEnvelope(
            id="evt_m", seq=1, run_id="run_m", kind="model.call", ts=utc_now_iso(),
            payload={"modelDeployment": "gpt-4o", "latencyMs": -1},
        )


def test_model_call_token_counts_are_optional_but_must_be_non_negative_when_present():
    # Absent entirely — the SDK response carried no usage data. Accepted.
    CopilotEventEnvelope(
        id="evt_m", seq=1, run_id="run_m", kind="model.call", ts=utc_now_iso(),
        payload={"modelDeployment": "gpt-4o", "latencyMs": 250},
    )
    # Present and valid.
    CopilotEventEnvelope(
        id="evt_m", seq=1, run_id="run_m", kind="model.call", ts=utc_now_iso(),
        payload={
            "modelDeployment": "gpt-4o",
            "latencyMs": 250,
            "promptTokens": 500,
            "completionTokens": 40,
        },
    )
    with pytest.raises(EnvelopeError, match="promptTokens"):
        CopilotEventEnvelope(
            id="evt_m", seq=1, run_id="run_m", kind="model.call", ts=utc_now_iso(),
            payload={"modelDeployment": "gpt-4o", "latencyMs": 250, "promptTokens": -5},
        )
    with pytest.raises(EnvelopeError, match="completionTokens"):
        CopilotEventEnvelope(
            id="evt_m", seq=1, run_id="run_m", kind="model.call", ts=utc_now_iso(),
            payload={"modelDeployment": "gpt-4o", "latencyMs": 250, "completionTokens": -1},
        )


def test_evidence_compacted_payload_is_closed_and_validated():
    payload = {
        "compactedIds": ["get_transactions"],
        "originalTokensEstimate": 100,
        "compactedTokensEstimate": 20,
    }
    envelope = CopilotEventEnvelope(
        id="evt_compact",
        seq=1,
        run_id="run_compact",
        kind="evidence_compacted",
        ts=utc_now_iso(),
        payload=payload,
    )
    assert envelope.to_wire()["payload"] == payload

    malformed = (
        {"compactedIds": [], "originalTokensEstimate": 1},
        {"compactedIds": ["x"], "originalTokensEstimate": -1, "compactedTokensEstimate": 0},
        {"compactedIds": [], "originalTokensEstimate": 1, "compactedTokensEstimate": 0},
        {"compactedIds": ["x"], "originalTokensEstimate": 1, "compactedTokensEstimate": 2},
        {"compactedIds": [1], "originalTokensEstimate": 1, "compactedTokensEstimate": 0},
    )
    for invalid in malformed:
        with pytest.raises(EnvelopeError):
            CopilotEventEnvelope(
                id="evt_compact",
                seq=1,
                run_id="run_compact",
                kind="evidence_compacted",
                ts=utc_now_iso(),
                payload=invalid,
            )


def test_evidence_progress_keeps_policy_satisfaction_and_model_choice_separate():
    payload = {
        "requiredEvidenceToolIds": ["get_account", "get_flagged_transaction"],
        "satisfiedRequiredEvidenceToolIds": ["get_account"],
        "discretionaryEvidenceToolIds": ["list_login_audits"],
    }
    envelope = CopilotEventEnvelope(
        id="evt_progress", seq=1, run_id="run_progress", kind="evidence_progress",
        ts=utc_now_iso(), payload=payload,
    )
    assert envelope.payload == payload


@pytest.mark.parametrize("payload", [
    {},
    {"requiredEvidenceToolIds": [], "satisfiedRequiredEvidenceToolIds": [],
     "discretionaryEvidenceToolIds": [], "mergedEvidenceToolIds": []},
    {"requiredEvidenceToolIds": ["get_account"],
     "satisfiedRequiredEvidenceToolIds": ["unknown"], "discretionaryEvidenceToolIds": []},
    {"requiredEvidenceToolIds": ["get_account"],
     "satisfiedRequiredEvidenceToolIds": [], "discretionaryEvidenceToolIds": ["get_account"]},
    {"requiredEvidenceToolIds": ["get_account", "get_account"],
     "satisfiedRequiredEvidenceToolIds": [], "discretionaryEvidenceToolIds": []},
    {"requiredEvidenceToolIds": [" "], "satisfiedRequiredEvidenceToolIds": [],
     "discretionaryEvidenceToolIds": []},
    None,
])
def test_evidence_progress_rejects_missing_malformed_or_merged_payload(payload):
    with pytest.raises(EnvelopeError):
        CopilotEventEnvelope(
            id="evt_progress", seq=1, run_id="run_progress", kind="evidence_progress",
            ts=utc_now_iso(), payload=payload,  # type: ignore[arg-type]
        )
