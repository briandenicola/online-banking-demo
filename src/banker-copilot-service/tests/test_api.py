"""End-to-end API behaviour: the app boots fail-closed, gates on banking role, and streams."""

from __future__ import annotations

import json

import httpx
import pytest

from conftest import judging_assessor, shipped_assessment_limits
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
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
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


async def _asgi_call(app, method, path, headers, body=b"", first_chunk_timeout=None):
    """Drive the ASGI app directly and time the first body chunk.

    `TestClient` cannot answer this question: it buffers the whole response inside the
    portal and only then builds an httpx object, so every "streamed" chunk appears to
    arrive at completion time. Time-to-first-byte is exactly the quantity this defect is
    about, so the measurement has to happen at the ASGI boundary, which is also the layer
    uvicorn writes the status line from.

    Returns `(status, headers, seconds_to_first_chunk, first_chunk)`; the latency is
    ``None`` if no chunk arrived within `first_chunk_timeout`.
    """
    import time

    import anyio

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "path": path.split("?", 1)[0],
        "raw_path": path.split("?", 1)[0].encode(),
        "query_string": path.split("?", 1)[1].encode() if "?" in path else b"",
        "root_path": "",
        "scheme": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "state": {},
    }

    sent = False
    captured: dict = {"headers": {}}
    first_chunk = anyio.Event()
    started = time.monotonic()

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # Never disconnect on our own: a disconnect would end the stream and make a slow
        # server look like a finished one.
        await anyio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
            captured["headers"] = {
                k.decode().lower(): v.decode() for k, v in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            chunk = message.get("body", b"")
            if chunk and "chunk" not in captured:
                captured["chunk"] = chunk
                captured["latency"] = time.monotonic() - started
                first_chunk.set()
            if not message.get("more_body", False) and not first_chunk.is_set():
                first_chunk.set()

    # Spawned through anyio, not `asyncio.ensure_future`: Starlette's `is_disconnected`
    # opens an anyio cancel scope, and a raw asyncio task is not registered with anyio's
    # task-state store, so it blows up before the code under test ever runs.
    async with anyio.create_task_group() as tg:
        tg.start_soon(app, scope, receive, send)
        with anyio.move_on_after(first_chunk_timeout if first_chunk_timeout else 3600):
            await first_chunk.wait()
        tg.cancel_scope.cancel()

    return (
        captured.get("status"),
        captured["headers"],
        captured.get("latency"),
        captured.get("chunk", b""),
    )


async def _open_stream_and_time_first_frame(asgi_app):
    auth = _auth(**BANKER)
    async with asgi_app.router.lifespan_context(asgi_app):
        status, _, _, created = await _asgi_call(
            asgi_app,
            "POST",
            "/api/copilot/sessions",
            {**auth, "content-type": "application/json"},
            body=json.dumps({"objective": "x"}).encode(),
        )
        assert status == 201, created
        session_id = json.loads(created)["sessionId"]

        return await _asgi_call(
            asgi_app,
            "GET",
            f"/api/copilot/sessions/{session_id}/stream",
            auth,
            first_chunk_timeout=4.0,
        )


def test_stream_flushes_its_first_frame_without_waiting_a_heartbeat(monkeypatch):
    """A session with no run yet must produce a frame AT ONCE, not one heartbeat later.

    The client verifies the connection on its first frame and gates approval signing on that
    verification. Any wait performed before the handler returns — or before the generator's
    first yield — withholds the status line and the frame for a whole heartbeat interval, so
    the client reads a healthy server as a dead one and greys out signing. The heartbeat here
    is deliberately long, so "flushed immediately" and "waited a heartbeat" are far apart and
    cannot be mistaken for each other.

    The whole measurement runs inside a blocking portal, the way `TestClient` runs its app:
    Starlette's `is_disconnected` opens an anyio cancel scope, and anyio will not honour one
    in a task it does not own.
    """
    import importlib

    import anyio.from_thread

    monkeypatch.setenv("COPILOT_SSE_HEARTBEAT_SECONDS", "10")

    import app.main as main_module

    importlib.reload(main_module)

    with anyio.from_thread.start_blocking_portal("asyncio") as portal:
        status, headers, latency, chunk = portal.call(
            _open_stream_and_time_first_frame, main_module.app
        )

    assert status == 200, (
        "no `http.response.start` was sent within 4s: the status line itself is being "
        "withheld, which is what the client reads as a connection that never opened"
    )
    assert headers["content-type"].startswith("text/event-stream")
    assert latency is not None, (
        "no frame arrived within 4s against a 10s heartbeat: the stream is waiting before it "
        "flushes, so the client cannot verify the connection and signing stays disabled"
    )
    assert latency < 2.0, f"the first frame took {latency:.2f}s against a 10s heartbeat"
    assert b"event: heartbeat" in chunk, (
        "the first frame must be a heartbeat the client understands, not an empty flush"
    )


def test_stream_still_answers_409_when_the_cursor_fell_out_of_the_replay_window(monkeypatch):
    """Removing the pre-flight wait must not cost us the resync guarantee.

    The 409 is what stops a client being handed a trace with a hole in it that looks
    complete. It is reached whenever a stream exists for the request — the `runId` lookup and
    `latest_for_session` both still run before it, and only the *waiting* moved into the
    generator. A run whose replay window has rolled past the cursor must still be refused up
    front rather than silently resumed from the wrong place.
    """
    import importlib

    monkeypatch.setenv("COPILOT_SSE_REPLAY_WINDOW", "2")

    import app.main as main_module

    importlib.reload(main_module)
    with TestClient(main_module.app) as test_client:
        session = test_client.post(
            "/api/copilot/sessions", json={"objective": "x"}, headers=_auth(**BANKER)
        ).json()
        run = test_client.post(
            f"/api/copilot/sessions/{session['sessionId']}/runs", json={}, headers=_auth(**BANKER)
        ).json()

        response = test_client.get(
            f"/api/copilot/sessions/{session['sessionId']}/stream"
            f"?runId={run['runId']}&lastSeq=1",
            headers=_auth(**BANKER),
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "resync_required"


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
