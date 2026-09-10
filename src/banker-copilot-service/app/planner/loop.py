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
import re
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

import jsonschema
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
from app.planner.intent_model import (
    EvidenceAnswer,
    INTENT_CONTRACT_INVALID,
    IntentDecision,
    PLANNER_MODEL_UNAVAILABLE,
)
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


@dataclass(frozen=True)
class _ActionSpec:
    action_id: str
    display_name: str
    base_rung: str
    agent_may_propose: bool
    required_evidence: tuple[str, ...]
    hash_fields: tuple[str, ...]
    money_fields: tuple[str, ...]
    score_override_floor: Decimal | None = None


@dataclass(frozen=True)
class _ReferenceResolution:
    decision: IntentDecision
    evidence: dict[str, Any] = field(default_factory=dict)


class ReferenceResolver:
    """Resolve model hints through read tools; never trust identifier-shaped text directly."""

    def __init__(self, registry: ToolRegistry | None = None, executor: ToolExecutor | None = None):
        self._registry = registry
        self._executor = executor

    async def resolve(self, request: PlannerRequest, decision: IntentDecision) -> _ReferenceResolution:
        if self._executor is None or self._registry is None:
            return _ReferenceResolution(decision=decision)

        draft = dict(decision.payload_draft or {})
        hints = dict(decision.subject_hints or {})
        evidence: dict[str, Any] = {}

        user_hint = _first_present(hints, "customer", "username", "user", "userId") or draft.get("userId")
        if user_hint:
            user = await self._resolve_user(str(user_hint), request.bearer_token)
            if isinstance(user, IntentDecision):
                return _ReferenceResolution(decision=user, evidence=evidence)
            draft["userId"] = user["id"]
            evidence["resolved_subject"] = {
                "query": str(user_hint),
                "matched": {"userId": user["id"], "username": user.get("username"), "displayName": user.get("displayName")},
                "basis": "customer-directory-lookup",
            }

        account_hint = _first_present(hints, "account", "accountType") or draft.get("accountType")
        account_id_hint = _first_present(hints, "accountId") or draft.get("accountId")
        account_number_hint = _first_present(hints, "accountNumber") or draft.get("accountNumber")
        if account_id_hint:
            account = await self._invoke("get_account", {"accountId": str(account_id_hint)}, request.bearer_token)
            if account is None:
                return _ReferenceResolution(
                    decision=_refusal("subject_not_found", "The referenced account could not be resolved for this banker."),
                    evidence=evidence,
                )
            draft["accountId"] = account.get("accountId") or account.get("id") or str(account_id_hint)
            evidence["resolved_account"] = {"query": str(account_id_hint), "matched": {"accountId": draft["accountId"]}, "basis": "account-id-read"}
        elif account_number_hint:
            account = await self._invoke("get_account_by_number", {"accountNumber": str(account_number_hint)}, request.bearer_token)
            if account is None:
                return _ReferenceResolution(
                    decision=_refusal("subject_not_found", "The referenced account could not be resolved for this banker."),
                    evidence=evidence,
                )
            draft["accountId"] = account.get("accountId") or account.get("id")
            evidence["resolved_account"] = {"query": str(account_number_hint), "matched": {"accountId": draft["accountId"]}, "basis": "account-number-read"}
        elif account_hint and draft.get("userId"):
            accounts_doc = await self._invoke("list_customer_accounts", {"userId": str(draft["userId"])}, request.bearer_token)
            accounts = accounts_doc.get("accounts") if isinstance(accounts_doc, Mapping) else accounts_doc
            matches = [
                a for a in (accounts or [])
                if str(a.get("accountType", "")).lower() == str(account_hint).lower()
            ]
            if not matches:
                return _ReferenceResolution(
                    decision=_refusal("subject_not_found", "No account matched the requested account type for the resolved customer."),
                    evidence=evidence,
                )
            if len(matches) > 1:
                return _ReferenceResolution(
                    decision=_refusal("ambiguous_subject", "More than one account matched the requested account type; no account was selected."),
                    evidence=evidence,
                )
            draft["accountId"] = matches[0].get("accountId") or matches[0].get("id")
            evidence["resolved_account"] = {
                "query": str(account_hint),
                "matched": {"accountId": draft["accountId"], "accountType": matches[0].get("accountType")},
                "basis": "customer-account-type",
            }

        if evidence:
            decision = replace(decision, payload_draft=draft)
        return _ReferenceResolution(decision=decision, evidence=evidence)

    async def _resolve_user(self, hint: str, token: str) -> dict[str, Any] | IntentDecision:
        if _looks_like_id(hint):
            user = await self._invoke("get_user", {"userId": hint}, token)
            if user is None:
                return _refusal("subject_not_found", "The referenced customer could not be resolved for this banker.")
            return {
                "id": user.get("id") or user.get("userId") or hint,
                "username": user.get("username") or user.get("Username"),
                "displayName": " ".join(str(user.get(k) or "").strip() for k in ("firstName", "lastName")).strip(),
            }
        doc = await self._invoke("lookup_customer", {"username": hint}, token)
        matches = (doc or {}).get("matches") or []
        if len(matches) == 0:
            return _refusal("subject_not_found", "No customer matched the supplied reference.")
        if len(matches) > 1:
            return _refusal("ambiguous_subject", "More than one customer matched the supplied reference; no customer was selected.")
        return dict(matches[0])

    async def _invoke(self, tool_id: str, arguments: dict[str, Any], token: str) -> Any | None:
        if self._registry.get(tool_id) is None:
            return None
        try:
            return (await self._executor.invoke(tool_id, arguments, token)).data
        except ToolInvocationError:
            return None


