"""``CopilotEventEnvelope`` replay fidelity — ONE schema, live stream and eval replay.

Epic §8.0 ratifies the UI's envelope as the single trace schema and says the
quiet part out loud:

    "Any divergence between what the UI consumes and what we persist is a bug,
    not a design choice."

**How this test lies to you.** A replay-fidelity test is trivially green if
``replay()`` hands back the same in-memory objects the live stream rendered
from. It compares a list to itself and reports the eval contract as satisfied.
Every assertion in this file is therefore written to defeat that:

  * the store holds **serialized frames only** — it raises on an object;
  * ``replay()`` parses JSON back out of the store, so equality is a
    round-trip, not an identity;
  * the live sink is asserted to be a **different object** from the replay
    result, and at least one test drops the live sink entirely before replaying;
  * every count assertion has an anti-vacuous floor, because a run that emitted
    nothing replays perfectly.
"""

from __future__ import annotations

import json

import pytest

from spec.envelope import (
    EVENT_KINDS,
    REQUIRED_PAYLOAD_FIELDS,
    TERMINAL_REASONS,
    CopilotEventEnvelope,
    EnvelopeError,
    Run,
    RunId,
    SessionId,
    TraceEmitter,
    TraceStore,
    redact,
    replay,
)


@pytest.fixture
def emitter(fixed_clock):
    return TraceEmitter(store=TraceStore(), clock=fixed_clock)


def _session_run(session="ses_1", run="run_1", parent=None):
    return Run(
        runId=RunId(run),
        sessionId=SessionId(session),
        parentRunId=RunId(parent) if parent else None,
    )


def _full_run(emitter: TraceEmitter, run: Run) -> None:
    emitter.emit(run, "run.started", {"taskId": "t", "title": "x", "intent": "i",
                                      "actor": {"id": "b1"}, "startedAt": "2026-09-04T00:00:00Z"})
    emitter.emit(run, "plan.proposed", {"version": 1, "steps": []})
    emitter.emit(run, "tool.started", {"toolCallId": "c1", "stepId": "s1", "name": "get_flagged_transaction",
                                       "attempt": 1, "traceId": "tr1", "spanId": "sp1"})
    emitter.emit(run, "tool.completed", {"toolCallId": "c1", "durationMs": 3,
                                         "traceId": "tr1", "spanId": "sp1"})
    emitter.emit(run, "approval.required", {"request": {"approvalId": "apr_1"},
                                            "policyVersion": "pv1:abc", "resolvedRung": "L2"})
    emitter.emit(run, "approval.terminal", {"approvalId": "apr_1", "state": "denied",
                                            "terminalReason": "POLICY_RUNG_ESCALATED",
                                            "terminalAt": "2026-09-04T00:01:00Z",
                                            "previousPayloadHash": "h1"})
    emitter.emit(run, "run.done", {"status": "completed", "durationMs": 9,
                                   "finalArtifactIds": [], "finalSeq": emitter.next_seq(run)})


# ---------------------------------------------------------------------------
# The fidelity property itself.
# ---------------------------------------------------------------------------


def test_a_persisted_trace_replays_to_the_sequence_the_live_stream_produced(emitter):
    run = _session_run()
    live = emitter.subscribe(run.sessionId)

    _full_run(emitter, run)

    replayed = replay(emitter.store, run.runId.value)

    assert len(live) >= 7, "anti-vacuous: an empty run replays perfectly and proves nothing"
    assert replayed is not live
    assert [f.to_json() for f in replayed] == [f.to_json() for f in live]
    assert [f.kind for f in replayed] == [f.kind for f in live]
    assert [f.seq for f in replayed] == [f.seq for f in live]


def test_replay_works_with_the_live_stream_thrown_away(emitter):
    """The eval case: nobody was watching, and the run finished last Tuesday.

    If replay depended in any way on the live subscription, this is where it
    breaks. Persisting only for connected clients is an easy accident and an
    invisible one — the demo looks perfect and #333 has no corpus.
    """
    run = _session_run()
    _full_run(emitter, run)  # no subscriber at all

    replayed = replay(emitter.store, run.runId.value)

    assert len(replayed) >= 7
    assert replayed[0].kind == "run.started"
    assert replayed[-1].kind == "run.done"


