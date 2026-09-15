"""`GET /api/copilot/traces` — the offline eval bulk-fetch path (epic #333, issue #374).

`GET /runs/{id}/trace` answers "replay this one run"; eval needs to pull N runs matching a
filter — this endpoint. Same ownership pattern as every other route in `sessions.py`
(`_load_owned_session`), same Cosmos query shape as the existing per-run trace read, and no
path through it that can run without a `sessionId` predicate.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from conftest import judging_assessor, shipped_assessment_limits
from tests.conftest import make_token

from test_api import BANKER, _auth, client  # noqa: F401 - reused fixture + helpers

_TERMINAL_STATUSES = {"completed", "failed", "awaiting_approval", "denied"}


def _start_session_and_run(client: TestClient, objective: str = "x") -> tuple[str, str]:
    session = client.post(
        "/api/copilot/sessions", json={"objective": objective}, headers=_auth(**BANKER)
    ).json()
    run = client.post(
        f"/api/copilot/sessions/{session['sessionId']}/runs", json={}, headers=_auth(**BANKER)
    ).json()
    return session["sessionId"], run["runId"]


def _start_session_and_wait_for_terminal_run(
    client: TestClient, objective: str = "x"
) -> tuple[str, str]:
    """Like ``_start_session_and_run``, but does not return until the run is done emitting.

    A run executes on a background task (``asyncio.create_task`` in ``sessions.py``), so the
    frame count for a run is not stable the instant ``POST /runs`` returns — it is stable once
    the run reaches a terminal status. A caller that needs to snapshot "every frame this run
    will ever produce" and compare it against a later, filtered snapshot must wait here first,
    or the two snapshots are racing the same background task rather than comparing a fixed set.
    """
    session_id, run_id = _start_session_and_run(client, objective)
    for _ in range(200):
        status = client.get(
            f"/api/copilot/runs/{run_id}", headers=_auth(**BANKER)
        ).json().get("status")
        if status in _TERMINAL_STATUSES:
            break
        time.sleep(0.01)
    else:
        raise AssertionError(f"run {run_id} did not reach a terminal status in time")
    return session_id, run_id


def test_missing_session_id_is_rejected_not_defaulted_to_unscoped(client):
    """FastAPI's own required-query-param validation is the first line: there must be no way
    to reach the sink without a sessionId at all."""
    response = client.get("/api/copilot/traces", headers=_auth(**BANKER))
    assert response.status_code == 422


def test_bulk_query_returns_every_frame_for_the_session(client):
    session_id, run_id = _start_session_and_run(client)

    response = client.get(
        "/api/copilot/traces", params={"sessionId": session_id}, headers=_auth(**BANKER)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sessionId"] == session_id
    assert body["frameCount"] == len(body["frames"])
    assert body["frames"], "the run just started must have left at least a run.started frame"
    assert all(frame["sessionId"] == session_id for frame in body["frames"])
    assert {frame["runId"] for frame in body["frames"]} == {run_id}


def test_bulk_query_spans_every_run_in_the_session():
    """Two runs in one session must both come back — that is the entire point of a bulk
    fetch over the single-run trace endpoint."""
    import importlib

    import app.main as main_module

    importlib.reload(main_module)
    with TestClient(main_module.app) as c:
        session = c.post(
            "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**BANKER)
        ).json()
        session_id = session["sessionId"]
        first = c.post(
            f"/api/copilot/sessions/{session_id}/runs", json={}, headers=_auth(**BANKER)
        ).json()
        second = c.post(
            f"/api/copilot/sessions/{session_id}/runs", json={}, headers=_auth(**BANKER)
        ).json()

        body = c.get(
            "/api/copilot/traces", params={"sessionId": session_id}, headers=_auth(**BANKER)
        ).json()
        assert {first["runId"], second["runId"]} <= {f["runId"] for f in body["frames"]}


def test_kind_filter_returns_only_that_kind(client):
    session_id, _run_id = _start_session_and_run(client)

    body = client.get(
        "/api/copilot/traces",
        params={"sessionId": session_id, "kind": "run.started"},
        headers=_auth(**BANKER),
    ).json()
    assert body["frames"]
    assert {frame["kind"] for frame in body["frames"]} == {"run.started"}


def test_unknown_kind_is_a_422_not_a_silently_empty_result(client):
    session_id, _run_id = _start_session_and_run(client)

    response = client.get(
        "/api/copilot/traces",
        params={"sessionId": session_id, "kind": "not.a.real.kind"},
        headers=_auth(**BANKER),
    )
    assert response.status_code == 422


def test_since_excludes_frames_before_it(client):
    session_id, _run_id = _start_session_and_wait_for_terminal_run(client)
    all_frames = client.get(
        "/api/copilot/traces", params={"sessionId": session_id}, headers=_auth(**BANKER)
    ).json()["frames"]
    assert len(all_frames) >= 2, "need at least two frames to prove `since` excludes anything"
    cutoff = all_frames[-1]["ts"]

    filtered = client.get(
        "/api/copilot/traces",
        params={"sessionId": session_id, "since": cutoff},
        headers=_auth(**BANKER),
    ).json()["frames"]
    assert all(frame["ts"] >= cutoff for frame in filtered)
    assert len(filtered) < len(all_frames)


def test_malformed_since_is_a_422_not_a_query_that_silently_matches_everything(client):
    session_id, _run_id = _start_session_and_run(client)

    response = client.get(
        "/api/copilot/traces",
        params={"sessionId": session_id, "since": "not-a-timestamp"},
        headers=_auth(**BANKER),
    )
    assert response.status_code == 422


def test_another_bankers_session_is_not_readable_here_either(client):
    session_id, _run_id = _start_session_and_run(client)

    response = client.get(
        "/api/copilot/traces",
        params={"sessionId": session_id},
        headers=_auth(user_id="usr_other_banker", effective_roles=["banker"]),
    )
    assert response.status_code == 404


def test_an_unknown_session_id_is_404_not_an_empty_scan(client):
    response = client.get(
        "/api/copilot/traces", params={"sessionId": "sess_does_not_exist"}, headers=_auth(**BANKER)
    )
    assert response.status_code == 404
