"""End-to-end API behaviour: the app boots fail-closed, gates on banking role, and streams."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_token


@pytest.fixture
def client(monkeypatch):
    import importlib

    import app.main as main_module

    importlib.reload(main_module)
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth(**kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(**kwargs)}"}


BANKER = {"effective_roles": ["banker"]}
SUPERVISOR = {"role": "supervisor", "effective_roles": ["supervisor", "banker"]}
ADMIN = {"user_id": "usr_admin", "role": "admin", "effective_roles": ["admin"]}
CUSTOMER = {"user_id": "usr_cust", "role": "user", "effective_roles": ["user"]}


# ------------------------------------------------------------------ health ----


def test_readyz_reports_zero_write_tools(client):
    response = client.get("/readyz")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ready"
    assert body["writeTools"] == 0
    assert body["methods"] == ["GET"]
    assert body["readMethodAllowlist"] == ["GET"]
    # Dual-mode decisions are reported, not inferred. Phase 1 lost ten minutes to a service
    # that silently chose an Entra credential path and said nothing.
    assert body["credentialMode"] in {"entra", "simple"}
    assert body["storeMode"] == "memory"
    assert body["plannerMode"] in {"foundry", "deterministic"}


def test_healthz_needs_no_token(client):
    assert client.get("/healthz").status_code == 200


# -------------------------------------------------------------------- auth ----


def test_missing_token_is_401(client):
    assert client.post("/api/copilot/sessions", json={"objective": "x"}).status_code == 401


def test_customer_token_cannot_reach_the_harness(client):
    """A retail customer satisfying a banker slot is exactly the Phase 1 escalation."""
    response = client.post(
        "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**CUSTOMER)
    )
    assert response.status_code == 403


def test_admin_token_cannot_reach_the_harness(client):
    """Platform power is not banking authority — admin implies neither banker nor supervisor."""
    response = client.post(
        "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**ADMIN)
    )
    assert response.status_code == 403


def test_token_without_effective_roles_is_refused(client):
    """The harness will not re-derive the ladder from the flat role claim. A second expansion
    is a second place for the role model to be wrong."""
    response = client.post(
        "/api/copilot/sessions",
        json={"objective": "x"},
        headers={"Authorization": f"Bearer {make_token(role='banker')}"},
    )
    assert response.status_code == 403


def test_supervisor_reaches_the_harness_through_implied_banker(client):
    response = client.post(
        "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**SUPERVISOR)
    )
    assert response.status_code == 201


# ------------------------------------------------------------------- tools ----


def test_tools_endpoint_advertises_no_write_tools(client):
    body = client.get("/api/copilot/tools", headers=_auth(**BANKER)).json()

    assert body["writeTools"] == []
    assert body["writeAffordance"]["toolId"] == "propose_action"
    assert {tool["method"] for tool in body["readTools"]} == {"GET"}
    assert "propose_action" not in {tool["toolId"] for tool in body["readTools"]}


def test_tool_descriptions_never_leak_a_resolved_upstream_url(client):
    body = client.get("/api/copilot/tools", headers=_auth(**BANKER)).json()
    serialized = json.dumps(body)
    assert "http://" not in serialized


# ---------------------------------------------------------------- sessions ----


def test_session_and_run_are_distinct_entities(client):
    """A session owns the conversation; a run owns one planner execution and its seq counter.
    Two runs in one session must be independently addressable."""
    session = client.post(
        "/api/copilot/sessions",
        json={"objective": "Review the flagged wire", "context": {"accountId": "acc_11"}},
        headers=_auth(**BANKER),
    ).json()
    session_id = session["sessionId"]

    first = client.post(
        f"/api/copilot/sessions/{session_id}/runs", json={}, headers=_auth(**BANKER)
    ).json()
    second = client.post(
        f"/api/copilot/sessions/{session_id}/runs", json={}, headers=_auth(**BANKER)
    ).json()

    assert first["runId"] != second["runId"]
    assert first["sessionId"] == second["sessionId"] == session_id

    fetched = client.get(f"/api/copilot/sessions/{session_id}", headers=_auth(**BANKER)).json()
    assert set(fetched["runIds"]) == {first["runId"], second["runId"]}


def test_another_bankers_session_is_not_readable(client):
    session = client.post(
        "/api/copilot/sessions", json={"objective": "mine"}, headers=_auth(**BANKER)
    ).json()

    response = client.get(
        f"/api/copilot/sessions/{session['sessionId']}",
        headers=_auth(user_id="usr_other_banker", effective_roles=["banker"]),
    )
    assert response.status_code == 404


def test_propose_route_rejects_cosigner_id_at_the_edge(client):
    session = client.post(
        "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**BANKER)
    ).json()

    response = client.post(
        f"/api/copilot/sessions/{session['sessionId']}/propose",
        json={
            "actionId": "transaction.flag.review",
            "payload": {"transactionId": "tx_1"},
            "cosignerId": "usr_supervisor_1",
        },
        headers=_auth(**BANKER),
    )
    assert response.status_code == 422


# ------------------------------------------------------- planner + stream ----


def test_planner_gathers_evidence_then_proposes_and_streams_the_trace(client, monkeypatch):
    """The §1.3 narrative in miniature: read tools run, an approval is required, nothing
    executes. The upstreams are mocked; the harness's own behaviour is not."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/authority/policy":
            return httpx.Response(
                200,
                json={
                    "policyVersion": "pv1:abcd",
                    "actions": [
                        {
                            "id": "transaction.flag.review",
                            "displayName": "Clear or confirm a flagged transaction",
                            "baseRung": "L1",
                            "agentMayPropose": True,
                            "requiredEvidence": [
                                "get_flagged_transaction",
                                "list_account_transactions",
                            ],
                        }
                    ],
                },
            )
        if path == "/api/authority/approvals":
            return httpx.Response(
                201,
                json={
                    "id": "apr_1",
                    "status": "pending",
                    "requiredRung": "L2",
                    "baseRung": "L1",
                    "requiredSigners": 2,
                    "payloadHash": "sha256:abc",
                    "policyVersion": "pv1:abcd",
                },
            )
        if path.startswith("/api/admin/flagged-transactions/"):
            return httpx.Response(
                200,
                json={
                    "transactionId": "tx_1",
                    "amount": 250000,
                    "customer": {"ssn": "123-45-6789", "dateOfBirth": "1980-01-01"},
                },
            )
        if path.startswith("/api/transactions/account/"):
            return httpx.Response(200, json=[{"id": "tx_0", "amount": 20}])
        return httpx.Response(404, json={"error": "not_found"})

    client.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    from app.planner.loop import Planner
    from app.tools.executor import ToolExecutor
    from app.tools.propose import AuthorityClient

    registry = client.app.state.registry
    client.app.state.executor = ToolExecutor(registry, client.app.state.http)
    client.app.state.authority = AuthorityClient(
        "http://authority-service:8080", client.app.state.http, 8000
    )
    client.app.state.planner = Planner(
        registry=registry,
        executor=client.app.state.executor,
        authority=client.app.state.authority,
        max_iterations=12,
    )

    session = client.post(
        "/api/copilot/sessions",
        json={
            "objective": "Review the flagged wire on acc_11",
            "context": {"txId": "tx_1", "accountId": "acc_11"},
        },
        headers=_auth(**BANKER),
    ).json()

    run = client.post(
        f"/api/copilot/sessions/{session['sessionId']}/runs",
        json={
            "actionId": "transaction.flag.review",
            "payload": {"transactionId": "tx_1", "decision": "cleared", "note": "reviewed"},
            "facts": {"amount": 250000},
        },
        headers=_auth(**BANKER),
    ).json()

    trace = client.get(
        f"/api/copilot/runs/{run['runId']}/trace", headers=_auth(**BANKER)
    ).json()
    frames = trace["frames"]

    kinds = [frame["kind"] for frame in frames]
    assert kinds[0] == "run.started"
    assert kinds[-1] == "run.done"

    # Set membership, not a count: names what is missing when this regresses.
    assert {"plan.proposed", "tool.started", "tool.completed", "approval.required"} <= set(kinds)

    # seq is gapless from 1.
    assert [frame["seq"] for frame in frames] == list(range(1, len(frames) + 1))

    # finalSeq counts the run.done frame itself.
    done = frames[-1]
    assert done["payload"]["finalSeq"] == done["seq"]

    # The approval frame COPIES policyVersion from the approval — never re-derived at emit.
    approval = next(f for f in frames if f["kind"] == "approval.required")
    assert approval["payload"]["policyVersion"] == "pv1:abcd"
    assert approval["payload"]["requiredRung"] == "L2"

    # Redaction happened at emit, so PII is not sitting in the persisted trace.
    serialized = json.dumps(frames)
    assert "123-45-6789" not in serialized
    assert "[redacted]" in serialized

    # Nothing executed. The harness proposed and stopped.
    assert "approval.terminal" not in kinds