def test_the_store_holds_bytes_not_objects(emitter):
    """The guard that stops this whole file from being self-comparison."""
    run = _session_run()
    _full_run(emitter, run)

    raw = emitter.store.raw_frames(run.runId.value)
    assert raw and all(isinstance(r, str) for r in raw)
    assert all(json.loads(r)["runId"] == run.runId.value for r in raw)

    with pytest.raises(TypeError):
        emitter.store.append(run.runId.value, {"not": "serialized"})


def test_a_frame_is_persisted_before_it_is_published(emitter):
    """Ordering, not just presence.

    Publish-then-persist survives every test that checks both happened, and
    fails exactly once — in a crash, where the banker saw a step that no replay
    will ever contain. Asserted by observing the store from inside the
    subscriber.
    """
    run = _session_run()
    observations: list[int] = []

    class ObservingSink(list):
        def append(self, item):  # noqa: ANN001
            observations.append(len(emitter.store.raw_frames(run.runId.value)))
            super().append(item)

    sink = ObservingSink()
    emitter._subscribers.setdefault(run.sessionId.value, []).append(sink)

    _full_run(emitter, run)

    assert observations, "anti-vacuous: the subscriber must have received frames"
    for index, persisted_count in enumerate(observations, start=1):
        assert persisted_count == index, (
            "the frame was published before it was persisted; a crash between the two "
            "loses eval data the UI already showed"
        )


# ---------------------------------------------------------------------------
# The properties replay depends on.
# ---------------------------------------------------------------------------


def test_seq_is_monotonic_and_gapless_per_run(emitter):
    run = _session_run()
    _full_run(emitter, run)
    frames = replay(emitter.store, run.runId.value)
    assert [f.seq for f in frames] == list(range(1, len(frames) + 1))


def test_seq_is_per_run_not_per_session(emitter):
    """Two runs in one session each start at 1.

    A session-wide counter looks identical in a single-run demo and destroys
    per-run replay the moment a banker asks a second question.
    """
    a, b = _session_run(run="run_1"), _session_run(run="run_2")
    _full_run(emitter, a)
    _full_run(emitter, b)

    assert [f.seq for f in replay(emitter.store, "run_1")][:1] == [1]
    assert [f.seq for f in replay(emitter.store, "run_2")][:1] == [1]
    assert set(emitter.store.run_ids()) == {"run_1", "run_2"}


def test_a_gap_in_the_persisted_frames_is_detected_rather_than_replayed(emitter):
    """Never render a known-incomplete trace as if it were complete (UI §4.4).

    The offline equivalent: never SCORE a known-incomplete trajectory. A missing
    frame that replays silently produces an eval verdict on an agent run nobody
    actually observed.
    """
    run = _session_run()
    _full_run(emitter, run)

    frames = list(emitter.store.raw_frames(run.runId.value))
    del emitter.store._frames[run.runId.value][2]

    with pytest.raises(EnvelopeError, match="seq gap"):
        replay(emitter.store, run.runId.value)

    assert len(frames) > 3


def test_run_done_final_seq_must_equal_its_own_seq(emitter):
    run = _session_run()
    emitter.emit(run, "heartbeat", {"serverTs": "x"})
    with pytest.raises(EnvelopeError, match="finalSeq"):
        emitter.emit(run, "run.done", {"status": "completed", "durationMs": 1,
                                       "finalArtifactIds": [], "finalSeq": 99})


def test_a_frame_after_run_done_is_refused(emitter):
    run = _session_run()
    _full_run(emitter, run)
    with pytest.raises(EnvelopeError, match="run.done"):
        emitter.emit(run, "heartbeat", {"serverTs": "x"})


def test_the_timestamp_is_the_server_clock(emitter):
    """§8.0: server clock ``ts``, never client.

    ``emit`` takes no timestamp parameter, so there is no input through which a
    client clock could arrive — the same "absence of a parameter is the control"
    shape as Phase 1's ``ExecuteAsync``.
    """
    import inspect

    params = set(inspect.signature(TraceEmitter.emit).parameters)
    assert params == {"self", "run", "kind", "payload"}
    run = _session_run()
    frame = emitter.emit(run, "heartbeat", {"serverTs": "ignored"})
    assert frame.ts.startswith("2026-09-04T00:00:")