class Planner:
    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        authority: AuthorityClient,
        max_iterations: int,
        assessment_limits: AssessmentLimits,
        assessor,
        intent_selector=None,
        answerer=None,
        reference_resolver: ReferenceResolver | None = None,
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
        self._intent_selector = intent_selector
        self._answerer = answerer
        self._reference_resolver = reference_resolver or ReferenceResolver(registry, executor)
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
            if request.action_id:
                evidence_tools = await self._required_evidence(request)
                steps = _plan_steps(evidence_tools, request.action_id)
            else:
                evidence_tools = []
                steps = _free_text_initial_steps()
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

                if step["kind"] == "intent":
                    added, next_step_number, required, proposal_expected = await self._run_intent_step(
                        request, stream, position, steps, next_step_number, evidence
                    )
                    evidence_tools = required
                    record.required_evidence_tool_ids = tuple(required)
                    outcome.proposal_expected = proposal_expected
                    if added:
                        plan_version += 1
                        await stream.emit(
                            "plan.revised",
                            {
                                "version": plan_version,
                                "at": _now(),
                                "reason": "The planner interpreted the free-text objective.",
                                "addedStepIds": added,
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
                elif step["kind"] == "validate":
                    pass
                elif step["kind"] == "refusal":
                    await stream.emit(
                        "run.error",
                        {
                            "code": step["code"],
                            "message": step["message"],
                            "recoverable": False,
                        },
                    )
                    outcome.aborted = True
                    await stream.emit(
                        "step.failed",
                        {"stepId": step["id"], "error": step["code"], "willRetry": False},
                    )
                    break
                elif step["kind"] == "tool":
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
                elif step["kind"] == "answer":
                    if self._answerer is None:
                        answer = EvidenceAnswer(
                            answer="",
                            failure_code=PLANNER_MODEL_UNAVAILABLE,
                            failure_message=(
                                "Answering a read-only objective requires a model, but no answer "
                                "model is configured."
                            ),
                        )
                    else:
                        answer = await self._answerer(request.objective, step["answerGoal"], evidence)
                    if answer.failed:
                        await stream.emit(
                            "run.error",
                            {
                                "code": answer.failure_code,
                                "message": answer.failure_message,
                                "recoverable": False,
                            },
                        )
                        await stream.emit(
                            "step.failed",
                            {
                                "stepId": step["id"],
                                "error": answer.failure_code,
                                "willRetry": False,
                            },
                        )
                        outcome.aborted = True
                        break
                    artifact = new_artifact(
                        run_id=request.run_id,
                        session_id=request.session.id,
                        kind="answer",
                        title="Copilot answer",
                        content={
                            "answer": answer.answer,
                            "keyPoints": list(answer.key_points),
                            "citedEvidenceIds": list(answer.cited_evidence_ids),
                            "unverified": list(answer.unverified),
                        },
                    )
                    artifact_ids.append(artifact.id)
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
                        #
                        # Under `withhold` this blocks ONLY `decline`, and that narrowness is
                        # compelled rather than an oversight (confirmed in the primary-assessment
                        # audit). `escalate` and `proceed_with_conditions` are adverse READINGS
                        # that both END IN A HUMAN DECISION, which is the thing a proposal exists
                        # to reach; withholding on them would send the case to the admin tabs,
                        # which leave no audit record — the harsher outcome, reached by the safer-
                        # sounding rule. `decline` is the only verdict where the primary is saying
                        # the action should not happen at all.
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

    async def _run_intent_step(
        self,
        request: PlannerRequest,
        stream: RunStream,
        position: int,
        steps: list[dict[str, Any]],
        next_step_number: int,
        evidence: dict[str, Any],
    ) -> tuple[list[str], int, list[str], bool]:
        catalogue = await self._authority.policy_catalogue(request.bearer_token)
        actions = _action_specs(catalogue)
        if catalogue.get("available") is False or not actions:
            decision = IntentDecision(
                kind="failure",
                reason_code="proposal_refused_by_authority",
                message=(
                    "The authority policy catalogue is unavailable, so the planner cannot know "
                    "which actions are inside the Copilot leash."
                ),
            )
            added, next_step_number = _insert_steps(
                steps,
                position,
                [
                    _step(
                        next_step_number,
                        "Refuse objective",
                        "refusal",
                        code=decision.reason_code,
                        message=decision.message,
                    )
                ],
            )
            return added, next_step_number, [], False
        proposable = [
            a
            for a in actions.values()
            if _is_proposable_action(a, self._registry.tool_ids)
        ]
        forbidden = [
            a
            for a in actions.values()
            if not _is_proposable_action(a, self._registry.tool_ids)
        ]

        selector = self._intent_selector
        if selector is None:
            decision = IntentDecision(
                kind="failure",
                reason_code=PLANNER_MODEL_UNAVAILABLE,
                message=(
                    "Free-text planning requires an intent model, but none is configured. "
                    "No action was selected and no evidence was gathered."
                ),
            )
        else:
            decision = await selector(
                request.objective,
                actions=[_action_wire(a) for a in proposable],
                forbidden_actions=[_action_wire(a) for a in forbidden],
                read_tools=self._registry.describe() if hasattr(self._registry, "describe") else [],
            )

        if decision.failed:
            added, next_step_number = _insert_steps(
                steps,
                position,
                [
                    _step(
                        next_step_number,
                        "Refuse objective",
                        "refusal",
                        code=decision.reason_code or INTENT_CONTRACT_INVALID,
                        message=decision.message or "The objective could not be interpreted.",
                    )
                ],
            )
            return added, next_step_number, [], False

        if decision.kind == "propose":
            action = actions.get(decision.action_id or "")
            invalid = _validate_action_choice(decision, action, actions, self._registry.tool_ids)
            if invalid is not None:
                added, next_step_number = _insert_steps(
                    steps,
                    position,
                    [_step(next_step_number, "Refuse objective", "refusal", **invalid)],
                )
                return added, next_step_number, [], False

        resolution = await self._reference_resolver.resolve(request, decision)
        decision = resolution.decision
        evidence.update(resolution.evidence)
        resolve_step = (
            [_step(next_step_number, "Resolve references", "validate")]
            if resolution.evidence
            else []
        )
        if resolve_step:
            next_step_number += 1

        if decision.kind == "refuse":
            added, next_step_number = _insert_steps(
                steps,
                position,
                [
                    _step(
                        next_step_number,
                        "Refuse objective",
                        "refusal",
                        code=decision.reason_code,
                        message=decision.message,
                    )
                ],
            )
            return added, next_step_number, [], False

        if decision.kind == "read":
            validated = _validate_read_plan(decision, self._registry, request.session.capabilities)
            if validated is not None:
                added, next_step_number = _insert_steps(
                    steps,
                    position,
                    [*resolve_step, _step(next_step_number, "Refuse objective", "refusal", **validated)],
                )
                return added, next_step_number, [], False
            planned = [
                _step(
                    next_step_number + offset,
                    f"Gather evidence: {item['toolId']}",
                    "tool",
                    toolId=item["toolId"],
                    arguments=dict(item.get("arguments") or {}),
                )
                for offset, item in enumerate(decision.read_plan)
            ]
            planned = [*resolve_step, *planned]
            planned.append(
                _step(
                    next_step_number + len(planned),
                    "Answer from evidence",
                    "answer",
                    answerGoal=decision.answer_goal,
                )
            )
            planned.append(
                _step(next_step_number + len(planned), "Assemble evidence bundle", "artifact")
            )
            added, next_step_number = _insert_steps(steps, position, planned)
            return added, next_step_number, [], False

        if decision.kind == "propose":
            action = actions.get(decision.action_id or "")
            assert action is not None
            payload_or_error = _construct_payload(action, decision.payload_draft or {})
            if isinstance(payload_or_error, dict) and "code" in payload_or_error:
                added, next_step_number = _insert_steps(
                    steps,
                    position,
                    [*resolve_step, _step(next_step_number, "Refuse objective", "refusal", **payload_or_error)],
                )
                return added, next_step_number, [], False
            request.action_id = action.action_id
            request.payload = payload_or_error
            required = [tool_id for tool_id in action.required_evidence if tool_id in self._registry.tool_ids]
            request.facts = _facts_from_payload(request.facts, request.payload)
            planned = [*resolve_step, _step(next_step_number, "Validate proposed action and payload", "validate")]
            planned.extend(
                _step(
                    next_step_number + index + 1,
                    f"Gather evidence: {tool_id}",
                    "tool",
                    toolId=tool_id,
                )
                for index, tool_id in enumerate(required)
            )
            planned.append(_step(next_step_number + len(planned), "Assess the evidence", "assess"))
            planned.append(_step(next_step_number + len(planned), "Assemble evidence bundle", "artifact"))
            planned.append(
                _step(
                    next_step_number + len(planned),
                    f"Propose {action.action_id} for human signature",
                    "propose",
                )
            )
            added, next_step_number = _insert_steps(steps, position, planned)
            return added, next_step_number, required, True

        added, next_step_number = _insert_steps(
            steps,
            position,
            [
                _step(
                    next_step_number,
                    "Refuse objective",
                    "refusal",
                    code=INTENT_CONTRACT_INVALID,
                    message="The planner model returned an unsupported intent kind.",
                )
            ],
        )
        return added, next_step_number, [], False

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

        arguments = dict(step.get("arguments") or _bind_arguments(tool.parameters, request))
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


def _free_text_initial_steps() -> list[dict[str, Any]]:
    return [_step(1, "Interpret objective", "intent")]


def _step(number: int, title: str, kind: str, **extra: Any) -> dict[str, Any]:
    step = {
        "id": f"step_{number}",
        "index": number - 1,
        "title": title,
        "status": "pending",
        "kind": kind,
    }
    step.update(extra)
    return step


def _insert_steps(
    steps: list[dict[str, Any]], position: int, added_steps: Sequence[dict[str, Any]]
) -> tuple[list[str], int]:
    steps[position:position] = list(added_steps)
    return [s["id"] for s in added_steps], max([_step_number(s["id"]) for s in steps], default=0) + 1


def _step_number(step_id: str) -> int:
    match = re.search(r"(\d+)$", step_id)
    return int(match.group(1)) if match else 0


def _action_specs(catalogue: dict[str, Any]) -> dict[str, _ActionSpec]:
    specs: dict[str, _ActionSpec] = {}
    thresholds = {
        str(t.get("name")): t.get("value") or t.get("default")
        for t in catalogue.get("thresholds") or []
        if t.get("name")
    }
    score_floor: Decimal | None = None
    if thresholds.get("score_override_floor") is not None:
        try:
            score_floor = Decimal(str(thresholds["score_override_floor"]))
        except InvalidOperation:
            score_floor = None
    for raw in catalogue.get("actions") or []:
        action_id = str(raw.get("id", "")).strip()
        if not action_id:
            continue
        specs[action_id] = _ActionSpec(
            action_id=action_id,
            display_name=str(raw.get("displayName") or action_id),
            base_rung=str(raw.get("baseRung") or ""),
            agent_may_propose=raw.get("agentMayPropose") is True,
            required_evidence=tuple(str(item) for item in raw.get("requiredEvidence") or ()),
            hash_fields=tuple(str(item) for item in raw.get("hashFields") or ()),
            money_fields=tuple(str(item) for item in raw.get("moneyFields") or ()),
            score_override_floor=score_floor if action_id == "transaction.score.override" else None,
        )
    return specs


def _action_wire(action: _ActionSpec) -> dict[str, Any]:
    wire = {
        "id": action.action_id,
        "displayName": action.display_name,
        "baseRung": action.base_rung,
        "requiredEvidence": list(action.required_evidence),
        "hashFields": list(action.hash_fields),
        "moneyFields": list(action.money_fields),
    }
    if action.score_override_floor is not None:
        wire["scoreOverrideSignableBand"] = [str(action.score_override_floor), "1.00"]
    return wire


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _looks_like_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Za-z_-]{8,64}", value))


def _refusal(code: str, message: str) -> IntentDecision:
    return IntentDecision(kind="refuse", reason_code=code, message=message)


def _validate_read_plan(
    decision: IntentDecision, registry: ToolRegistry, capabilities: Sequence[str]
) -> dict[str, str] | None:
    capability_set = set(capabilities or ())
    for item in decision.read_plan:
        tool_id = str(item.get("toolId", "")).strip()
        tool = registry.get(tool_id)
        if tool is None:
            return {
                "code": "objective_unmappable",
                "message": f"The objective asked for evidence this harness cannot gather: {tool_id}.",
            }
        if not isinstance(item.get("arguments"), dict):
            return {
                "code": INTENT_CONTRACT_INVALID,
                "message": "The planner model returned a read step without an arguments object.",
            }
        if tool.capability_scope not in capability_set:
            return {
                "code": "read_tool_forbidden",
                "message": f"The selected evidence tool is outside this session's authority: {tool_id}.",
            }
        try:
            jsonschema.validate(instance=item["arguments"], schema=tool.parameters)
        except jsonschema.ValidationError:
            return {
                "code": INTENT_CONTRACT_INVALID,
                "message": f"The planner model returned invalid arguments for {tool_id}.",
            }
    return None


def _validate_action_choice(
    decision: IntentDecision,
    action: _ActionSpec | None,
    actions: dict[str, _ActionSpec],
    known_tool_ids: frozenset[str],
) -> dict[str, str] | None:
    action_id = decision.action_id or ""
    if action is None:
        if action_id in actions:
            return {
                "code": "forbidden_action",
                "message": (
                    f"{action_id} is outside the Copilot proposal leash and must be handled "
                    "through the appropriate non-harness process."
                ),
            }
        return {
            "code": "objective_unmappable",
            "message": f"The objective mapped to {action_id}, which is not a known authority action.",
        }
    if not action.agent_may_propose or action.base_rung == "L3":
        return {
            "code": "forbidden_action",
            "message": (
                f"{action.action_id} is outside the Copilot proposal leash and must be handled "
                "through the appropriate non-harness process."
            ),
        }
    unknown_evidence = sorted(set(action.required_evidence) - known_tool_ids)
    if unknown_evidence:
        return {
            "code": "evidence_unavailable",
            "message": (
                f"{action.action_id} requires evidence this harness cannot gather: "
                f"{', '.join(unknown_evidence)}."
            ),
        }
    return None


def _is_proposable_action(action: _ActionSpec, known_tool_ids: frozenset[str]) -> bool:
    return (
        action.agent_may_propose
        and action.base_rung != "L3"
        and set(action.required_evidence).issubset(known_tool_ids)
    )


def _construct_payload(action: _ActionSpec, draft: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    fields = action.hash_fields or tuple(str(k) for k in draft.keys())
    for field in fields:
        value = _resolve_mapping_path(draft, field)
        if value is None:
            return {
                "code": "payload_unfillable",
                "message": f"The planner could not fill required payload field '{field}' for {action.action_id}.",
            }
        if field in action.money_fields:
            money = _normalise_money(value, field)
            if isinstance(money, dict):
                return money
            value = money
        if action.action_id == "transaction.score.override" and field == "newScore":
            score = _normalise_score(value, action.score_override_floor)
            if isinstance(score, dict):
                return score
            value = score
        _set_mapping_path(payload, field, value)
    return payload


def _normalise_money(value: Any, field: str) -> str | dict[str, str]:
    if isinstance(value, bool):
        return {"code": "payload_invalid", "message": f"Money field '{field}' is not a decimal amount."}
    if isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        try:
            amount = Decimal(value.replace(",", ""))
        except InvalidOperation:
            return {"code": "payload_invalid", "message": f"Money field '{field}' is not a decimal amount."}
    else:
        return {
            "code": "payload_invalid",
            "message": f"Money field '{field}' must be an integer or decimal string, not {type(value).__name__}.",
        }
    if amount != amount.quantize(Decimal("0.01")):
        return {
            "code": "payload_invalid",
            "message": f"Money field '{field}' has more than two decimal places.",
        }
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def _normalise_score(value: Any, floor: Decimal | None) -> str | dict[str, str]:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return {"code": "payload_invalid", "message": "newScore must be a decimal string between 0.00 and 1.00."}
    try:
        score = Decimal(str(value))
    except InvalidOperation:
        return {"code": "payload_invalid", "message": "newScore must be a decimal string between 0.00 and 1.00."}
    if score != score.quantize(Decimal("0.01")):
        return {"code": "payload_invalid", "message": "newScore must have exactly two decimal places or fewer."}
    if score < Decimal("0.00") or score > Decimal("1.00"):
        return {"code": "payload_invalid", "message": "newScore must be between 0.00 and 1.00."}
    if floor is not None and score < floor:
        return {
            "code": "payload_invalid",
            "message": f"newScore below {floor} is outside the Copilot signable band.",
        }
    return f"{score.quantize(Decimal('0.01')):.2f}"


def _resolve_mapping_path(root: Mapping[str, Any], dotted: str) -> Any:
    cursor: Any = root
    for segment in dotted.split("."):
        if not isinstance(cursor, Mapping) or segment not in cursor:
            return None
        cursor = cursor[segment]
    return cursor


def _set_mapping_path(root: dict[str, Any], dotted: str, value: Any) -> None:
    cursor = root
    parts = dotted.split(".")
    for segment in parts[:-1]:
        child = cursor.get(segment)
        if not isinstance(child, dict):
            child = {}
            cursor[segment] = child
        cursor = child
    cursor[parts[-1]] = value


def _facts_from_payload(existing: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    facts = dict(existing or {})
    for key, value in payload.items():
        if key not in facts:
            facts[key] = value
    return facts


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

    # ABSENT and EMPTY are different facts and this line used to conflate them, because
    # `schema.get("required") or <fallback>` treats `[]` as falsy.
    #
    #   * `required: []` means every parameter is OPTIONAL, so the tool is bindable with no
    #     arguments at all. `list_account_applications` is exactly this, and it was being
    #     recorded `unbindable` — a FALSE stated reason, and a request silently dropped out of
    #     the stage-1 demand count. It errs closed, so there is no authority consequence; the
    #     consequence is to the measurement, and it undercounts in the direction that makes the
    #     ceiling look less needed than it is. That is the shape of defect this feature keeps
    #     producing, so it is named here rather than fixed quietly.
    #   * `required` ABSENT is a schema the manifest loader would not have produced — every tool
    #     in `config/copilot-tools.yaml` declares it — so it means a malformed or hand-built
    #     schema, and the conservative reading is kept: treat every declared property as needed.
    #     Guessing "all optional" there would admit a tool on a schema nobody wrote.
    declared = list((schema.get("properties") or {}).keys())
    raw_required = schema.get("required")
    required = list(raw_required) if isinstance(raw_required, list) else declared

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
