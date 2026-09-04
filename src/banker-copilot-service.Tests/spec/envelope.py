"""``CopilotEventEnvelope`` — one schema for the live stream AND for eval replay.

Contract of record: ``docs/design/banker-copilot-ui.md`` §4.2, ratified as the
single trace schema by epic §8.0, which adds the eval-driven fields.

    "Any divergence between what the UI consumes and what we persist is a bug,
    not a design choice." — epic §8.0

That sentence is the property this module exists to make testable. The way it
gets violated is never a decision; it is drift. Someone adds a field to the live
frame for the UI and the persisted frame is written from a different dict; or
persistence is added as an afterthought that reconstructs frames from a log.
Both produce a live stream and a trace that agree today and diverge quietly.

So there is exactly ONE construction site (``TraceEmitter.emit``), it persists
BEFORE it publishes, and replay reads back JSON bytes from the store rather than
any in-memory object the live stream also touched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

# ---------------------------------------------------------------------------
# Entities. Epic §0.1: "session and run are genuinely two entities, not a
# naming drift." They are distinct types here so that conflating them is a
# TypeError rather than a code review.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionId:
    """A banker's Copilot conversation. Durable, spans many turns."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith("ses_"):
            raise ValueError(f"session ids are prefixed 'ses_', got {self.value!r}")


@dataclass(frozen=True)
class RunId:
    """One intent → plan → tools → artifact cycle INSIDE a session."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith("run_"):
            raise ValueError(f"run ids are prefixed 'run_', got {self.value!r}")


@dataclass(frozen=True)
class Run:
    runId: RunId
    sessionId: SessionId
    parentRunId: RunId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.runId, RunId):
            raise TypeError("runId must be a RunId, not a session id or a bare string")
        if not isinstance(self.sessionId, SessionId):
            raise TypeError("sessionId must be a SessionId, not a run id or a bare string")


# ---------------------------------------------------------------------------
# The closed kind union (UI §4.2). A new kind server-side without a client
# handler is meant to be a compile error in TypeScript; in Python the equivalent
# is refusing to emit an unknown kind at all.
# ---------------------------------------------------------------------------

EVENT_KINDS = (
    "run.started",
    "plan.proposed",
    "plan.revised",
    "step.started",
    "step.completed",
    "step.failed",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "subagent.spawned",
    "subagent.progress",
    "subagent.completed",
    "approval.required",
    "approval.updated",
    "approval.terminal",
    "artifact.created",
    "artifact.updated",
    "run.error",
    "run.done",
    "heartbeat",
)

TOOL_KINDS = ("tool.started", "tool.completed", "tool.failed")

# Epic §5.1.1 / §0.1: ONE terminal rejection state, carrying a mandatory
# closed-enum reason. There is no `expired`, no `voided`, no `execution_failed`.
TERMINAL_REASONS = (
    "HUMAN_DENIED",
    "POLICY_RUNG_ESCALATED",
    "PAYLOAD_SUPERSEDED",
    "TTL_EXPIRED",
)

# Epic §8.0, the "➕ add" rows. Each is a field the trace MUST carry or the
# corresponding eval question (#333) is unanswerable offline.
REQUIRED_PAYLOAD_FIELDS: Mapping[str, tuple[str, ...]] = {
    "tool.started": ("traceId", "spanId"),
    "tool.completed": ("traceId", "spanId"),
    "tool.failed": ("traceId", "spanId"),
    "subagent.spawned": ("parentRunId",),
    "approval.required": ("policyVersion", "resolvedRung"),
}


class EnvelopeError(ValueError):
    """A frame that does not satisfy the ratified envelope contract."""


@dataclass(frozen=True)
class CopilotEventEnvelope:
    id: str
    seq: int
    runId: str
    kind: str
    ts: str
    payload: Mapping[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "seq": self.seq,
                "runId": self.runId,
                "kind": self.kind,
                "ts": self.ts,
                "payload": self.payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def from_json(raw: str) -> "CopilotEventEnvelope":
        obj = json.loads(raw)
        unknown = set(obj) - {"id", "seq", "runId", "kind", "ts", "payload"}
        if unknown:
            raise EnvelopeError(f"unknown envelope field(s) {sorted(unknown)}")
        return CopilotEventEnvelope(
            id=obj["id"],
            seq=obj["seq"],
            runId=obj["runId"],
            kind=obj["kind"],
            ts=obj["ts"],
            payload=obj["payload"],
        )


class TraceStore:
    """Stand-in for the ``copilot-traces`` container, PK ``/runId``.

    Holds **bytes**, never objects. That is not an implementation detail: it is
    what stops ``replay()`` from accidentally handing back the very list the
    live stream rendered from and calling the resulting equality a fidelity
    proof.
    """

    def __init__(self) -> None:
        self._frames: dict[str, list[str]] = {}

    def append(self, run_id: str, raw: str) -> None:
        if not isinstance(raw, str):
            raise TypeError("the trace store persists serialized frames only")
        self._frames.setdefault(run_id, []).append(raw)

    def raw_frames(self, run_id: str) -> tuple[str, ...]:
        return tuple(self._frames.get(run_id, ()))

    def run_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._frames))


def replay(store: TraceStore, run_id: str) -> tuple[CopilotEventEnvelope, ...]:
    """Reconstruct a historical run from persisted frames — the #333 entry point."""
    frames = tuple(CopilotEventEnvelope.from_json(raw) for raw in store.raw_frames(run_id))
    _assert_contiguous(frames, run_id)
    return frames