# ---------------------------------------------------------------------------
# The closed schema, checked against the ratified document rather than a copy.
# ---------------------------------------------------------------------------


def test_the_kind_union_matches_the_ratified_ui_design(ui_event_kinds):
    """Derived from the spec text, not transcribed.

    Phase 1's worst tests were the ones that transcribed an expectation and then
    defended it. This reads ``CopilotEventKind`` out of
    ``docs/design/banker-copilot-ui.md`` §4.2 — the contract of record per §8.0 —
    so the oracle cannot drift from the document silently.
    """
    assert set(EVENT_KINDS) == set(ui_event_kinds)
    assert len(ui_event_kinds) == 20


def test_the_epic_prose_and_the_ui_union_disagree_on_the_terminal_frame_name(repo_root):
    """FINDING F2-2, asserted so it cannot be forgotten.

    Epic §8.0 lists ``approval.required/updated/voided`` and later requires "an
    ``approval.voided`` frame with reason ``POLICY_RUNG_ESCALATED``". The UI
    design §4.2 renamed that frame ``approval.terminal`` and documents why:
    there is no ``void`` lifecycle state, so an event named for one reintroduces
    the distinction §5.1.1 collapsed into ``terminalReason``.

    Both documents are ratified and they name the same frame differently — the
    exact class of drift §0.1 exists to prevent, in the schema §8.0 calls the
    contract of record. The UI name is the one I have taken as normative,
    because §8.0 defers to "the envelope in ``banker-copilot-ui.md`` §4.2 is the
    contract of record."

    This test asserts the CURRENT state. It goes red when the epic is corrected.
    """
    epic = (repo_root / "docs" / "epics" / "banker-copilot.md").read_text(encoding="utf-8")
    assert "approval.voided" in epic, (
        "the epic no longer says approval.voided — if §8.0 was corrected to "
        "approval.terminal, delete this test and close finding F2-2"
    )
    assert "approval.terminal" not in EVENT_KINDS or True
    assert "approval.terminal" in EVENT_KINDS


def test_an_unknown_kind_cannot_be_emitted(emitter):
    run = _session_run()
    with pytest.raises(EnvelopeError, match="unknown event kind"):
        emitter.emit(run, "approval.voided", {"approvalId": "apr_1"})


def test_an_unknown_envelope_field_is_refused_on_read_back():
    with pytest.raises(EnvelopeError, match="unknown envelope field"):
        CopilotEventEnvelope.from_json(
            json.dumps({"id": "e", "seq": 1, "runId": "run_1", "kind": "heartbeat",
                        "ts": "t", "payload": {}, "extra": 1})
        )


# ---------------------------------------------------------------------------
# The §8.0 eval-driven additions. Each is unrecoverable if missed at emit.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind,fields", sorted(REQUIRED_PAYLOAD_FIELDS.items()))
def test_the_eval_required_fields_are_enforced_at_emit(emitter, kind, fields):
    run = _session_run()
    base = {
        "tool.started": {"toolCallId": "c", "stepId": "s", "name": "n", "attempt": 1},
        "tool.completed": {"toolCallId": "c", "durationMs": 1},
        "tool.failed": {"toolCallId": "c", "error": "e", "attempt": 1, "willRetry": False},
        "subagent.spawned": {"subagentId": "sa1", "parentStepId": "s", "name": "n",
                             "role": "specialist", "depth": 1},
        "approval.required": {"request": {"approvalId": "apr_1"}},
    }[kind]

    for missing in fields:
        payload = dict(base)
        payload.update({f: "v" for f in fields if f != missing})
        with pytest.raises(EnvelopeError, match=missing):
            emitter.emit(run, kind, payload)


def test_a_denied_approval_frame_without_a_terminal_reason_is_refused(emitter):
    """§8.0 composition with O9.

    Without ``terminalReason`` on the terminal frame, an offline replay cannot
    tell a policy void from a human denial — and scores the policy rollout as a
    model regression. The direction of the error is what makes it expensive.
    """
    run = _session_run()
    with pytest.raises(EnvelopeError, match="terminalReason"):
        emitter.emit(run, "approval.terminal", {"approvalId": "a", "state": "denied",
                                                "terminalAt": "t", "previousPayloadHash": "h"})


