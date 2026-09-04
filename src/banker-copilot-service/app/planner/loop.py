"""The planner loop.

Server-side, single-threaded (epic §6.1 — fan-out is Phase 3). Every step it takes emits a
`CopilotEventEnvelope`, so the live trace and the persisted eval trace are the same events by
construction rather than by agreement.

**Two modes, and the service says which one it chose at startup.**

* ``foundry`` — Azure AI Foundry via Agent Framework, pinned to the same versions as
  `ai-service`, used when a project endpoint and model deployment are configured.
* ``deterministic`` — no model. Gathers the evidence the authority policy requires for the
  target action, then proposes. Used for local dev, CI and the tests.

The deterministic planner does not carry its own idea of what evidence an action needs. It
**asks `authority-service`** (`GET /api/authority/policy` → ``actions[].requiredEvidence``),
which reads it from `config/authority-policy.yaml`. A local copy of that list would be a second
statement of an authorization-relevant fact, and `authority-service` would reject a proposal
built from a stale one with 422 anyway.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import structlog

from app.events.bus import RunStream
from app.config import env_with_legacy
from app.stores.sessions import Session, new_artifact
from app.tools.executor import ToolExecutor, ToolInvocationError
from app.tools.propose import AuthorityClient, ProposeRejected
from app.tools.registry import ToolRegistry

logger = structlog.get_logger("banker-copilot-service")

AGENT_ID = "asst_banker_copilot_v1"

try:  # pragma: no cover - exercised only where the Foundry extras are installed
    from agent_framework_foundry import FoundryChatClient  # noqa: F401

    AGENT_FRAMEWORK_AVAILABLE = True
except ImportError:  # pragma: no cover
    FoundryChatClient = None
    AGENT_FRAMEWORK_AVAILABLE = False


def planner_mode() -> str:
    """Which loop will run, decided once and logged.

    Phase 1 lost ten minutes to a dual-mode switch that read an ambient env var and never said
    which branch it took. Every mode decision in this service is named out loud.
    """
    # `FOUNDRY_*` is this repo's convention (ai-service, prompt-eval-service). This service
    # shipped with `AZURE_AI_*`, which the platform lane then wired to match rather than leave
    # the service with no model access — the right call, and the wrong direction to settle in.
    # Both are read; the non-canonical one is reported on /readyz so the convergence is visible
    # instead of permanent.
    endpoint = env_with_legacy("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "").strip()
    deployment = env_with_legacy("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT", "").strip()
    if AGENT_FRAMEWORK_AVAILABLE and endpoint and deployment:
        return "foundry"
    return "deterministic"


@dataclass
class PlannerRequest:
    session: Session
    run_id: str
    objective: str
    action_id: str | None
    payload: dict[str, Any]
    facts: dict[str, Any]
    bearer_token: str
    correlation_id: str | None = None


class Planner:
    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        authority: AuthorityClient,
        max_iterations: int,
        store=None,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._authority = authority
        self._max_iterations = max_iterations
        self._store = store

    async def run(self, request: PlannerRequest, stream: RunStream) -> None:
        started = time.monotonic()
        artifact_ids: list[str] = []
        status = "completed"

        await stream.emit(
            "run.started",
            {
                "taskId": request.run_id,
                "title": request.objective[:120],
                "intent": request.objective,
                "actor": {
                    "id": request.session.actor_id,
                    "username": request.session.actor_username,
                },
                "startedAt": _now(),
            },
        )

        try:
            evidence_tools = await self._required_evidence(request)
            steps = _plan_steps(evidence_tools, request.action_id)

            await stream.emit("plan.proposed", {"version": 1, "steps": steps})

            evidence: dict[str, Any] = {}
            for index, step in enumerate(steps):
                if index >= self._max_iterations:
                    await stream.emit(
                        "run.error",
                        {
                            "code": "iteration_cap",
                            "message": (
                                "Planner hit its configured iteration cap "
                                f"({self._max_iterations}) before finishing."
                            ),
                            "recoverable": False,
                        },
                    )
                    status = "failed"
                    break

                await stream.emit(
                    "step.started",
                    {"stepId": step["id"], "index": step["index"], "title": step["title"]},
                )
                step_started = time.monotonic()

                if step["kind"] == "tool":
                    ok = await self._run_tool_step(request, stream, step, evidence)
                    if not ok:
                        status = "failed"
                        await stream.emit(
                            "step.failed",
                            {
                                "stepId": step["id"],
                                "error": "evidence gathering failed",
                                "willRetry": False,
                            },
                        )
                        break
                elif step["kind"] == "artifact":
                    artifact = new_artifact(
                        run_id=request.run_id,
                        session_id=request.session.id,
                        kind="evidence_bundle",
                        title="Evidence gathered",
                        content=evidence,
                    )
                    artifact_ids.append(artifact.id)
                    # Persist BEFORE emitting. An artifact the banker can see in the stream but
                    # cannot retrieve after a reload is worse than one that was never offered:
                    # the pane renders empty and nothing distinguishes that from "no artifacts".
                    if self._store is not None:
                        await self._store.save_artifact(artifact)
                    await stream.emit(
                        "artifact.created",
                        {
                            "artifactId": artifact.id,
                            "kind": artifact.kind,
                            "title": artifact.title,
                            "revision": artifact.revision,
                            "content": artifact.content,
                        },
                    )
                elif step["kind"] == "propose":
                    await self._run_propose_step(request, stream, evidence)

                await stream.emit(
                    "step.completed",
                    {
                        "stepId": step["id"],
                        "durationMs": int((time.monotonic() - step_started) * 1000),
                    },
                )

        except Exception as exc:  # noqa: BLE001 - the trace must record the failure honestly
            status = "failed"
            logger.error("Planner run failed", run_id=request.run_id, error=str(exc))
            await stream.emit(
                "run.error",
                {"code": "planner_error", "message": str(exc), "recoverable": False},
            )

        await stream.emit(
            "run.done",
            {
                "status": status,
                "durationMs": int((time.monotonic() - started) * 1000),
                "finalArtifactIds": artifact_ids,
                # finalSeq counts itself: the client asserts it saw every seq up to and
                # including this frame, so an off-by-one here reads as a permanent gap.
                "finalSeq": stream.last_seq + 1,
            },
        )

    async def _required_evidence(self, request: PlannerRequest) -> list[str]:
        """Ask authority-service what this action requires. Never guess, never cache a copy."""
        if not request.action_id:
            return []

        catalogue = await self._authority.policy_catalogue(request.bearer_token)
        for action in catalogue.get("actions") or []:
            if action.get("id") == request.action_id:
                required = action.get("requiredEvidence") or []
                # An evidence id that is not a registered tool is a real seam defect: the
                # policy would demand proof the harness has no way to obtain.
                unknown = sorted(set(required) - self._registry.tool_ids)
                if unknown:
                    logger.warning(
                        "Authority policy requires evidence with no registered tool",
                        action_id=request.action_id,
                        missing=unknown,
                    )
                return [tool_id for tool_id in required if tool_id in self._registry.tool_ids]
        return []

    async def _run_tool_step(
        self,
        request: PlannerRequest,
        stream: RunStream,
        step: dict[str, Any],
        evidence: dict[str, Any],
    ) -> bool:
        tool_id = step["toolId"]
        tool = self._registry.get(tool_id)
        if tool is None:
            return False

        arguments = _bind_arguments(tool.parameters, request)
        call_id = f"call_{stream.last_seq + 1}"

        await stream.emit(
            "tool.started",
            {
                "toolCallId": call_id,
                "stepId": step["id"],
                "name": tool_id,
                "args": arguments,
                "attempt": 1,
            },
        )

        try:
            result = await self._executor.invoke(tool_id, arguments, request.bearer_token)
        except ToolInvocationError as exc:
            await stream.emit(
                "tool.failed",
                {
                    "toolCallId": call_id,
                    "error": f"{exc.code}: {exc.message}",
                    "attempt": 1,
                    "willRetry": False,
                },
            )
            return False

        evidence[tool_id] = result.data
        await stream.emit(
            "tool.completed",
            {
                "toolCallId": call_id,
                "durationMs": result.duration_ms,
                "resultSummary": result.summary(),
                "result": result.data,
            },
        )
        return True

    async def _run_propose_step(
        self, request: PlannerRequest, stream: RunStream, evidence: dict[str, Any]
    ) -> None:
        try:
            outcome = await self._authority.propose(
                {
                    "actionId": request.action_id,
                    "payload": request.payload,
                    "evidence": evidence,
                    "facts": request.facts,
                    "agentAssessment": {
                        "summary": request.objective,
                        "evidenceToolIds": sorted(evidence.keys()),
                    },
                },
                bearer_token=request.bearer_token,
                session_id=request.session.id,
                agent_id=AGENT_ID,
                correlation_id=request.correlation_id,
            )
        except ProposeRejected as exc:
            await stream.emit(
                "run.error",
                {"code": exc.code, "message": exc.message, "recoverable": False},
            )
            return

        if not outcome.admitted:
            await stream.emit(
                "run.error",
                {
                    "code": outcome.body.get("error", "propose_refused"),
                    "message": outcome.body.get("message", "authority-service refused the proposal"),
                    "recoverable": outcome.status_code == 422,
                },
            )
            return

        body = outcome.body
        await stream.emit(
            "approval.required",
            {
                "request": body,
                # Copied from the approval, never re-derived from whatever policy happens to be
                # live at emit time. §8.0: that default would be invisible in normal operation
                # and wrong exactly during a policy change, which is the case #333 most needs.
                "policyVersion": body.get("policyVersion"),
                "requiredRung": body.get("requiredRung"),
                "baseRung": body.get("baseRung"),
                "requiredSigners": body.get("requiredSigners"),
                "payloadHash": body.get("payloadHash"),
            },
        )


def _plan_steps(evidence_tools: list[str], action_id: str | None) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for tool_id in evidence_tools:
        index = len(steps)
        steps.append(
            {
                "id": f"step_{index + 1}",
                "index": index,
                "title": f"Gather evidence: {tool_id}",
                "status": "pending",
                "kind": "tool",
                "toolId": tool_id,
            }
        )

    index = len(steps)
    steps.append(
        {
            "id": f"step_{index + 1}",
            "index": index,
            "title": "Assemble evidence bundle",
            "status": "pending",
            "kind": "artifact",
        }
    )

    if action_id:
        index = len(steps)
        steps.append(
            {
                "id": f"step_{index + 1}",
                "index": index,
                "title": f"Propose {action_id} for human signature",
                "status": "pending",
                "kind": "propose",
            }
        )

    return steps


def _bind_arguments(schema: dict[str, Any], request: PlannerRequest) -> dict[str, Any]:
    """Fill a tool's declared parameters from the session context, payload and facts.

    Only declared parameters are bound. The schema sets ``additionalProperties: false``, so an
    unbound extra would be rejected by validation rather than forwarded upstream.
    """
    sources: dict[str, Any] = {}
    sources.update(request.session.context or {})
    sources.update(request.payload or {})
    sources.update(request.facts or {})

    bound: dict[str, Any] = {}
    for name in (schema.get("properties") or {}):
        if name in sources and sources[name] is not None:
            bound[name] = sources[name]
    return bound


def _now() -> str:
    from app.events.envelope import utc_now_iso

    return utc_now_iso()
