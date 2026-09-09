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
from dataclasses import dataclass, field
from typing import Any, Sequence

import structlog

from app.events.bus import RunStream
from app.config import ConfigurationError, env_with_legacy
from app.stores.sessions import Session, new_artifact
from app.tools.executor import ToolExecutor, ToolInvocationError
from app.tools.propose import AuthorityClient, ProposeRejected
from app.tools.registry import ToolRegistry
from app.planner.approval_view import primary_proposal_assessment, primary_wire_assessment
from app.planner.evidence_ceiling import (
    ITERATIONS_EXHAUSTED,
    READ_REFUSED_403,
    RefusedEvidenceRequest,
    additional_evidence,
)
from app.planner.limits import AssessmentLimits
from app.planner.primary_model import PrimaryAssessment, unavailable

logger = structlog.get_logger("banker-copilot-service")

AGENT_ID = "asst_banker_copilot_v1"

try:  # pragma: no cover - exercised only where the Foundry extras are installed
    from agent_framework_foundry import FoundryChatClient  # noqa: F401

    AGENT_FRAMEWORK_AVAILABLE = True
except ImportError:  # pragma: no cover
    FoundryChatClient = None
    AGENT_FRAMEWORK_AVAILABLE = False


PLANNER_MODES = ("foundry", "deterministic")

#: §P6. Declared, never inferred, logged at startup, ONE call site, one named function.
#:
#: `propose` (the default and the ruled-correct behaviour): the primary proposes even when its
#: own assessment is adverse. An agent that declines to propose has DISPOSED — it has exercised a
#: veto the authority ladder never granted it, and it exercises it invisibly, because the banker
#: gets an empty screen rather than a denial. Worse, the banker still needs to act, so the refusal
#: relocates the work to the admin tabs, which are reachable, role-authorized and leave no audit
#: record. An adverse proposal on the governed path is strictly better than a silent refusal that
#: routes around it — and the card's two-position comparison only exists if there are two
#: positions.
#:
#: `withhold` exists so Brian can SEE that behaviour, not because it is close. A withheld proposal
#: ends the run `failed` with `primary_declined`: no approval was admitted, and status is derived
#: from that, so flipping this seam cannot reintroduce the completed-on-no-approval lie by a new
#: door.
ADVERSE_PROPOSAL_MODES = ("propose", "withhold")


def adverse_proposal_mode() -> str:
    mode = (os.getenv("COPILOT_ADVERSE_PROPOSAL") or "propose").strip().lower()
    if mode not in ADVERSE_PROPOSAL_MODES:
        raise ConfigurationError(
            f"COPILOT_ADVERSE_PROPOSAL={mode!r} is not one of {ADVERSE_PROPOSAL_MODES}. "
            "This setting is declared, never inferred: guessing it would decide whether a banking "
            "action reaches a human at all."
        )
    return mode


