"""`CopilotEventEnvelope` — ONE schema for the live UI stream AND offline eval replay.

Contract of record: `docs/design/banker-copilot-ui.md` §4.2, plus the eval-driven additions
ratified in `docs/epics/banker-copilot.md` §8.0. There is no parallel "trace schema": if the
frame the UI consumes and the frame we persist ever diverge, that is a bug, not a design choice.

Two properties are load-bearing and are asserted rather than assumed:

* ``seq`` is monotonic **and gapless** per run. Replay ordering depends on it, and so does the
  client's gap detection. It is allocated by the run's event bus, never by a caller.
* ``ts`` is the **server** clock. A client clock in a trace makes latency analysis fiction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

#: The closed set of event kinds. Adding one here without adding it to the UI's discriminated
#: union is caught at compile time on the client — that is the point of a closed enum on both
#: sides. Mirrors banker-copilot-ui.md §4.2 exactly.
EVENT_KINDS: frozenset[str] = frozenset(
    {
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
    }
)

#: The closed rejection-reason enum (epic §5.1.1 / O9). `denied` is the single terminal
#: rejection state, so a terminal frame without one of these is unreadable in replay: a policy
#: void and a human denial would score identically, and only HUMAN_DENIED is evidence about
#: the agent. Owned by authority-service; mirrored here only to validate what we persist.
TERMINAL_REASONS: frozenset[str] = frozenset(
    {"HUMAN_DENIED", "POLICY_RUNG_ESCALATED", "PAYLOAD_SUPERSEDED", "TTL_EXPIRED"}
)


class EnvelopeError(ValueError):
    """A frame that would be unreplayable. Raised at emit so the defect surfaces immediately."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class CopilotEventEnvelope:
    id: str
    seq: int
    run_id: str
    kind: str
    ts: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: Present on run-scoped frames belonging to a session. Not part of §4.2's envelope, so it
    #: rides alongside rather than inside — the UI ignores what it does not know.
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise EnvelopeError(
                f"unknown event kind {self.kind!r}. The kind set is closed and shared with the "
                "UI's discriminated union; an unlisted kind is a silent no-op on the client."
            )
        if self.seq < 1:
            raise EnvelopeError("seq is 1-based and monotonic per run")
        if self.kind == "approval.terminal":
            _validate_terminal(self.payload)

    def to_wire(self) -> dict[str, Any]:
        """The exact object the UI receives in the SSE `data:` field."""
        wire = {
            "id": self.id,
            "seq": self.seq,
            "runId": self.run_id,
            "kind": self.kind,
            "ts": self.ts,
            "payload": self.payload,
        }
        if self.session_id:
            wire["sessionId"] = self.session_id
        return wire

    def to_document(self, parent_run_id: str | None = None) -> dict[str, Any]:
        """The persisted trace frame. Partition key is ``/runId`` per epic §8.0.

        The persisted frame is the wire frame plus provenance the UI has no use for. It is
        deliberately a superset and never a re-shaping: a replay must be able to reconstruct
        exactly what the banker saw.

        ``runId``, ``sessionId``, ``seq``, ``kind`` and ``ts`` are TOP LEVEL and unconditional.
        Cosmos will not use a composite index unless every filtered and ordered path appears in
        it, so nesting one of these under a wrapper — or omitting it — does not raise: the query
        quietly falls back to a full scan, or returns zero rows. Both look like "no data".
        """
        if not self.session_id:
            raise EnvelopeError(
                "a persisted trace frame must carry sessionId at the top level. Eval replay "
                "(#333) reads WHERE sessionId = @sessionId ORDER BY ts ASC, and a frame without "
                "it is not missing from the results with an error — it is silently absent."
            )
        document = dict(self.to_wire())
        document["id"] = self.id
        document["runId"] = self.run_id
        document["sessionId"] = self.session_id
        if parent_run_id:
            document["parentRunId"] = parent_run_id
        return document


def _validate_terminal(payload: dict[str, Any]) -> None:
    state = payload.get("state")
    if state not in {"denied", "executed"}:
        raise EnvelopeError(
            "approval.terminal payload requires state 'denied' or 'executed'; there is no "
            "'expired' or 'voided' state in this lifecycle."
        )
    if state == "denied":
        reason = payload.get("terminalReason")
        if reason not in TERMINAL_REASONS:
            raise EnvelopeError(
                f"approval.terminal state='denied' requires terminalReason in "
                f"{sorted(TERMINAL_REASONS)}, got {reason!r}. Without it, replay cannot tell a "
                "policy-driven void from a banker rejecting the agent — and it would score the "
                "former as a model regression."
            )


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:20]}"
