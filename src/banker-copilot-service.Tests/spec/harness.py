"""A minimal agent loop, so "nothing executed" can be asserted over a whole run.

The interesting tests in Phase 2 are negatives: after a complete turn — plan,
tool calls, a proposal, an artifact — **zero mutating requests left the
harness**. That claim needs something to run. This is the smallest thing that
counts as a run.

The "model" is a scripted list of actions, which is a feature rather than a
limitation: a real LLM cannot be made to attempt the specific attacks that
matter (name an unregistered tool, act on an instruction injected into a tool
result, ask for an approval to be executed). A script can attempt all of them
deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .envelope import Run, SessionId, TraceEmitter
from .registry import (
    DomainReadTransport,
    ProposeActionTool,
    ReadTool,
    ToolRegistrationRefused,
    ToolRegistry,
)


class UnknownToolCalled(ToolRegistrationRefused):
    """The model named something that is not a registered tool."""


@dataclass
class ScriptedStep:
    tool: str
    args: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class Harness:
    registry: ToolRegistry
    emitter: TraceEmitter
    transport: DomainReadTransport
    bearer: str

    def run_turn(
        self,
        session: SessionId,
        run: Run,
        steps: list[ScriptedStep],
        trace_id: str = "trace-0001",
    ) -> list[Any]:
        results: list[Any] = []
        self.emitter.emit(
            run,
            "run.started",
            {"taskId": "task-1", "title": "turn", "intent": "review", "actor": {"id": "banker-1"},
             "startedAt": "2026-09-04T00:00:00Z"},
        )

        for index, step in enumerate(steps, start=1):
            tool = self._resolve(step.tool)
            self.emitter.emit(
                run,
                "tool.started",
                {
                    "toolCallId": f"call-{index}",
                    "stepId": f"step-{index}",
                    "name": step.tool,
                    "attempt": 1,
                    "traceId": trace_id,
                    "spanId": f"span-{index:04d}",
                },
            )
            if isinstance(tool, ProposeActionTool):
                result = tool(
                    actionId=step.args["actionId"],
                    payload=step.args.get("payload", {}),
                    evidenceRefs=step.args.get("evidenceRefs", {}),
                    bearer=self.bearer,
                )
            else:
                result = tool(step.args, self.bearer)
            results.append(result)
            self.emitter.emit(
                run,
                "tool.completed",
                {
                    "toolCallId": f"call-{index}",
                    "durationMs": 1,
                    "traceId": trace_id,
                    "spanId": f"span-{index:04d}",
                    "resultSummary": "ok",
                },
            )

        self.emitter.emit(
            run,
            "run.done",
            {
                "status": "completed",
                "durationMs": 2,
                "finalArtifactIds": [],
                "finalSeq": self.emitter.next_seq(run),
            },
        )
        return results

    def _resolve(self, tool_id: str) -> Any:
        try:
            tool = self.registry.get(tool_id)
        except ToolRegistrationRefused as exc:
            raise UnknownToolCalled(str(exc)) from exc
        if not isinstance(tool, (ReadTool, ProposeActionTool)):
            raise UnknownToolCalled(f"'{tool_id}' resolved to something uncallable")
        return tool
