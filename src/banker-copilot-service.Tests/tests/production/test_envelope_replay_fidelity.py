"""`CopilotEventEnvelope` replay fidelity — epic §8.0.

One schema serves two consumers: the live UI stream and the offline eval replay
(#333). §8.0 calls itself "the contract of record". The failure mode it exists to
prevent is drift — the stream gains a field, or reorders, or drops a frame the
sink never saw, and the evaluation harness is then scoring a transcript that
never happened. Nobody notices, because both halves keep working.

What a false pass looks like here, and it is the easy mistake: comparing the
replay against the same in-memory list the live stream was read from. That
compares a list to itself. Everything below reads the live sequence off the
**wire** (the SSE response body) and the replay out of the **trace endpoint**,
which is the persisted document, and compares those two.
"""

from __future__ import annotations

import json
import time

import pytest  # noqa: F401  (fixtures below are plain functions; pytest is the runner)

from . import service_import  # noqa: F401

from app.events.envelope import CopilotEventEnvelope


def _session(client, headers) -> str:
    return client.post(
        "/api/copilot/sessions", headers=headers, json={"objective": "review"}
    ).json()["sessionId"]


def _run_and_wait(client, headers, session_id, intent="review flagged transaction txn_1") -> str:
    run_id = client.post(
        f"/api/copilot/sessions/{session_id}/runs", headers=headers, json={"intent": intent}
    ).json()["runId"]
    for _ in range(40):
        status = client.get(f"/api/copilot/runs/{run_id}", headers=headers).json().get("status")
        if status in ("completed", "failed", "awaiting_approval", "denied"):
            break
        time.sleep(0.05)
    return run_id


def _read_stream(client, headers, session_id, run_id):
    """Read the live wire representation to completion.

    A finished run's stream closes rather than idling, which is what makes this
    terminate — and is itself part of §4.6.
    """
    frames = []
    url = f"/api/copilot/sessions/{session_id}/stream?runId={run_id}&lastSeq=0"
    with client.stream("GET", url, headers=headers) as response:
        assert response.status_code == 200
        event_name = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:") and event_name != "heartbeat":
                frames.append(json.loads(line[5:]))
    return frames


def _replay(client, headers, run_id):
    body = client.get(f"/api/copilot/runs/{run_id}/trace", headers=headers).json()
    return body["frames"], body


@pytest.fixture
def executed_run(client, banker_headers):
    session_id = _session(client, banker_headers)
    run_id = _run_and_wait(client, banker_headers, session_id)
    return session_id, run_id


def test_a_run_actually_produces_frames(client, banker_headers, executed_run):
    """Anti-vacuous, and the most important test in the file.

    Two empty sequences are equal. Every fidelity assertion below is trivially
    satisfied by a run that emitted nothing, so the sequence must first be shown
    to be non-trivial: more than one frame, more than one kind.
    """
    session_id, run_id = executed_run
    live = _read_stream(client, banker_headers, session_id, run_id)
    replayed, _ = _replay(client, banker_headers, run_id)

    assert len(live) >= 3, f"only {len(live)} live frames — fidelity would pass vacuously"
    assert len({f["kind"] for f in live}) >= 3, "a single-kind trace exercises nothing"
    assert replayed, "the persisted trace is empty"


def test_replay_reproduces_the_live_sequence_exactly(client, banker_headers, executed_run):
    """The eval contract. Same frames, same order, same identities."""
    session_id, run_id = executed_run
    live = _read_stream(client, banker_headers, session_id, run_id)
    replayed, _ = _replay(client, banker_headers, run_id)

    assert [f["seq"] for f in replayed] == [f["seq"] for f in live]
    assert [f["kind"] for f in replayed] == [f["kind"] for f in live]
    assert [f["id"] for f in replayed] == [f["id"] for f in live]


