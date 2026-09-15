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
        "mode_transition",
        "evidence_compacted",
        "evidence_progress",
        "sensitive_read_recorded",
    }
)

RUN_MODES: frozenset[str] = frozenset({"plan", "execute"})
_TOOL_EVENT_KINDS: frozenset[str] = frozenset({"tool.started", "tool.completed", "tool.failed"})

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
        elif self.kind == "mode_transition":
            _validate_mode_transition(self.payload)
        elif self.kind == "evidence_compacted":
            _validate_evidence_compacted(self.payload)
        elif self.kind == "evidence_progress":
            _validate_evidence_progress(self.payload)
        elif self.kind == "sensitive_read_recorded":
            _validate_sensitive_read_recorded(self.payload)
        elif self.kind in _TOOL_EVENT_KINDS:
            _validate_tool_invocation(self.kind, self.payload)

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


def _validate_mode_transition(payload: dict[str, Any]) -> None:
    if set(payload) != {"from", "to"} or payload.get("from") != "plan" or payload.get("to") != "execute":
        raise EnvelopeError(
            "mode_transition payload must be exactly {'from': 'plan', 'to': 'execute'}"
        )


def _validate_evidence_compacted(payload: dict[str, Any]) -> None:
    if set(payload) != {"compactedIds", "originalTokensEstimate", "compactedTokensEstimate"}:
        raise EnvelopeError(
            "evidence_compacted payload must be exactly {'compactedIds', "
            "'originalTokensEstimate', 'compactedTokensEstimate'}"
        )
    ids = payload["compactedIds"]
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(item, str) or not item for item in ids)
    ):
        raise EnvelopeError("evidence_compacted compactedIds must be a non-empty list of non-empty strings")
    for field in ("originalTokensEstimate", "compactedTokensEstimate"):
        value = payload[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise EnvelopeError(f"evidence_compacted {field} must be a non-negative integer")
    if payload["compactedTokensEstimate"] > payload["originalTokensEstimate"]:
        raise EnvelopeError("evidence_compacted compacted estimate cannot exceed original estimate")

def _validate_evidence_progress(payload: dict[str, Any]) -> None:
    """Validate the server observation without allowing policy and model choices to blur.

    Required ids are the authority-derived control; discretionary ids are the model-derived
    choice. Keeping all three sets explicit makes a replay tell those facts apart.
    """
    if not isinstance(payload, dict):
        raise EnvelopeError("evidence_progress payload must be an object")

    expected = {
        "requiredEvidenceToolIds",
        "satisfiedRequiredEvidenceToolIds",
        "discretionaryEvidenceToolIds",
    }
    if set(payload) != expected:
        raise EnvelopeError(
            "evidence_progress payload must be exactly "
            "{'requiredEvidenceToolIds', 'satisfiedRequiredEvidenceToolIds', "
            "'discretionaryEvidenceToolIds'}; required and discretionary ids cannot be merged"
        )

    values: dict[str, list[str]] = {}
    for field in expected:
        value = payload[field]
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(set(value)) != len(value)
        ):
            raise EnvelopeError(
                f"evidence_progress {field} must be a list of unique non-empty strings"
            )
        values[field] = value

    required = set(values["requiredEvidenceToolIds"])
    satisfied = set(values["satisfiedRequiredEvidenceToolIds"])
    discretionary = set(values["discretionaryEvidenceToolIds"])
    if not satisfied <= required:
        raise EnvelopeError(
            "evidence_progress satisfiedRequiredEvidenceToolIds must be a subset of "
            "requiredEvidenceToolIds"
        )
    if required & discretionary:
        raise EnvelopeError(
            "evidence_progress requiredEvidenceToolIds and discretionaryEvidenceToolIds "
            "must remain disjoint"
        )


def _validate_sensitive_read_recorded(payload: dict[str, Any]) -> None:
    """Validate the session standing-approval audit frame without carrying argument values."""
    if not isinstance(payload, dict):
        raise EnvelopeError("sensitive_read_recorded payload must be an object")
    if set(payload) != {"toolId", "scope", "context"}:
        raise EnvelopeError(
            "sensitive_read_recorded payload must be exactly {'toolId', 'scope', 'context'}"
        )
    tool_id = payload["toolId"]
    if not isinstance(tool_id, str) or not tool_id.strip():
        raise EnvelopeError("sensitive_read_recorded toolId must be a non-empty string")
    if payload["scope"] != "session":
        raise EnvelopeError("sensitive_read_recorded scope must be 'session'")
    context = payload["context"]
    if not isinstance(context, dict) or set(context) != {"argumentKeys"}:
        raise EnvelopeError("sensitive_read_recorded context must contain only argumentKeys")
    keys = context["argumentKeys"]
    if (
        not isinstance(keys, list)
        or any(not isinstance(item, str) or not item.strip() for item in keys)
        or keys != sorted(set(keys))
    ):
        raise EnvelopeError("sensitive_read_recorded argumentKeys must be sorted unique strings")


def _validate_tool_invocation(kind: str, payload: dict[str, Any]) -> None:
    mode = payload.get("mode")
    if mode not in RUN_MODES:
        raise EnvelopeError(
            f"{kind} payload requires mode in {sorted(RUN_MODES)}, got {mode!r}"
        )
    tool_id = payload.get("name") or payload.get("toolId")
    if not isinstance(tool_id, str) or not tool_id.strip():
        raise EnvelopeError(f"{kind} payload requires a tool identity")
    if mode == "execute" and tool_id != "propose_action":
        raise EnvelopeError("only propose_action may have execute mode")


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:20]}"