def _assert_contiguous(frames: Iterable[CopilotEventEnvelope], run_id: str) -> None:
    expected = 1
    for frame in frames:
        if frame.runId != run_id:
            raise EnvelopeError(f"frame {frame.id} is partitioned under the wrong run")
        if frame.seq != expected:
            raise EnvelopeError(
                f"seq gap in run {run_id}: expected {expected}, got {frame.seq}. "
                "Gapless-per-run is what deterministic replay rests on"
            )
        expected += 1


def redact(payload: Any, jsonpaths: Iterable[str]) -> Any:
    """Apply the manifest ``redaction`` JSONPaths (§3.2) at EMIT time.

    Supports the two shapes the worked manifest actually uses: ``$.a.b`` and
    ``$[*].a``. Redaction at render time would be a security bug, not a
    performance choice: persisted traces outlive the session, so a field
    scrubbed only in the UI is a field written to Cosmos forever.
    """
    result = json.loads(json.dumps(payload))
    for path in jsonpaths:
        if not path.startswith("$"):
            raise EnvelopeError(f"redaction path {path!r} is not a JSONPath")
        parts = [p for p in path[1:].replace("[*]", ".[*]").split(".") if p]
        _redact_at(result, parts)
    return result


def _redact_at(node: Any, parts: list[str]) -> None:
    if not parts:
        return
    head, rest = parts[0], parts[1:]
    if head == "[*]":
        if isinstance(node, list):
            for item in node:
                _redact_at(item, rest)
        return
    if isinstance(node, dict):
        if not rest:
            node.pop(head, None)
            return
        _redact_at(node.get(head), rest)


@dataclass
class TraceEmitter:
    """The ONE construction site for a frame. Persist, then publish.

    Ordering matters and is asserted: if the frame were published first and
    persisted afterwards, a crash between the two would leave the UI having
    shown a step that no eval replay can ever see — the divergence §8.0
    forbids, in the direction nobody notices, because the demo looked fine.
    """

    store: TraceStore
    clock: Callable[[], str]
    id_factory: Callable[[int], str] = field(default=lambda n: f"evt_{n:06d}")
    redaction_paths: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    _seq: dict[str, int] = field(default_factory=dict, init=False)
    _subscribers: dict[str, list[list[CopilotEventEnvelope]]] = field(
        default_factory=dict, init=False
    )
    _emitted: int = field(default=0, init=False)
    _done: set[str] = field(default_factory=set, init=False)

    # -- subscription is SESSION-scoped (epic §0.1). A banker watches a
    # -- conversation, not a turn; every frame still carries runId so the UI and
    # -- #333 can partition by run.
    def subscribe(self, session_id: SessionId) -> list[CopilotEventEnvelope]:
        if not isinstance(session_id, SessionId):
            raise TypeError("the SSE stream is session-scoped; subscribe with a SessionId")
        sink: list[CopilotEventEnvelope] = []
        self._subscribers.setdefault(session_id.value, []).append(sink)
        return sink

    def next_seq(self, run: Run) -> int:
        """The seq the next frame for this run will carry (1-based, gapless)."""
        return self._seq.get(run.runId.value, 0) + 1

    def emit(self, run: Run, kind: str, payload: Mapping[str, Any]) -> CopilotEventEnvelope:
        if not isinstance(run, Run):
            raise TypeError("emit takes a Run, which carries both ids and cannot conflate them")
        if kind not in EVENT_KINDS:
            raise EnvelopeError(
                f"unknown event kind {kind!r}; the kind union is closed so that a new "
                "server-side kind is a client compile error, not a silent no-op"
            )
        if run.runId.value in self._done:
            raise EnvelopeError(
                f"run {run.runId.value} already emitted run.done; a late frame would make "
                "finalSeq a lie"
            )

        for required in REQUIRED_PAYLOAD_FIELDS.get(kind, ()):
            if required not in payload:
                raise EnvelopeError(
                    f"'{kind}' frame is missing required field '{required}' (epic §8.0); "
                    "it cannot be recovered later, which is the whole reason it is required "
                    "at emit"
                )

        if kind == "approval.terminal":
            state = payload.get("state")
            if state not in ("denied", "executed"):
                raise EnvelopeError("approval.terminal state must be 'denied' or 'executed'")
            if state == "denied":
                reason = payload.get("terminalReason")
                if reason not in TERMINAL_REASONS:
                    raise EnvelopeError(
                        "a denied approval frame needs a closed-enum terminalReason; without "
                        "it an offline replay scores a policy void as a human rejecting the "
                        "agent (epic §8.0 / §5.1.1)"
                    )

        seq = self._seq.get(run.runId.value, 0) + 1
        self._seq[run.runId.value] = seq
        self._emitted += 1

        clean = redact(payload, self.redaction_paths.get(kind, ()))

        if kind == "run.done":
            if clean.get("finalSeq") != seq:
                raise EnvelopeError(
                    f"run.done.finalSeq must equal its own seq ({seq}); the client asserts on "
                    "it to prove it saw every frame"
                )
            self._done.add(run.runId.value)

        envelope = CopilotEventEnvelope(
            id=self.id_factory(self._emitted),
            seq=seq,
            runId=run.runId.value,
            kind=kind,
            ts=self.clock(),
            payload=clean,
        )

        # Persist FIRST. Durability of the eval input does not depend on anyone
        # being connected.
        self.store.append(run.runId.value, envelope.to_json())

        for sink in self._subscribers.get(run.sessionId.value, ()):
            sink.append(envelope)

        return envelope