def test_replay_reproduces_the_payloads_not_merely_the_shape(client, banker_headers, executed_run):
    """Kinds and sequence numbers matching while payloads diverge is exactly the
    drift this is here to catch — an evaluator reads the payloads."""
    session_id, run_id = executed_run
    live = _read_stream(client, banker_headers, session_id, run_id)
    replayed, _ = _replay(client, banker_headers, run_id)

    by_seq = {f["seq"]: f for f in replayed}
    for frame in live:
        stored = by_seq[frame["seq"]]
        assert stored["payload"] == frame["payload"], (
            f"seq {frame['seq']} ({frame['kind']}) differs between the live stream and the "
            "persisted trace"
        )


def test_the_persisted_document_is_a_superset_of_the_wire_frame(client, banker_headers, executed_run):
    """§8.0's actual relationship: the document may carry storage concerns
    (partition key, ttl) the wire does not, but it may never carry LESS.

    A field the UI renders that is not persisted is a field the evaluator cannot
    see — the transcript and the thing the banker was shown would differ.
    """
    session_id, run_id = executed_run
    live = _read_stream(client, banker_headers, session_id, run_id)
    replayed, _ = _replay(client, banker_headers, run_id)
    by_seq = {f["seq"]: f for f in replayed}

    for frame in live:
        missing = set(frame) - set(by_seq[frame["seq"]])
        assert not missing, f"wire fields absent from the persisted document: {sorted(missing)}"


def test_the_envelope_class_itself_keeps_document_a_superset_of_wire():
    """Structural, so it holds for kinds this run happened not to emit.

    The behavioural test above only covers the frames one scripted run produced.
    A kind that appears in an approval path would go unchecked.
    """
    envelope = CopilotEventEnvelope(
        id="evt_1",
        seq=1,
        run_id="run_1",
        session_id="sess_1",
        kind="run.started",
        ts="2026-01-01T00:00:00Z",
        payload={"a": 1},
    )
    wire = envelope.to_wire()
    document = envelope.to_document()

    assert set(wire) <= set(document), sorted(set(wire) - set(document))
    for key in wire:
        assert document[key] == wire[key], key


def test_sequence_numbers_are_gapless_in_both_representations(client, banker_headers, executed_run):
    """A gap in the replay is a frame that was streamed and never stored. The
    UI looked complete; the transcript is not."""
    session_id, run_id = executed_run
    live = _read_stream(client, banker_headers, session_id, run_id)
    replayed, body = _replay(client, banker_headers, run_id)

    for label, frames in (("live", live), ("replayed", replayed)):
        sequences = [f["seq"] for f in frames]
        assert sequences == list(range(1, len(sequences) + 1)), f"{label}: {sequences}"

    assert body["frameCount"] == len(replayed)


def test_the_trace_declares_whether_it_is_trustworthy(client, banker_headers, executed_run):
    """`traceDegraded` is the honest answer to "persistence failed mid-run".

    Without it a short trace is indistinguishable from a short run, and #333
    would score a truncated transcript as a complete one.
    """
    _, run_id = executed_run
    _, body = _replay(client, banker_headers, run_id)

    assert "traceDegraded" in body
    assert body["traceDegraded"] is False, (
        "this run persisted cleanly; a true value here means frames are missing"
    )


def test_resuming_from_a_cursor_returns_the_same_frames_as_a_full_read(
    client, banker_headers, executed_run
):
    """Reconnection must not perturb the sequence. If resume re-numbered or
    re-emitted, a client that reconnected once would hold a different transcript
    from one that never dropped — and only one of them can match the trace.
    """
    session_id, run_id = executed_run
    full = _read_stream(client, banker_headers, session_id, run_id)
    cutoff = full[1]["seq"]

    resumed = []
    url = f"/api/copilot/sessions/{session_id}/stream?runId={run_id}&lastSeq={cutoff}"
    with client.stream("GET", url, headers=banker_headers) as response:
        assert response.status_code == 200
        event_name = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:") and event_name != "heartbeat":
                resumed.append(json.loads(line[5:]))

    # Strictly increasing, or "the same frames" is being satisfied by the same
    # frames twice — which is how F2-6 hides inside an equality assertion.
    sequences = [f["seq"] for f in resumed]
    assert sequences == sorted(set(sequences)), f"the resumed stream repeats frames: {sequences}"
    assert resumed == [f for f in full if f["seq"] > cutoff]