@pytest.mark.parametrize("reason", ["EXPIRED", "VOIDED", "human_denied", "", None])
def test_a_terminal_reason_outside_the_closed_enum_is_refused(emitter, reason):
    run = _session_run()
    payload = {"approvalId": "a", "state": "denied", "terminalAt": "t",
               "previousPayloadHash": "h", "terminalReason": reason}
    with pytest.raises(EnvelopeError):
        emitter.emit(run, "approval.terminal", payload)


@pytest.mark.parametrize("reason", TERMINAL_REASONS)
def test_every_member_of_the_closed_enum_is_accepted(emitter, reason):
    """Both directions. A validator that rejects everything passes the tests above."""
    run = _session_run()
    frame = emitter.emit(run, "approval.terminal", {"approvalId": "a", "state": "denied",
                                                    "terminalAt": "t",
                                                    "previousPayloadHash": "h",
                                                    "terminalReason": reason})
    assert frame.payload["terminalReason"] == reason


def test_an_executed_approval_frame_needs_no_reason(emitter):
    run = _session_run()
    frame = emitter.emit(run, "approval.terminal", {"approvalId": "a", "state": "executed",
                                                    "terminalAt": "t",
                                                    "previousPayloadHash": "h"})
    assert "terminalReason" not in frame.payload


def test_the_kind_union_has_no_frame_that_can_carry_model_and_token_counts(ui_event_kinds):
    """FINDING F2-3.

    Epic §8.0 requires "Model, deployment, token counts on **model-call
    frames**" — but §4.2's closed union has no model-call kind, and the union is
    closed by design. So that row of §8.0 is unsatisfiable without a schema
    change, and cost/regression attribution per run (#333) has nowhere to live.

    Asserted as the current state. When a model-call kind lands, this test goes
    red and should be replaced by a real requirement test.
    """
    assert not [k for k in ui_event_kinds if "model" in k or "llm" in k], (
        "a model-call kind now exists — replace this finding with an assertion that it "
        "carries model, deployment and token counts (epic §8.0)"
    )


# ---------------------------------------------------------------------------
# Redaction at emit, not at render.
# ---------------------------------------------------------------------------


def test_redaction_is_applied_before_persistence(fixed_clock):
    """§8.0: "persisted traces outlive the session; PII must never be written."

    The false pass here is redacting in the UI and testing the UI. The assertion
    that matters is on the BYTES in the store.
    """
    emitter = TraceEmitter(
        store=TraceStore(),
        clock=fixed_clock,
        redaction_paths={"tool.completed": ("$.result.customer.ssn",)},
    )
    run = _session_run()
    live = emitter.subscribe(run.sessionId)

    emitter.emit(run, "tool.completed", {"toolCallId": "c", "durationMs": 1,
                                         "traceId": "tr", "spanId": "sp",
                                         "result": {"customer": {"ssn": "123-45-6789",
                                                                 "name": "A"}}})

    raw = emitter.store.raw_frames(run.runId.value)[0]
    assert "123-45-6789" not in raw
    assert "\"name\":\"A\"" in raw.replace(" ", "")
    # And the live frame is redacted too — one code path, not two.
    assert "ssn" not in json.dumps(live[0].payload)


def test_redaction_handles_the_array_form_the_manifest_actually_uses():
    """``$[*].ipAddress`` — the shape ``list_login_audits`` declares in §3.3."""
    payload = [{"ipAddress": "10.0.0.1", "userId": "u1"}, {"ipAddress": "10.0.0.2", "userId": "u2"}]
    cleaned = redact(payload, ["$[*].ipAddress"])
    assert cleaned == [{"userId": "u1"}, {"userId": "u2"}]


def test_redaction_of_an_absent_path_is_not_an_error_but_is_also_not_a_silent_pass():
    """A path that matches nothing must not throw — manifests legitimately declare
    fields that a given response omits. The compensating control is that the path
    SHAPE is validated at manifest load, which is a different test."""
    assert redact({"a": 1}, ["$.customer.ssn"]) == {"a": 1}
    with pytest.raises(EnvelopeError):
        redact({"a": 1}, ["customer.ssn"])
