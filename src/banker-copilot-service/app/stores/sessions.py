"""Session, run and artifact persistence.

``session`` and ``run`` are two genuinely distinct entities and are not unified:

* A **session** is the banker's conversation with the harness. It owns the actor, the objective,
  the working context and the capability grant. It outlives any single agent execution.
* A **run** is one planner execution inside a session. It owns the plan, the ``seq`` counter and
  the trace. A session with three runs has three independently replayable traces.

Collapsing them would make ``seq`` session-scoped, which breaks per-run replay determinism, and
would make "re-run this with the same objective" indistinguishable from "continue talking".
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.events.envelope import utc_now_iso


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# The persisted documents are camelCase, because camelCase is this repo's cross-service wire
# contract and the partition keys and composite indexes are declared against camelCase paths.
#
# These maps exist so the casing is stated ONCE per entity instead of at each call site. The
# earlier code built documents with `asdict()` (snake_case) and then hand-patched a few
# camelCase keys on top, which produced documents carrying BOTH spellings of the same fact and
# — for Artifact, where the patching was forgotten — a document with no `runId` and no
# `sessionId` at all. Cosmos does not report a field-path mismatch. It returns zero rows, and an
# artifact pane that is empty because the query is wrong looks exactly like one that is empty
# because the run produced nothing.
# `bankerId` and `updatedAt`, not `actorId` and nothing, because the platform lane indexes
# (bankerId ASC, updatedAt DESC) to serve "my sessions, most recently active first" — the
# session list in the UI's left pane. An index whose paths the writer does not produce is not an
# error: the query is answered by a full scan and looks healthy until the container is big.
# The index is the declared consumer, so the writer conforms to it.
_SESSION_FIELDS = {
    "id": "id",
    "actor_id": "bankerId",
    "actor_username": "actorUsername",
    "objective": "objective",
    "context": "context",
    "capabilities": "capabilities",
    "created_at": "createdAt",
    "updated_at": "updatedAt",
    "expires_at": "expiresAt",
    "run_ids": "runIds",
    "messages": "messages",
}

_RUN_FIELDS = {
    "id": "id",
    "session_id": "sessionId",
    "objective": "objective",
    "status": "status",
    "started_at": "startedAt",
    "parent_run_id": "parentRunId",
    "finished_at": "finishedAt",
    "final_seq": "finalSeq",
    "trace_degraded": "traceDegraded",
}

_ARTIFACT_FIELDS = {
    "id": "id",
    "run_id": "runId",
    "session_id": "sessionId",
    "kind": "kind",
    "title": "title",
    "revision": "revision",
    "content": "content",
    "created_at": "createdAt",
}


def _to_document(instance: Any, mapping: dict[str, str], doc_type: str) -> dict[str, Any]:
    document = {wire: getattr(instance, attr) for attr, wire in mapping.items()}
    document["docType"] = doc_type
    return document


def _from_document(document: dict[str, Any], mapping: dict[str, str], cls):
    """Refuse a document that does not carry every mapped path.

    A missing path would otherwise become a default or a ``None`` and travel onward as data.
    This is the read-side half of the same guarantee: if the casing ever drifts again, it
    fails here by NAME rather than producing a half-populated object.
    """
    missing = [wire for wire in mapping.values() if wire not in document]
    if missing:
        raise ValueError(
            f"{cls.__name__} document is missing {missing}. The persisted contract is camelCase; "
            "a snake_case document is from a superseded writer and must not be silently coerced."
        )
    return cls(**{attr: document[wire] for attr, wire in mapping.items()})


@dataclass
class Session:
    id: str
    actor_id: str
    actor_username: str
    objective: str
    context: dict[str, Any]
    capabilities: list[str]
    created_at: str
    expires_at: str
    updated_at: str = ""
    run_ids: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def touch(self) -> None:
        """Advance ``updatedAt``. Called on every mutation, because the session list orders by
        it — a session whose ``updatedAt`` never moves sinks to the bottom of the banker's own
        list while they are actively working in it."""
        self.updated_at = utc_now_iso()

    def to_wire(self) -> dict[str, Any]:
        return {
            "sessionId": self.id,
            "bankerId": self.actor_id,
            "updatedAt": self.updated_at,
            "objective": self.objective,
            "context": self.context,
            "capabilities": self.capabilities,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "runIds": list(self.run_ids),
            "traceUrl": f"/api/copilot/sessions/{self.id}/stream",
        }

    def to_document(self) -> dict[str, Any]:
        document = _to_document(self, _SESSION_FIELDS, "session")
        # The sessions container is partitioned by /sessionId, and a session's own id IS its
        # session id. Without this the document lands in the undefined partition.
        document["sessionId"] = self.id
        return document


@dataclass
class Run:
    id: str
    session_id: str
    objective: str
    status: str
    started_at: str
    parent_run_id: str | None = None
    finished_at: str | None = None
    final_seq: int | None = None
    trace_degraded: bool = False

    def to_wire(self) -> dict[str, Any]:
        return {
            "runId": self.id,
            "sessionId": self.session_id,
            "objective": self.objective,
            "status": self.status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "finalSeq": self.final_seq,
            "parentRunId": self.parent_run_id,
            "traceDegraded": self.trace_degraded,
        }

    def to_document(self) -> dict[str, Any]:
        document = _to_document(self, _RUN_FIELDS, "run")
        document["runId"] = self.id
        return document


@dataclass
class Artifact:
    id: str
    run_id: str
    session_id: str
    kind: str
    title: str
    revision: int
    content: Any
    created_at: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "artifactId": self.id,
            "runId": self.run_id,
            "kind": self.kind,
            "title": self.title,
            "revision": self.revision,
            "content": self.content,
            "createdAt": self.created_at,
        }

    def to_document(self) -> dict[str, Any]:
        document = _to_document(self, _ARTIFACT_FIELDS, "artifact")
        document["artifactId"] = self.id
        return document


class InMemorySessionStore:
    """Used when COSMOS_DB_ENDPOINT is unset — local dev and tests."""

    mode = "memory"

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._runs: dict[str, Run] = {}
        self._artifacts: dict[str, Artifact] = {}

    async def save_session(self, session: Session) -> None:
        session.touch()
        self._sessions[session.id] = session

    async def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def save_run(self, run: Run) -> None:
        self._runs[run.id] = run

    async def get_run(self, run_id: str, session_id: str | None = None) -> Run | None:
        run = self._runs.get(run_id)
        # Mirrors the Cosmos store's partition scoping so the in-memory double cannot pass a
        # lookup the real store would answer with nothing. A fake that is more permissive than
        # the thing it stands in for is how partition bugs reach production green.
        if run is None or (session_id and run.session_id != session_id):
            return None
        return run

    async def save_artifact(self, artifact: Artifact) -> None:
        self._artifacts[artifact.id] = artifact

    async def list_artifacts(self, session_id: str, run_id: str) -> list[Artifact]:
        return [
            a
            for a in self._artifacts.values()
            if a.run_id == run_id and a.session_id == session_id
        ]


class CosmosSessionStore:
    """Sessions and runs share the sessions container, whose partition key is ``/id``.

    They remain separate documents discriminated by ``docType`` — one container is a storage
    decision, not a modelling one. Artifacts get their own container, partitioned by
    ``/sessionId``, because they are read on a different axis and can be large.

    The partition keys are the platform lane's, and passing the wrong VALUE for one is the most
    expensive mistake available here: Cosmos answers a partition-key mismatch with ZERO ROWS
    and no error. An empty artifact pane and a session that genuinely has no artifacts are
    indistinguishable from inside this process.
    """

    mode = "cosmos"

    def __init__(self, sessions_container, artifacts_container) -> None:
        self._sessions = sessions_container
        self._artifacts = artifacts_container

    async def save_session(self, session: Session) -> None:
        # Touch here, in the store, rather than at each caller. A timestamp maintained by
        # convention at N call sites is a timestamp that is wrong at the N+1th.
        session.touch()
        await asyncio.to_thread(self._sessions.upsert_item, session.to_document())

    async def get_session(self, session_id: str) -> Session | None:
        def _read():
            try:
                return self._sessions.read_item(item=session_id, partition_key=session_id)
            except Exception:
                return None

        document = await asyncio.to_thread(_read)
        return _session_from_document(document) if document else None

    async def save_run(self, run: Run) -> None:
        await asyncio.to_thread(self._sessions.upsert_item, run.to_document())

    async def get_run(self, run_id: str, session_id: str | None = None) -> Run | None:
        """A point read when the caller knows the session, a cross-partition query otherwise.

        The container is partitioned by ``/sessionId``, so a RUN's partition is its SESSION —
        not its own id. Reading it with ``partition_key=run_id`` would address a partition that
        does not exist and return nothing, with no error. The session id is the only correct
        partition value for a run document, which is why callers are pushed to supply it.
        """
        if session_id:

            def _read():
                try:
                    return self._sessions.read_item(item=run_id, partition_key=session_id)
                except Exception:
                    return None

            document = await asyncio.to_thread(_read)
        else:
            # Deliberately cross-partition and deliberately not the hot path: reachable only
            # from a direct GET /runs/{id} where the session is not yet known.
            def _query():
                return list(
                    self._sessions.query_items(
                        query=(
                            "SELECT * FROM c WHERE c.docType = 'run' AND c.runId = @runId"
                        ),
                        parameters=[{"name": "@runId", "value": run_id}],
                        enable_cross_partition_query=True,
                    )
                )

            rows = await asyncio.to_thread(_query)
            document = rows[0] if rows else None

        if not document or document.get("docType") != "run":
            return None
        return _run_from_document(document)

    async def save_artifact(self, artifact: Artifact) -> None:
        await asyncio.to_thread(self._artifacts.upsert_item, artifact.to_document())

    async def list_artifacts(self, session_id: str, run_id: str) -> list[Artifact]:
        def _query():
            return list(
                self._artifacts.query_items(
                    query="SELECT * FROM c WHERE c.runId = @runId ORDER BY c.revision",
                    parameters=[{"name": "@runId", "value": run_id}],
                    # /sessionId, NOT /runId. Passing runId here is not an error — it is a
                    # partition that contains nothing, and the empty result reads as "this run
                    # produced no artifacts".
                    partition_key=session_id,
                )
            )

        rows = await asyncio.to_thread(_query)
        return [_artifact_from_document(row) for row in rows]


def _session_from_document(document: dict[str, Any]) -> Session:
    return _from_document(document, _SESSION_FIELDS, Session)


def _run_from_document(document: dict[str, Any]) -> Run:
    return _from_document(document, _RUN_FIELDS, Run)


def _artifact_from_document(document: dict[str, Any]) -> Artifact:
    return _from_document(document, _ARTIFACT_FIELDS, Artifact)


def new_session(
    actor_id: str,
    actor_username: str,
    objective: str,
    context: dict[str, Any],
    capabilities: list[str],
    ttl_seconds: int,
) -> Session:
    now = datetime.now(timezone.utc)
    return Session(
        id=_new_id("sess"),
        actor_id=actor_id,
        actor_username=actor_username,
        objective=objective,
        context=context,
        capabilities=capabilities,
        created_at=utc_now_iso(),
        # Equal to createdAt at birth rather than empty: the session list orders by updatedAt,
        # and a new session with no value would sort as though it were the oldest.
        updated_at=utc_now_iso(),
        expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z"),
    )


def new_run(session_id: str, objective: str, parent_run_id: str | None = None) -> Run:
    return Run(
        id=_new_id("run"),
        session_id=session_id,
        objective=objective,
        status="running",
        started_at=utc_now_iso(),
        parent_run_id=parent_run_id,
    )


def new_artifact(
    run_id: str, session_id: str, kind: str, title: str, content: Any, revision: int = 1
) -> Artifact:
    return Artifact(
        id=_new_id("art"),
        run_id=run_id,
        session_id=session_id,
        kind=kind,
        title=title,
        revision=revision,
        content=content,
        created_at=utc_now_iso(),
    )
