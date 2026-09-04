"""`/api/copilot` — the harness surface.

Design of record: `docs/design/banker-copilot-policy-engine.md` §8.1–§8.3.

The stream is SSE. The client opens it with `fetch`, not native `EventSource`, because
`EventSource` cannot set an `Authorization` header and the token would end up in the query
string — and therefore in nginx access logs, browser history and every APM span. The gateway
already carries `proxy_buffering off` on this location.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.auth import UserContext, require_banker
from app.dependencies import (
    correlation_id,
    get_authority,
    get_planner,
    get_registry,
    get_runs,
    get_session_store,
)
from app.events.envelope import CopilotEventEnvelope, utc_now_iso
from app.planner.loop import AGENT_ID, PlannerRequest
from app.stores.sessions import new_run, new_session
from app.tools.propose import PROPOSE_TOOL_SCHEMA, ProposeRejected

logger = structlog.get_logger("banker-copilot-service")

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class CreateSessionRequest(BaseModel):
    objective: str = Field(..., min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


class StartRunRequest(BaseModel):
    objective: str | None = Field(default=None, max_length=2000)
    actionId: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)


class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class ProposeRequestBody(BaseModel):
    """The sole write affordance, also exposed directly so the UI and tests can exercise it."""

    actionId: str
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)
    agentAssessment: dict[str, Any] | None = None
    supersedesApprovalId: str | None = None

    # `cosignerId` is deliberately absent and, because this model forbids extras, a request
    # carrying it is rejected with 422 rather than quietly ignored.
    model_config = {"extra": "forbid"}


@router.get("/tools")
async def list_tools(
    user: UserContext = Depends(require_banker),
    registry=Depends(get_registry),
):
    """Manifest introspection. Shows what the agent can do — and that none of it is a write."""
    return {
        "manifestId": registry.manifest.manifest_id,
        "readTools": registry.describe(),
        "writeTools": [],
        "writeAffordance": {
            "toolId": "propose_action",
            "displayName": "Propose an action for human signature",
            "description": (
                "Submit a proposal to authority-service. This does not execute anything: a "
                "human signature is required, and authority-service is the sole executor of "
                "agent-originated writes."
            ),
            "parameters": PROPOSE_TOOL_SCHEMA,
        },
    }


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    user: UserContext = Depends(require_banker),
    registry=Depends(get_registry),
    store=Depends(get_session_store),
    request: Request = None,
):
    session = new_session(
        actor_id=user.user_id,
        actor_username=user.username,
        objective=body.objective,
        context=body.context,
        capabilities=sorted({tool.capability_scope for tool in registry.tools}),
        ttl_seconds=request.app.state.settings.session_ttl_seconds,
    )
    await store.save_session(session)

    wire = session.to_wire()
    wire["agentId"] = AGENT_ID
    wire["manifestId"] = registry.manifest.manifest_id
    return wire


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: UserContext = Depends(require_banker),
    store=Depends(get_session_store),
    runs=Depends(get_runs),
):
    session = await _load_owned_session(store, session_id, user)
    wire = session.to_wire()
    wire["runIds"] = runs.runs_for_session(session_id) or session.run_ids
    return wire


@router.post("/sessions/{session_id}/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    session_id: str,
    body: StartRunRequest,
    request: Request,
    user: UserContext = Depends(require_banker),
    store=Depends(get_session_store),
    runs=Depends(get_runs),
    planner=Depends(get_planner),
):
    """Start one planner execution inside a session.

    A ``run`` is not a ``session``. Sequence numbers are run-scoped, which is what makes each
    trace independently replayable; a session with three runs has three traces, not one.
    """
    session = await _load_owned_session(store, session_id, user)

    run = new_run(session_id=session_id, objective=body.objective or session.objective)
    session.run_ids.append(run.id)
    await store.save_run(run)
    await store.save_session(session)

    stream = runs.create(run.id, session_id)

    planner_request = PlannerRequest(
        session=session,
        run_id=run.id,
        objective=run.objective,
        action_id=body.actionId,
        payload=body.payload,
        facts=body.facts,
        bearer_token=user.bearer_token,
        correlation_id=correlation_id(request),
    )

    async def _execute() -> None:
        try:
            await planner.run(planner_request, stream)
        finally:
            run.status = "completed" if not stream.trace_degraded else "completed_degraded"
            run.finished_at = utc_now_iso()
            run.final_seq = stream.last_seq
            run.trace_degraded = stream.trace_degraded
            await store.save_run(run)

    asyncio.create_task(_execute())

    return {
        "runId": run.id,
        "sessionId": session_id,
        "status": "running",
        "traceUrl": f"/api/copilot/sessions/{session_id}/stream?runId={run.id}",
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: UserContext = Depends(require_banker),
    store=Depends(get_session_store),
    runs=Depends(get_runs),
):
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await _load_owned_session(store, run.session_id, user)

    wire = run.to_wire()
    stream = runs.get(run_id)
    wire["lastSeq"] = stream.last_seq if stream else run.final_seq
    return wire


@router.get("/runs/{run_id}/trace")
async def get_run_trace(
    run_id: str,
    user: UserContext = Depends(require_banker),
    store=Depends(get_session_store),
    runs=Depends(get_runs),
):
    """The persisted trace, read back in the same envelope shape the UI streamed.

    This is the eval replay path (#333). It reads the sink, not the in-process buffer, so a
    trace that failed to persist reads as missing here rather than being reconstructed from
    memory and looking complete.
    """
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await _load_owned_session(store, run.session_id, user)

    frames = await runs.sink.read_run(run_id)
    return {
        "runId": run_id,
        "frameCount": len(frames),
        "traceDegraded": run.trace_degraded,
        "frames": frames,
    }


@router.get("/runs/{run_id}/artifacts")
async def list_run_artifacts(
    run_id: str,
    user: UserContext = Depends(require_banker),
    store=Depends(get_session_store),
):
    """The artifact pane's read path after a reload.

    The session id is resolved first and passed down, because `copilot-artifacts` is
    partitioned by `/sessionId` — a lookup that knows only the run id cannot address the
    right partition, and would come back empty rather than wrong.
    """
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await _load_owned_session(store, run.session_id, user)

    artifacts = await store.list_artifacts(run.session_id, run_id)
    return {
        "runId": run_id,
        "sessionId": run.session_id,
        "artifacts": [artifact.to_wire() for artifact in artifacts],
    }


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def post_message(
    session_id: str,
    body: MessageRequest,
    user: UserContext = Depends(require_banker),
    store=Depends(get_session_store),
    runs=Depends(get_runs),
):
    session = await _load_owned_session(store, session_id, user)
    session.messages.append(
        {"role": "user", "content": body.content, "ts": utc_now_iso(), "actorId": user.user_id}
    )
    await store.save_session(session)

    stream = runs.latest_for_session(session_id)
    seq = stream.last_seq if stream else 0
    return {"accepted": True, "seq": seq}


@router.post("/sessions/{session_id}/propose", status_code=status.HTTP_201_CREATED)
async def propose(
    session_id: str,
    body: ProposeRequestBody,
    request: Request,
    user: UserContext = Depends(require_banker),
    store=Depends(get_session_store),
    authority=Depends(get_authority),
):
    """The ONLY write-shaped route in this service — and it still does not write.

    It forwards to authority-service, which evaluates the ladder, creates the approval and
    waits for human signatures. There is no branch in this service that executes anything.
    """
    session = await _load_owned_session(store, session_id, user)

    try:
        outcome = await authority.propose(
            body.model_dump(exclude_none=True),
            bearer_token=user.bearer_token,
            session_id=session.id,
            agent_id=AGENT_ID,
            correlation_id=correlation_id(request),
        )
    except ProposeRejected as exc:
        raise HTTPException(status_code=400, detail={"error": exc.code, "message": exc.message})

    return JSONResponse(status_code=outcome.status_code, content=outcome.body)


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    request: Request,
    runId: str | None = None,
    lastSeq: int = 0,
    user: UserContext = Depends(require_banker),
    store=Depends(get_session_store),
    runs=Depends(get_runs),
):
    await _load_owned_session(store, session_id, user)

    heartbeat_seconds = request.app.state.settings.sse_heartbeat_seconds

    # The standard SSE resume header. Linus's client sends BOTH this and `?lastSeq=`;
    # honouring only the query param would mean a resume that looks like it worked while
    # silently replaying the whole run, which the client would render as duplicates.
    if lastSeq <= 0:
        header_cursor = request.headers.get("last-event-id")
        if header_cursor:
            try:
                lastSeq = max(0, int(header_cursor))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Last-Event-ID must be the integer seq of the last event received.",
                )

    stream = runs.get(runId) if runId else runs.latest_for_session(session_id)
    if stream is None and runId:
        raise HTTPException(status_code=404, detail="Unknown run for this session")
    if stream is None:
        # Attach-then-dispatch is the normal UI order, not an error. Wait one heartbeat
        # interval for the run to appear; if none does, open the stream anyway and let the
        # heartbeats carry it. A client that asked to watch a session it owns gets a live
        # connection, not a 404 that trips its reconnect backoff.
        stream = await runs.await_next_run(session_id, timeout=heartbeat_seconds)

    if stream is not None and not stream.replay_available_from(lastSeq):
        # Never hand the client a trace with a hole in it and let it look complete.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "resync_required",
                "message": "The requested cursor has fallen out of the replay window.",
            },
        )

    idle_budget = request.app.state.settings.session_ttl_seconds

    async def _events():
        nonlocal stream
        queue = None
        try:
            # No run yet: heartbeat until one starts, the client goes away, or the session
            # idles out. The connection is honest about being alive-and-waiting, which is
            # the distinction §4.6 exists to preserve.
            waited = 0.0
            while stream is None:
                if await request.is_disconnected() or waited >= idle_budget:
                    return
                stream = await runs.await_next_run(session_id, timeout=heartbeat_seconds)
                if stream is None:
                    waited += heartbeat_seconds
                    yield _heartbeat_frame()

            # Subscribe exactly once, and only here. Subscribing before the generator ran
            # would replay the backlog twice — a duplicate-seq stream that looks plausible.
            queue, backlog = stream.subscribe(lastSeq)
            for event in backlog:
                yield _sse_frame(event)

            # A run that finished before the client attached is complete, not idle. Holding the
            # connection open would render as "still thinking" forever — the ambiguity §4.6
            # exists to eliminate.
            if stream.closed and queue.empty():
                return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                except asyncio.TimeoutError:
                    if stream.closed:
                        break
                    # A heartbeat is a promise of liveness. Without it a half-open TCP
                    # connection is indistinguishable from "the agent is thinking".
                    yield _heartbeat_frame()
                    continue

                if event is None:
                    break
                yield _sse_frame(event)
        finally:
            if stream is not None and queue is not None:
                stream.unsubscribe(queue)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_frame(event: CopilotEventEnvelope) -> str:
    # `id:` is the SEQ, not the envelope id, so that a browser's automatic Last-Event-ID
    # resume and our own `?lastSeq=` cursor are the same number. Two cursors meaning
    # "where you got to" is one cursor too many. The envelope id is still in `data`.
    return (
        f"id: {event.seq}\n"
        f"event: {event.kind}\n"
        f"data: {json.dumps(event.to_wire())}\n\n"
    )


def _heartbeat_frame() -> str:
    return "event: heartbeat\n" f"data: {json.dumps({'serverTs': utc_now_iso()})}\n\n"


async def _load_owned_session(store, session_id: str, user: UserContext):
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.actor_id != user.user_id:
        # A 404, not a 403: existence of another banker's session is not this caller's business.
        raise HTTPException(status_code=404, detail="Session not found")
    return session