def planner_mode() -> str:
    """Which loop will run, decided once and logged.

    Phase 1 lost ten minutes to a dual-mode switch that read an ambient env var and never said
    which branch it took. Every mode decision in this service is named out loud.

    The mode is *declared*, never inferred. This function used to return ``"deterministic"``
    whenever the Foundry preconditions were not all met, which collapsed three unrelated
    failures — the ``agent_framework_foundry`` extra missing from the image, an unset endpoint,
    an unset model — into one indistinguishable success. A deployment that had lost its model
    access reported ``status: ready`` and answered questions with no model behind it. Reviewers
    checking supervisor disagreement would have been measuring a script and reading it as
    agreement. Failure looked exactly like success.

    So deterministic is now reachable only because somebody typed it. Asking for ``foundry``
    (the default) with incomplete configuration raises, and names the part that is missing.
    """
    requested = os.getenv("COPILOT_PLANNER_MODE", "").strip().lower() or "foundry"
    if requested not in PLANNER_MODES:
        raise ConfigurationError(
            f"COPILOT_PLANNER_MODE={requested!r} is not a planner mode. "
            f"Expected one of {', '.join(PLANNER_MODES)}."
        )

    if requested == "deterministic":
        # An explicit choice — local development and tests run here. Nothing to verify: the
        # deterministic planner needs no model. It is returned because it was asked for.
        return "deterministic"

    # `FOUNDRY_*` is this repo's convention (ai-service, prompt-eval-service). This service
    # shipped with `AZURE_AI_*`, which the platform lane then wired to match rather than leave
    # the service with no model access — the right call, and the wrong direction to settle in.
    # Both are read; the non-canonical one is reported on /readyz so the convergence is visible
    # instead of permanent.
    endpoint = env_with_legacy("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "").strip()
    deployment = env_with_legacy("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT", "").strip()

    missing: list[str] = []
    if not AGENT_FRAMEWORK_AVAILABLE:
        missing.append("the agent_framework_foundry package is not importable in this image")
    if not endpoint:
        missing.append("FOUNDRY_PROJECT_ENDPOINT is unset")
    if not deployment:
        missing.append("FOUNDRY_MODEL is unset")

    if missing:
        raise ConfigurationError(
            "COPILOT_PLANNER_MODE=foundry, but the planner cannot reach a model: "
            + "; ".join(missing)
            + ". Set COPILOT_PLANNER_MODE=deterministic to run without a model deliberately."
        )

    return "foundry"


@dataclass(frozen=True)
class ProposeStepResult:
    """What the propose step achieved, and separately, whether its error admits a repair.

    Two facts, deliberately not collapsed into one:

    * ``approval`` — did this step produce something a human can actually sign? This, and
      only this, is what the run's terminal status turns on.
    * ``recoverable`` — does the error the step hit *admit* a repair (a re-canonicalised
      payload, a re-read)? That describes the **error**, never what the planner **did**
      about it.

    Deriving the run's status from ``recoverable`` would plant the same bug in a new place.
    A recoverable refusal that nobody actually recovered from still leaves the banker with
    no proposal, and reporting that as ``completed`` is the lie being fixed here. So a
    recoverable error keeps the run alive only if a repair attempt then *succeeds* and sets
    ``approval``. The deterministic planner has no repair strategy today — the seam where
    one belongs is marked at the call site — so both kinds currently end the run failed, but
    they end it for visibly different reasons and ``run.error`` still carries the flag.
    """

    approval: dict[str, Any] | None = None
    error_code: str | None = None
    recoverable: bool = False

    @property
    def admitted(self) -> bool:
        return self.approval is not None


@dataclass
class _RunOutcome:
    """The run's terminal status, *derived* from what the run achieved.

    ``status`` used to be a local initialised to ``"completed"`` that only paths which
    remembered to would lower. That default is the whole defect: every terminal path
    inherited success for free, so the one path that forgot (a refused proposal) emitted
    ``run.done status: "completed"`` on an unrecoverable error — failure wearing the
    costume of success, sitting on the field every harness and dashboard trusts first.

    Here a run starts having achieved nothing and success must be *earned*: either the
    proposal the objective asked for was admitted, or the objective never asked for one.
    A new terminal path added later inherits failure, not success.
    """

    #: True when the plan contains a propose step — i.e. the run's purpose is to put an
    #: approval in front of a human. False for an evidence-only run (no ``action_id``),
    #: which is a deliberate no-op outcome and legitimately completes without an approval.
    proposal_expected: bool
    proposal_admitted: bool = False
    #: Set by paths that abort the plan outright: tool/evidence failure, the iteration cap,
    #: or an unhandled exception.
    aborted: bool = False

    @property
    def status(self) -> str:
        if self.aborted:
            return "failed"
        if self.proposal_expected and not self.proposal_admitted:
            return "failed"
        return "completed"


@dataclass
class _AssessmentRecord:
    """What the harness OBSERVED about the assessment loop, kept apart from what the model claimed.

    Every field here is server-derived (§P5.5). The model's requests are its claim; these are the
    observation, and the two must never be blurred into one list — ``requiredEvidenceToolIds`` is a
    CONTROL and ``discretionaryEvidenceToolIds`` is a CHOICE, and "the copilot reviewed the
    account" must not mean something different run to run while reading identically.
    """

    required_evidence_tool_ids: tuple[str, ...]
    discretionary_evidence_tool_ids: list[str] = field(default_factory=list)
    refused: list[RefusedEvidenceRequest] = field(default_factory=list)
    iterations: int = 0
    #: A POSITIVE recorded fact, never an absence. Without it, "hit the cap while still
    #: unsatisfied" and "was satisfied on the first pass" read identically — a broken path
    #: looking like a working one, which is the defect class this feature keeps producing.
    #: It starts False and is EARNED, in the same spirit as `_RunOutcome.status`.
    converged: bool = False
    assessment: PrimaryAssessment = field(
        default_factory=lambda: unavailable(
            "primary_never_assessed",
            "no assessment step ran on this plan",
        )
    )

    def refuse(self, tool_id: str, reason: str) -> None:
        self.refused.append(RefusedEvidenceRequest(tool_id, reason))

    @property
    def refusals_wire(self) -> list[dict[str, str]]:
        return [r.to_wire() for r in self.refused]


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
        assessment_limits: AssessmentLimits,
        assessor,
        store=None,
        fanout=None,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._authority = authority
        self._max_iterations = max_iterations
        # Both required, neither defaulted. A default budget here would be a second home for a
        # number whose only home is `config/harness-limits.yaml` (invariant I-3), and a default
        # assessor would be the exact failure this feature exists to end: a planner that quietly
        # runs without a judgement and looks identical to one that has one.
        self._assessment_limits = assessment_limits
        self._assessor = assessor
        self._adverse_proposal = adverse_proposal_mode()
        self._store = store
        # The Phase 3 fan-out engine. Optional so the single-threaded planner (and every
        # test that never reaches L2) is unchanged; when present, an L2 proposal triggers
        # the ONE mandatory fan-out — the blind independent second opinion (§6.2/§6.4).
        self._fanout = fanout

    async def run(self, request: PlannerRequest, stream: RunStream) -> None:
        started = time.monotonic()
        artifact_ids: list[str] = []
        # Success is earned, never defaulted. `proposal_expected` is set the moment the plan
        # is known, a few lines below.
        outcome = _RunOutcome(proposal_expected=bool(request.action_id))

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
            # The plan is the authority on what this run set out to do. Reading it here (rather
            # than trusting the request) means a plan that silently dropped its propose step
            # cannot report success for a signature it never sought.
            outcome.proposal_expected = any(step["kind"] == "propose" for step in steps)

            await stream.emit("plan.proposed", {"version": 1, "steps": steps})

            evidence: dict[str, Any] = {}
            record = _AssessmentRecord(required_evidence_tool_ids=tuple(evidence_tools))
            # The plan is now a MUTABLE list walked by position, because the assess step may
            # insert discretionary reads into it (§P5.2). They are inserted as ORDINARY tool
            # steps, so they inherit the iteration cap below without a new bound being invented:
            # two independent ceilings, one of them already shipped and tested, is worth more
            # than one carefully-argued new one.
            plan_version = 1
            next_step_number = len(steps) + 1
            position = 0
            executed = 0
            while position < len(steps):
                step = steps[position]
                position += 1
                index = executed
                executed += 1
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
                    outcome.aborted = True
                    break

                await stream.emit(
                    "step.started",
                    {"stepId": step["id"], "index": step["index"], "title": step["title"]},
                )
                step_started = time.monotonic()

                if step["kind"] == "tool":
                    ok = await self._run_tool_step(request, stream, step, evidence)
                    if not ok and step.get("discretionary"):
                        # A discretionary read that fails does NOT fail the run. It was never
                        # required, so the plan is no worse off than if the model had not asked.
                        # It is recorded as a refused read, because otherwise the record cannot
                        # distinguish "did not look" from "was not allowed to look" — and it has
                        # already spent its budget, which bounds a model that would otherwise
                        # enumerate the 403s to learn the session's authority surface.
                        record.refuse(step["toolId"], READ_REFUSED_403)
                        await stream.emit(
                            "step.failed",
                            {
                                "stepId": step["id"],
                                "error": "discretionary read refused",
                                "willRetry": False,
                            },
                        )
                        continue
                    if not ok:
                        # Belt and braces: a tool step only exists when the run has an
                        # `action_id`, so the plan also contains a propose step this break
                        # skips — the outcome would read failed on that alone. Stated
                        # anyway, because "correct via a fact about another step" is how a
                        # path ends up depending on something nobody meant it to.
                        outcome.aborted = True
                        await stream.emit(
                            "step.failed",
                            {
                                "stepId": step["id"],
                                "error": "evidence gathering failed",
                                "willRetry": False,
                            },
                        )
                        break
                elif step["kind"] == "assess":
                    granted = await self._run_assess_step(request, stream, step, evidence, record)
                    if granted:
                        added, next_step_number = _insert_discretionary_steps(
                            steps, position, granted, next_step_number
                        )
                        plan_version += 1
                        record.discretionary_evidence_tool_ids.extend(granted)
                        await stream.emit(
                            "plan.revised",
                            {
                                "version": plan_version,
                                "at": _now(),
                                # Says WHOSE choice this was. The trace titles these steps
                                # differently too (§P5.5): a control and a choice must never read
                                # identically on screen.
                                "reason": (
                                    "The agent asked for additional evidence beyond what the "
                                    "policy requires."
                                ),
                                "addedStepIds": added,
                                # Nothing is ever removed by a revision here. The ceiling is
                                # strictly additive; a revision that could drop a required step
                                # would be the evidence floor moving, which is the one thing
                                # this whole design prevents by construction.
                                "removedStepIds": [],
                                "steps": [
                                    {
                                        "id": s["id"],
                                        "index": s["index"],
                                        "title": s["title"],
                                        "status": s["status"],
                                    }
                                    for s in steps
                                ],
                            },
                        )
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
                    if not _proposal_permitted(self._adverse_proposal, record.assessment):
                        # §P6, the seam, at its ONE call site. Default `propose` never lands here.
                        await stream.emit(
                            "run.error",
                            {
                                "code": "primary_declined",
                                "message": (
                                    "The primary agent's assessment was adverse and "
                                    "COPILOT_ADVERSE_PROPOSAL=withhold, so no proposal was put to "
                                    "a human. The action is not prevented — it is relocated to a "
                                    "path that leaves no audit record."
                                ),
                                "recoverable": False,
                            },
                        )
                        await stream.emit(
                            "step.failed",
                            {
                                "stepId": step["id"],
                                "error": "primary_declined",
                                "willRetry": False,
                            },
                        )
                        break
                    result = await self._run_propose_step(request, stream, evidence, record)
                    if not result.admitted:
                        # This step exists for one reason: to put an approval in front of a
                        # human. It produced none, so it did not do its job, and emitting
                        # `step.completed` here would dress the failure as success — which is
                        # precisely how run_6f19b2eb4ec54a20 came to report
                        # `run.done status: "completed"` after refusing a non-canonical
                        # `amount`. The step is marked failed and the plan stops.
                        #
                        # A repair loop for `result.recoverable` belongs HERE: re-enter the
                        # propose step with an adjusted payload and fall through to the
                        # admitted branch if it then succeeds. There is no such loop today, so
                        # `willRetry` says false rather than implying an attempt that never
                        # happens, and the run ends failed either way — a refusal nobody
                        # recovered from is still a run with no proposal in it. The
                        # recoverable/unrecoverable distinction is preserved where it is
                        # actionable: on the `run.error` frame already emitted.
                        await stream.emit(
                            "step.failed",
                            {
                                "stepId": step["id"],
                                "error": result.error_code or "propose_refused",
                                "willRetry": False,
                            },
                        )
                        break

                    outcome.proposal_admitted = True
                    body = result.approval
                    # §6.2: an L2 proposal triggers the ONE mandatory fan-out — a blind,
                    # independent second opinion. L1 never fans out (batching/duplicating a
                    # second opinion defeats it). The engine is absent in single-threaded
                    # deployments, so guard on its presence.
                    if self._fanout is not None and body.get("requiredRung") == "L2":
                        await self._fanout.run_second_opinion(
                            request,
                            stream,
                            body,
                            # §P5.7. The supervisor's independent draw is defined by THE ACTION
                            # UNDER REVIEW — policy — not by what the primary happened to gather.
                            # It used to be handed `evidence`, and the day discretionary reads
                            # landed in that dict the second draw would silently have widened to
                            # follow the primary's choices: blindness defeated by a data-flow
                            # change in a module that never mentions the supervisor.
                            required_evidence_tool_ids=record.required_evidence_tool_ids,
                            parent_step_id=step["id"],
                        )

                await stream.emit(
                    "step.completed",
                    {
                        "stepId": step["id"],
                        "durationMs": int((time.monotonic() - step_started) * 1000),
                    },
                )

        except Exception as exc:  # noqa: BLE001 - the trace must record the failure honestly
            outcome.aborted = True
            logger.error("Planner run failed", run_id=request.run_id, error=str(exc))
            await stream.emit(
                "run.error",
                {"code": "planner_error", "message": str(exc), "recoverable": False},
            )

        await stream.emit(
            "run.done",
            {
                # Derived from what the run achieved (see `_RunOutcome`), never a default
                # that each terminal path has to remember to lower.
                "status": outcome.status,
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

    async def _run_assess_step(
        self,
        request: PlannerRequest,
        stream: RunStream,
        step: dict[str, Any],
        evidence: dict[str, Any],
        record: _AssessmentRecord,
    ) -> tuple[str, ...]:
        """Ask the primary to JUDGE the evidence, and decide which extra reads it may have.

        Returns the tool ids granted — empty on every pass at budget 0, which is stage 1.

        **Everything below runs at every budget.** The prompt is the same constant, the reply goes
        through the same parser, the requests are recorded, and `additional_evidence` is called and
        returns empty. There is no `if budget:` here and there must never be one: a branch would
        mean stage 1 measured a code path that never ships, which is this feature's signature
        defect (§P5.1). The only edge stage 1 does not traverse is the executor invoking an extra
        tool — and the executor is traversed on every run anyway by the required evidence.
        """
        assessment = await self._assessor(
            request.objective, request.action_id, request.payload, evidence
        )
        record.iterations += 1
        record.assessment = assessment

        pass_number = record.iterations
        final_pass = pass_number >= self._assessment_limits.max_assessment_iterations

        bindable = tuple(
            tool_id
            for tool_id in self._registry.tool_ids
            if _is_bindable(self._registry.get(tool_id), request)
        )
        granted, refused = additional_evidence(
            assessment.requested_evidence,
            gathered=evidence.keys(),
            known_tool_ids=self._registry.tool_ids,
            bindable_tool_ids=bindable,
            # On the last permitted pass the budget is not consulted for granting, because there
            # is no gathering step left to run — see the re-classification below. Retrying past
            # `maxAssessmentIterations`, in any form including a "just one more" special case, is
            # refused (§P5.6).
            budget=0 if final_pass else self._remaining_budget(record),
        )
        if final_pass and granted:  # pragma: no cover - unreachable while budget is forced to 0
            granted = ()
        if final_pass:
            # Reported as what it is. Calling this `budget_exhausted` would report unspent budget
            # as spent and corrupt the one number stage 1 exists to produce.
            refused = tuple(
                RefusedEvidenceRequest(r.tool_id, ITERATIONS_EXHAUSTED)
                if r.reason == "budget_exhausted"
                else r
                for r in refused
            )
        record.refused.extend(refused)

        # EARNED, never defaulted: the primary formed a position AND asked for nothing further,
        # i.e. it stopped because it was satisfied. A failed assessment did not converge — it
        # failed — and a request nobody could honour did not converge either.
        record.converged = assessment.formed and not assessment.requested_evidence

        await stream.emit(
            "step.completed",
            {
                "stepId": step["id"],
                "durationMs": 0,
                "summary": _assessment_summary(assessment),
                # §P7.1: the raw reply lives on the EVENT STREAM, joined by sessionId and
                # correlationId, and never on the approval. The approval carries the structural
                # fields and the two hashes that tie them to this reply.
                "rawReply": assessment.raw_reply,
                "assessmentPass": pass_number,
            },
        )
        return granted

    def _remaining_budget(self, record: _AssessmentRecord) -> int:
        """PER-RUN, not per-iteration: two passes cannot spend the budget each."""
        return self._assessment_limits.per_run_additional_tool_budget - len(
            record.discretionary_evidence_tool_ids
        )

    async def _run_propose_step(
        self,
        request: PlannerRequest,
        stream: RunStream,
        evidence: dict[str, Any],
        record: _AssessmentRecord,
    ) -> ProposeStepResult:
        """Propose the action for human signature.

        Returns a :class:`ProposeStepResult` that says both what was admitted (if anything)
        and whether the refusal admits a repair. It used to return the approval body or a
        bare ``None``, and the caller treated ``None`` as "nothing to fan out from" and
        nothing more — so a refusal was indistinguishable from a run that simply had no L2
        second opinion to gather, and the loop marched on to `step.completed`.
        """
        try:
            outcome = await self._authority.propose(
                {
                    "actionId": request.action_id,
                    "payload": request.payload,
                    "evidence": evidence,
                    "facts": request.facts,
                    # The primary's OWN judgement, and the harness's own observations about how
                    # it was reached. This used to be `{"summary": request.objective}` — the
                    # banker's words echoed back — which the wire adapter then dressed in a
                    # defaulted "proceed". The card rendered a verdict no agent had produced.
                    "agentAssessment": primary_proposal_assessment(
                        record.assessment,
                        required_evidence_tool_ids=record.required_evidence_tool_ids,
                        discretionary_evidence_tool_ids=record.discretionary_evidence_tool_ids,
                        refused_evidence_requests=record.refusals_wire,
                        assessment_iterations=record.iterations,
                        converged=record.converged,
                    ),
                },
                bearer_token=request.bearer_token,
                session_id=request.session.id,
                agent_id=AGENT_ID,
                correlation_id=request.correlation_id,
            )
        except ProposeRejected as exc:
            # Refused before it ever left this service: the payload could not be
            # canonicalised. Nothing upstream was consulted and nothing here can repair it.
            await stream.emit(
                "run.error",
                {"code": exc.code, "message": exc.message, "recoverable": False},
            )
            return ProposeStepResult(error_code=exc.code, recoverable=False)

        if not outcome.admitted:
            recoverable = outcome.status_code == 422
            code = outcome.body.get("error", "propose_refused")
            await stream.emit(
                "run.error",
                {
                    "code": code,
                    "message": outcome.body.get("message", "authority-service refused the proposal"),
                    "recoverable": recoverable,
                },
            )
            return ProposeStepResult(error_code=code, recoverable=recoverable)

        body = outcome.body
        # Shipped contract: ApprovalRequiredPayload = { approval: Approval, policyVersion,
        # requiredRung } (ui-app types.ts). The reducer reads `event.payload.approval` — emitting
        # the old `{request: body}` left `p.approval` undefined and threw a TypeError on the FIRST
        # approval of every run. The value is the authoritative WIRE body; the single mapper
        # `authorityWire.toApproval` turns it into the client Approval (see decision record — the
        # SSE path must route through that one mapper, exactly as the REST path does). We enrich
        # only the primary's assessment with a renderable `verdict`, derived from its own declared
        # recommendation; nothing is re-derived from the primary's private reasoning.
        emitted = dict(body)
        if isinstance(body.get("agentAssessment"), dict):
            emitted["agentAssessment"] = primary_wire_assessment(body)
        await stream.emit(
            "approval.required",
            {
                "approval": emitted,
                # Copied from the approval, never re-derived from whatever policy happens to be
                # live at emit time. §8.0: that default would be invisible in normal operation
                # and wrong exactly during a policy change, which is the case #333 most needs.
                "policyVersion": body.get("policyVersion"),
                "requiredRung": body.get("requiredRung"),
            },
        )
        return ProposeStepResult(approval=body)


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

    if action_id:
        # §P5.2, invariant 1: the required evidence above is gathered FIRST and
        # UNCONDITIONALLY, before the model is consulted at all. Ordering is the control — if the
        # model is never asked until the required set is in hand, then a model failure, a timeout
        # or a garbage reply CANNOT reduce evidence below policy. There is nothing to validate,
        # because there is no sequence in which it happens.
        index = len(steps)
        steps.append(
            {
                "id": f"step_{index + 1}",
                "index": index,
                "title": "Assess the evidence",
                "status": "pending",
                "kind": "assess",
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


DISCRETIONARY_STEP_TITLE = "Additional check (agent's choice): {tool_id}"
REASSESS_STEP_TITLE = "Re-assess with the additional evidence"


def _insert_discretionary_steps(
    steps: list[dict[str, Any]],
    position: int,
    granted: Sequence[str],
    next_step_number: int,
) -> tuple[list[str], int]:
    """Splice the granted reads, plus one more assess pass, into the live plan.

    Titled distinctly on purpose (§P5.5). A required read and a discretionary one must never read
    identically in the trace: one is the policy's control and the other is the model's choice, and
    blurring them is the same error as merging the two id lists on the record.

    Step ids are drawn from a counter that never rewinds, so an id always means the same step for
    the life of the run — the UI upserts plan steps by id, and a reused id would silently rewrite
    a step the banker already watched run.
    """
    added: list[str] = []
    inserted: list[dict[str, Any]] = []
    for tool_id in granted:
        inserted.append(
            {
                "id": f"step_{next_step_number}",
                "index": 0,
                "title": DISCRETIONARY_STEP_TITLE.format(tool_id=tool_id),
                "status": "pending",
                "kind": "tool",
                "toolId": tool_id,
                "discretionary": True,
            }
        )
        added.append(f"step_{next_step_number}")
        next_step_number += 1

    inserted.append(
        {
            "id": f"step_{next_step_number}",
            "index": 0,
            "title": REASSESS_STEP_TITLE,
            "status": "pending",
            "kind": "assess",
        }
    )
    added.append(f"step_{next_step_number}")
    next_step_number += 1

    steps[position:position] = inserted
    for i, step in enumerate(steps):
        # Positional, so the trace renders in the order things actually happened. Ids are stable;
        # only the index moves.
        step["index"] = i
    return added, next_step_number


def _is_bindable(tool, request: PlannerRequest) -> bool:
    """Can this tool's REQUIRED parameters be filled from the banker's own inputs?

    The model names a tool id and never an argument (§P5.3). A tool whose required parameters
    cannot be bound from the session context, payload and facts is refused as unbindable rather
    than invented — the same rule as §R5: nobody may stamp a subject onto evidence. This is the
    sharpest edge in the whole ceiling, because an invented argument could read ANOTHER
    CUSTOMER'S account and file it in this customer's approval record.
    """
    if tool is None:
        return False
    schema = tool.parameters or {}
    required = schema.get("required") or list((schema.get("properties") or {}).keys())
    bound = _bind_arguments(schema, request)
    return all(name in bound for name in required)


def _assessment_summary(assessment) -> str:
    if assessment.formed:
        return f"Primary assessment: {assessment.verdict}"
    return f"No assessment formed: {assessment.failure_reason or assessment.failure}"


def _proposal_permitted(mode: str, assessment) -> bool:
    """§P6's ONE decision point. Under the default `propose`, this is always True."""
    if mode == "propose":
        return True
    return assessment.verdict != "decline"


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
