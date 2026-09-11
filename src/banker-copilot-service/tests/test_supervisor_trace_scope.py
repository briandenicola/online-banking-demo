"""Trace SCOPE for the blind supervisor (epic §6.4, check 4.3).

The sibling suites prove the supervisor is blind at *construction* time:
``test_supervisor_blind_construction.py`` pins the builder's signature, and
``test_supervisor_boundary.py`` pins the caller by capturing the exact ``SupervisorInput``
during a real run. Neither of them says anything about the PERSISTED TRACE, and that is the
question check 4.3 actually asks: ``approval.updated`` combines the primary's assessment and the
supervisor's into ONE document (``fanout.py`` — ``updated_approval["agentAssessment"]`` carries
both ``primary`` and ``supervisor``), and ``CopilotEventEnvelope.to_document`` persists it whole.

That combined document is legitimate — it is the audit record a human reads after the fact — but
it is legitimate for exactly one reason: **it is written strictly after the supervisor has already
spoken.** Today that ordering is guaranteed by nothing but statement order inside one function. A
future edit that emitted a combined "pending" frame at spawn time, or that gave the supervisor's
own child run a copy of the primary's assessment "for context", would relocate the primary's
reasoning to BEFORE the second opinion exists — and every existing test would stay green, because
none of them look at ordering and none of them look at the child run's trace at all.

So this file holds three properties that are currently correct and unheld:

1. The combined audit frame is written AFTER the supervisor's verdict frame (post-hoc, not live).
2. The supervisor's OWN persisted trace (``<run>::supervisor``) contains nothing from the primary.
   This is the document a future "give the supervisor context" edit would most naturally poison,
   and it is the one document no other test reads.
3. A run's trace is readable ONLY by the banker who owns the session. ``get_run_trace`` calls
   ``_load_owned_session``, but no test proves it: that line could be deleted with the whole suite
   green, and every banker could then read every other banker's full reasoning trace.

The harness is reused from ``test_supervisor_boundary`` on purpose — driving the REAL planner and
fan-out is what makes these assertions about the shipped path rather than about a mock.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_supervisor_boundary import (
    PRIMARY_SENTINEL,
    _drive,
    _frames,
    _SpyDecider,
)

SUPERVISOR_RUN_ID = "run_1::supervisor"


def _combined_frames(frames) -> list[dict]:
    """Every persisted frame that holds the primary's and the supervisor's opinions at once."""
    combined = []
    for frame in frames:
        assessment = (frame.get("payload") or {}).get("approval", {}).get("agentAssessment") or {}
        if "primary" in assessment and "supervisor" in assessment:
            combined.append(frame)
    return combined


@pytest.mark.asyncio
async def test_the_combined_audit_frame_is_written_after_the_supervisor_has_spoken():
    """§6.4 check 4.3. The one document holding both opinions is a POST-HOC audit record.

    Blindness is a property of the moment the opinion is formed, not of the filing cabinet it is
    later stored in. This asserts the ordering that makes the combined document defensible: the
    supervisor's verdict frame (``subagent.completed``) is persisted at a strictly lower seq than
    any frame carrying both opinions. Regression this prevents: emitting a combined frame early
    (a "pending" approval.updated at spawn time, say), which would place the primary's assessment
    in the trace BEFORE the second opinion exists and make "independent" a claim about ordering
    that the trace itself contradicts.
    """
    runs, _ = await _drive("L2", _SpyDecider())
    frames = _frames(runs, "run_1")

    verdict = [f for f in frames if f["kind"] == "subagent.completed"]
    assert verdict, "the supervisor never reported a verdict — the L2 fan-out did not fire"
    verdict_seq = verdict[0]["seq"]

    combined = _combined_frames(frames)
    # Anti-vacuous: there really IS a document holding both opinions. If this list were empty the
    # ordering assertion below would pass by describing nothing.
    assert combined, "no frame carried both opinions — the scan has no subject and proves nothing"

    for frame in combined:
        assert frame["seq"] > verdict_seq, (
            f"{frame['kind']} (seq {frame['seq']}) combined the primary's assessment with the "
            f"supervisor's at or before the supervisor's own verdict (seq {verdict_seq}). The "
            "combined record is only defensible as a post-hoc artifact."
        )


@pytest.mark.asyncio
async def test_the_supervisors_own_trace_carries_nothing_from_the_primary():
    """The supervisor's child run is its own persisted document, and it must stay clean.

    ``<run>::supervisor`` is a separate trace with its own partition key (``/runId``). No other
    test reads it. Regression this prevents: an edit that seeds the supervisor's run with the
    primary's plan or assessment "so the trace makes sense to a reviewer" — which would put the
    primary's reasoning inside the supervisor's own record, the one place it must never be, and
    would be invisible to every parent-run scan.
    """
    runs, _ = await _drive("L2", _SpyDecider())

    child = _frames(runs, SUPERVISOR_RUN_ID)
    # Anti-vacuous: the supervisor really did write a trace, so an absent sentinel is a result.
    assert child, "the supervisor persisted no trace of its own — nothing was scanned"
    assert any(f["kind"] == "tool.completed" for f in child), (
        "the supervisor's trace records no independent read — it did not do its own work"
    )

    for frame in child:
        assert PRIMARY_SENTINEL not in json.dumps(frame), (
            f"the supervisor's own trace frame {frame['kind']} carries the primary's sentinel"
        )
        assert not frame["kind"].startswith("approval."), (
            f"the supervisor's own trace carries {frame['kind']}; the approval — which holds the "
            "primary's assessment — belongs to the parent run, never to the blind subagent"
        )

    # And the parent trace DID carry it, proving the sentinel was live throughout this run.
    assert any(PRIMARY_SENTINEL in json.dumps(f) for f in _frames(runs, "run_1"))


# ------------------------------------------------------- who may read a trace ----


@pytest.fixture
def client(monkeypatch):
    import importlib

    import app.main as main_module

    importlib.reload(main_module)
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth(**kwargs) -> dict[str, str]:
    from tests.conftest import make_token

    return {"Authorization": f"Bearer {make_token(**kwargs)}"}


def test_another_banker_cannot_read_a_runs_trace(client):
    """A trace is the fullest record of a run: the plan, every read value, both assessments.

    ``get_run_trace`` resolves the run and then calls ``_load_owned_session``, which 404s unless
    the caller owns the session. That ownership check was held by no test — it could have been
    deleted with the suite green, and any authenticated banker could then read every other
    banker's complete reasoning trace. 404 rather than 403 is deliberate: the existence of
    another banker's run is not this caller's business.
    """
    session = client.post(
        "/api/copilot/sessions", json={"objective": "mine"}, headers=_auth(effective_roles=["banker"])
    ).json()
    run = client.post(
        f"/api/copilot/sessions/{session['sessionId']}/runs",
        json={"message": "review flagged transactions"},
        headers=_auth(effective_roles=["banker"]),
    ).json()

    # Anti-vacuous: the owner CAN read it, so the 404 below is an authorization result and not a
    # route that is simply broken or a run that never existed.
    owned = client.get(
        f"/api/copilot/runs/{run['runId']}/trace", headers=_auth(effective_roles=["banker"])
    )
    assert owned.status_code == 200

    intruder = client.get(
        f"/api/copilot/runs/{run['runId']}/trace",
        headers=_auth(user_id="usr_other_banker", effective_roles=["banker"]),
    )
    assert intruder.status_code == 404

    # A supervisor role is a co-signing authority, not a reader of other people's traces.
    other_role = client.get(
        f"/api/copilot/runs/{run['runId']}/trace",
        headers=_auth(user_id="usr_other_super", role="supervisor", effective_roles=["supervisor", "banker"]),
    )
    assert other_role.status_code == 404
