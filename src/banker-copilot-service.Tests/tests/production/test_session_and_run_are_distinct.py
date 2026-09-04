"""`session` and `run` are two entities, and conflating them is a security bug.

Epic §0.1: a *session* is the banker's conversation; a *run* is one agent
execution within it. The distinction is load-bearing in three places:

* ``seq`` is monotonic and gapless **per run**. If it were per session, two
  concurrent runs would interleave into one counter and a replay could not
  reconstruct either.
* An approval belongs to a run, and re-planning creates a NEW run that supersedes
  the previous approval. Collapse them and "supersede" has nothing to point at.
* Evidence gathered in run N is not automatically evidence for run N+1.

The false pass: a single-run test. With one run per session every per-session
identifier is coincidentally also a per-run identifier and every conflation test
passes. Every case here therefore uses at least two runs.
"""

from __future__ import annotations

import time

from . import service_import  # noqa: F401


def _session(client, headers, objective="review flagged transactions") -> str:
    response = client.post("/api/copilot/sessions", headers=headers, json={"objective": objective})
    assert response.status_code == 201, response.text
    return response.json()["sessionId"]


def _run(client, headers, session_id, intent="review flagged transaction txn_1") -> str:
    response = client.post(
        f"/api/copilot/sessions/{session_id}/runs", headers=headers, json={"intent": intent}
    )
    assert response.status_code == 202, response.text
    return response.json()["runId"]


def _settle(client, headers, run_id, attempts=40):
    for _ in range(attempts):
        body = client.get(f"/api/copilot/runs/{run_id}", headers=headers).json()
        if body.get("status") in ("completed", "failed", "awaiting_approval", "denied"):
            return body
        time.sleep(0.05)
    return client.get(f"/api/copilot/runs/{run_id}", headers=headers).json()


def test_the_two_entities_have_distinct_identifier_namespaces(client, banker_headers):
    session_id = _session(client, banker_headers)
    run_id = _run(client, banker_headers, session_id)

    assert session_id != run_id
    assert session_id.startswith("sess_"), session_id
    assert run_id.startswith("run_"), run_id


def test_a_run_id_is_not_accepted_where_a_session_id_belongs(client, banker_headers):
    """The conflation, tested directly. If the store were keyed on one id space
    a run id would resolve as a session and the ownership check would run against
    the wrong document."""
    session_id = _session(client, banker_headers)
    run_id = _run(client, banker_headers, session_id)

    assert client.get(f"/api/copilot/sessions/{run_id}", headers=banker_headers).status_code == 404
    assert client.get(f"/api/copilot/runs/{session_id}", headers=banker_headers).status_code == 404


def test_one_session_carries_many_runs(client, banker_headers):
    session_id = _session(client, banker_headers)
    first = _run(client, banker_headers, session_id, "review txn_1")
    second = _run(client, banker_headers, session_id, "review txn_2")

    assert first != second
    for run_id in (first, second):
        body = client.get(f"/api/copilot/runs/{run_id}", headers=banker_headers).json()
        assert body["sessionId"] == session_id


def test_seq_is_per_run_and_restarts_for_the_next_run(client, banker_headers):
    """The replay contract. Two runs in one session must each start at 1;
    a shared counter would make the second run's trace start mid-sequence and
    silently unreplayable on its own.
    """
    session_id = _session(client, banker_headers)
    first = _run(client, banker_headers, session_id, "review txn_1")
    _settle(client, banker_headers, first)
    second = _run(client, banker_headers, session_id, "review txn_2")
    _settle(client, banker_headers, second)

    for run_id in (first, second):
        frames = client.get(f"/api/copilot/runs/{run_id}/trace", headers=banker_headers).json()["frames"]
        assert frames, run_id
        sequences = [frame["seq"] for frame in frames]
        assert sequences[0] == 1, f"{run_id} does not start at 1: {sequences[:3]}"
        assert sequences == list(range(1, len(sequences) + 1)), (
            f"{run_id} sequence is not gapless and monotonic: {sequences}"
        )


