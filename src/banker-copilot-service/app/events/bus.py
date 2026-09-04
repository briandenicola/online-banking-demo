"""Per-run event bus and trace sink.

One emit path. A frame is allocated a ``seq``, redacted, persisted, and *then* fanned out to
live subscribers — in that order, deliberately. If persistence fails, the frame is still
delivered (the banker must not watch a stream stall over a storage hiccup) but the failure is
logged loudly and the run is marked trace-degraded, because a trace with silently missing
frames is worse than no trace: #333 would replay it as though it were complete.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from app.events.envelope import CopilotEventEnvelope, new_event_id, utc_now_iso

logger = structlog.get_logger("banker-copilot-service")


class TraceSink(Protocol):
    """Durable home for every emitted frame. Epic §8.0: persisted as emitted, not reconstructed."""

    async def append(self, envelope: CopilotEventEnvelope, parent_run_id: str | None) -> None: ...

    async def read_run(self, run_id: str) -> list[dict[str, Any]]: ...


class InMemoryTraceSink:
    """Local-dev and test sink. Same interface, same ordering guarantees, no durability."""

    def __init__(self) -> None:
        self._frames: dict[str, list[dict[str, Any]]] = {}

    async def append(self, envelope: CopilotEventEnvelope, parent_run_id: str | None) -> None:
        self._frames.setdefault(envelope.run_id, []).append(envelope.to_document(parent_run_id))

    async def read_run(self, run_id: str) -> list[dict[str, Any]]:
        return list(self._frames.get(run_id, []))


class CosmosTraceSink:
    """Writes to the `copilot-traces` container, partition key ``/runId`` (epic §8.0)."""

    def __init__(self, container) -> None:
        self._container = container

    async def append(self, envelope: CopilotEventEnvelope, parent_run_id: str | None) -> None:
        document = envelope.to_document(parent_run_id)
        await asyncio.to_thread(self._container.upsert_item, document)

    async def read_run(self, run_id: str) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            return list(
                self._container.query_items(
                    query="SELECT * FROM c WHERE c.runId = @runId ORDER BY c.seq",
                    parameters=[{"name": "@runId", "value": run_id}],
                    partition_key=run_id,
                )
            )

        return await asyncio.to_thread(_query)


@dataclass
class RunStream:
    """The live + durable event stream for one run.

    ``session`` and ``run`` are distinct entities in this design and are NOT unified: a session
    is the banker's conversation, a run is one planner execution inside it. ``seq`` is scoped to
    the run, which is what makes replay deterministic.
    """

    run_id: str
    session_id: str
    sink: TraceSink
    replay_window: int
    parent_run_id: str | None = None
    _seq: int = 0
    _recent: deque = field(default_factory=deque)
    _subscribers: list[asyncio.Queue] = field(default_factory=list)
    _closed: bool = False
    trace_degraded: bool = False

    @property
    def last_seq(self) -> int:
        return self._seq

    @property
    def closed(self) -> bool:
        return self._closed

    async def emit(self, kind: str, payload: dict[str, Any]) -> CopilotEventEnvelope:
        self._seq += 1
        envelope = CopilotEventEnvelope(
            id=new_event_id(),
            seq=self._seq,
            run_id=self.run_id,
            kind=kind,
            ts=utc_now_iso(),
            payload=payload,
            session_id=self.session_id,
        )

        try:
            await self.sink.append(envelope, self.parent_run_id)
        except Exception as exc:  # noqa: BLE001 - a sink failure must never stall the banker
            self.trace_degraded = True
            logger.error(
                "Trace frame not persisted — this run is no longer replayable in full",
                run_id=self.run_id,
                seq=envelope.seq,
                kind=kind,
                error=str(exc),
            )

        self._recent.append(envelope)
        while len(self._recent) > self.replay_window:
            self._recent.popleft()

        for queue in list(self._subscribers):
            queue.put_nowait(envelope)

        if kind == "run.done":
            self._closed = True
            for queue in list(self._subscribers):
                queue.put_nowait(None)

        return envelope

    def subscribe(self, last_seq: int = 0) -> tuple[asyncio.Queue, list[CopilotEventEnvelope]]:
        """Attach a live subscriber and return whatever it missed from the replay window.

        A cursor older than the retained window returns ``None`` for the backlog so the caller
        can answer 409 `resync_required` rather than handing the client a trace with a hole in
        it and letting it look complete.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)

        backlog = [event for event in self._recent if event.seq > last_seq]
        return queue, backlog

    def replay_available_from(self, last_seq: int) -> bool:
        if last_seq == 0 or not self._recent:
            return True
        return self._recent[0].seq <= last_seq + 1

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)


class RunStreamRegistry:
    """In-process registry of live runs. Durability lives in the sink, not here."""

    def __init__(self, sink: TraceSink, replay_window: int) -> None:
        self._sink = sink
        self._replay_window = replay_window
        self._runs: dict[str, RunStream] = {}
        self._by_session: dict[str, list[str]] = {}
        self._waiters: dict[str, list[asyncio.Future]] = {}

    def create(
        self, run_id: str, session_id: str, parent_run_id: str | None = None
    ) -> RunStream:
        stream = RunStream(
            run_id=run_id,
            session_id=session_id,
            sink=self._sink,
            replay_window=self._replay_window,
            parent_run_id=parent_run_id,
        )
        self._runs[run_id] = stream
        self._by_session.setdefault(session_id, []).append(run_id)
        for waiter in self._waiters.pop(session_id, []):
            if not waiter.done():
                waiter.set_result(stream)
        return stream

    async def await_next_run(self, session_id: str, timeout: float) -> RunStream | None:
        """Block until this session has a run, or the timeout elapses.

        The UI opens the session stream and THEN dispatches the first turn, so at attach
        time there is legitimately nothing to stream yet. Answering 404 there would make an
        ordinary race look like a missing session, and the client's reconnect backoff would
        then hide the first frames of the run it was opened to watch.
        """
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[RunStream] = loop.create_future()
        self._waiters.setdefault(session_id, []).append(waiter)
        try:
            return await asyncio.wait_for(asyncio.shield(waiter), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            pending = self._waiters.get(session_id)
            if pending and waiter in pending:
                pending.remove(waiter)
            if pending == []:
                self._waiters.pop(session_id, None)

    def get(self, run_id: str) -> RunStream | None:
        return self._runs.get(run_id)

    def latest_for_session(self, session_id: str) -> RunStream | None:
        run_ids = self._by_session.get(session_id) or []
        return self._runs.get(run_ids[-1]) if run_ids else None

    def runs_for_session(self, session_id: str) -> list[str]:
        return list(self._by_session.get(session_id) or [])

    @property
    def sink(self) -> TraceSink:
        return self._sink