def test_stream_replays_the_trace_over_sse(client, monkeypatch):
    session = client.post(
        "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**BANKER)
    ).json()
    run = client.post(
        f"/api/copilot/sessions/{session['sessionId']}/runs", json={}, headers=_auth(**BANKER)
    ).json()

    with client.stream(
        "GET",
        f"/api/copilot/sessions/{session['sessionId']}/stream?runId={run['runId']}",
        headers=_auth(**BANKER),
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        # nginx buffering is off at the gateway; this header is the same instruction for any
        # other proxy in front of us.
        assert response.headers["x-accel-buffering"] == "no"

        body = ""
        for chunk in response.iter_text():
            body += chunk
            if "event: run.done" in body:
                break

    assert "event: run.started" in body
    assert "event: run.done" in body
    # `id:` carries the SEQ, because that is what the client sends back as Last-Event-ID.
    # If it carried the envelope id instead, resume would be uninterpretable and the client
    # would silently restart the run from zero.
    seq_ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    assert len(seq_ids) >= 2
    assert seq_ids == sorted(seq_ids)
    assert len(set(seq_ids)) == len(seq_ids)


def test_stream_for_an_unknown_run_is_404(client):
    """A named run that does not exist is an error. A session with no run YET is not."""
    session = client.post(
        "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**BANKER)
    ).json()
    response = client.get(
        f"/api/copilot/sessions/{session['sessionId']}/stream?runId=run_nope",
        headers=_auth(**BANKER),
    )
    assert response.status_code == 404


def test_stream_attached_before_any_run_stays_open_and_heartbeats(client):
    """The UI opens the stream and THEN dispatches the turn.

    Answering 404 to that ordinary race would trip the client's reconnect backoff and hide
    the opening frames of the very run it attached to watch. The connection must be honest
    about being alive-and-waiting instead.
    """
    session = client.post(
        "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**BANKER)
    ).json()
    with client.stream(
        "GET",
        f"/api/copilot/sessions/{session['sessionId']}/stream",
        headers=_auth(**BANKER),
    ) as response:
        assert response.status_code == 200
        body = ""
        for chunk in response.iter_text():
            body += chunk
            if "event: heartbeat" in body:
                break
    assert "event: heartbeat" in body


def test_stream_rejects_a_non_numeric_last_event_id(client):
    """The resume cursor is the seq. A cursor we cannot interpret must not be treated as
    'start from the beginning' — that silently replays the run as duplicates."""
    session = client.post(
        "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**BANKER)
    ).json()
    response = client.get(
        f"/api/copilot/sessions/{session['sessionId']}/stream",
        headers={**_auth(**BANKER), "Last-Event-ID": "evt_not_a_seq"},
    )
    assert response.status_code == 400


def test_artifacts_produced_by_a_run_are_readable_after_the_stream_closes(client):
    """A streamed artifact the banker cannot retrieve after a reload is worse than none:
    the pane renders empty, and nothing distinguishes that from 'no artifacts'."""
    session = client.post(
        "/api/copilot/sessions", json={"objective": "review"}, headers=_auth(**BANKER)
    ).json()
    run = client.post(
        f"/api/copilot/sessions/{session['sessionId']}/runs",
        json={"message": "review flagged transactions"},
        headers=_auth(**BANKER),
    ).json()

    with client.stream(
        "GET",
        f"/api/copilot/sessions/{session['sessionId']}/stream?runId={run['runId']}",
        headers=_auth(**BANKER),
    ) as response:
        body = ""
        for chunk in response.iter_text():
            body += chunk
            if "event: run.done" in body:
                break
    assert "event: artifact.created" in body

    listed = client.get(
        f"/api/copilot/runs/{run['runId']}/artifacts", headers=_auth(**BANKER)
    )
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["sessionId"] == session["sessionId"]
    assert len(payload["artifacts"]) >= 1, "the run streamed an artifact but persisted none"


def test_another_banker_cannot_list_a_runs_artifacts(client):
    session = client.post(
        "/api/copilot/sessions", json={"objective": "mine"}, headers=_auth(**BANKER)
    ).json()
    run = client.post(
        f"/api/copilot/sessions/{session['sessionId']}/runs",
        json={"message": "review flagged transactions"},
        headers=_auth(**BANKER),
    ).json()

    response = client.get(
        f"/api/copilot/runs/{run['runId']}/artifacts",
        headers=_auth(user_id="usr_other_banker", effective_roles=["banker"]),
    )
    assert response.status_code == 404