def test_every_frame_names_both_its_run_and_its_session(client, banker_headers):
    """A session-scoped stream carrying frames from two runs is only
    demultiplexable if each frame says which run it came from."""
    session_id = _session(client, banker_headers)
    first = _run(client, banker_headers, session_id, "review txn_1")
    _settle(client, banker_headers, first)
    second = _run(client, banker_headers, session_id, "review txn_2")
    _settle(client, banker_headers, second)

    for run_id in (first, second):
        frames = client.get(f"/api/copilot/runs/{run_id}/trace", headers=banker_headers).json()["frames"]
        for frame in frames:
            assert frame["runId"] == run_id
            assert frame["sessionId"] == session_id


def test_a_runs_trace_contains_only_that_runs_frames(client, banker_headers):
    """Cross-contamination check. If traces were stored per session, run 2's
    trace would replay run 1's reasoning as its own."""
    session_id = _session(client, banker_headers)
    first = _run(client, banker_headers, session_id, "review txn_1")
    _settle(client, banker_headers, first)
    second = _run(client, banker_headers, session_id, "review txn_2")
    _settle(client, banker_headers, second)

    first_ids = {f["id"] for f in client.get(f"/api/copilot/runs/{first}/trace", headers=banker_headers).json()["frames"]}
    second_ids = {f["id"] for f in client.get(f"/api/copilot/runs/{second}/trace", headers=banker_headers).json()["frames"]}

    assert first_ids and second_ids
    assert not (first_ids & second_ids), "the two runs share frames"


def test_final_seq_is_a_property_of_the_run_not_the_session(client, banker_headers):
    session_id = _session(client, banker_headers)
    first = _run(client, banker_headers, session_id, "review txn_1")
    first_body = _settle(client, banker_headers, first)
    second = _run(client, banker_headers, session_id, "review txn_2")
    second_body = _settle(client, banker_headers, second)

    first_frames = client.get(f"/api/copilot/runs/{first}/trace", headers=banker_headers).json()["frames"]
    second_frames = client.get(f"/api/copilot/runs/{second}/trace", headers=banker_headers).json()["frames"]

    assert first_body["finalSeq"] == first_frames[-1]["seq"]
    assert second_body["finalSeq"] == second_frames[-1]["seq"]


def test_the_stream_is_scoped_to_a_named_run(client, banker_headers):
    """``runId`` selects which run to follow. Without it a second run would tail
    onto the first client's cursor and produce a sequence that goes backwards."""
    session_id = _session(client, banker_headers)
    first = _run(client, banker_headers, session_id, "review txn_1")
    _settle(client, banker_headers, first)
    second = _run(client, banker_headers, session_id, "review txn_2")
    _settle(client, banker_headers, second)

    url = f"/api/copilot/sessions/{session_id}/stream?runId={first}&lastSeq=0"
    with client.stream("GET", url, headers=banker_headers) as response:
        assert response.status_code == 200
        seen = []
        for line in response.iter_lines():
            if line.startswith("data:"):
                import json

                seen.append(json.loads(line[5:]))
            if len(seen) >= 3:
                break

    assert seen, "the replay backlog was empty"
    for frame in seen:
        assert frame["runId"] == first, "the stream served frames from a different run"


def test_a_run_cannot_be_started_in_another_bankers_session(client, banker_headers):
    """Session ownership gates run creation. Otherwise a session id — which
    appears in trace documents and logs — is enough to run an agent as someone
    else."""
    from .conftest import make_token

    session_id = _session(client, banker_headers)
    intruder = {"Authorization": f"Bearer {make_token(user_id='usr_banker_2')}"}

    response = client.post(
        f"/api/copilot/sessions/{session_id}/runs", headers=intruder, json={"intent": "review"}
    )
    assert response.status_code in (403, 404), response.status_code
