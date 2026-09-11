"""Fan-out engine and the L2 blind supervisor — the headline of Phase 3.

Contract of record: epic §6.2 (the L2 second opinion is the ONE mandatory fan-out;
the rest are opt-in), §6.3 (subagents inherit the read allowlist, cannot call
``propose_action``, and run under the config-driven limits in
``config/harness-limits.yaml``), §6.4 (the second opinion is BLIND — constructed
from the banker intent and raw entity ids only, never the primary's plan,
narrative, recommendation, confidence or cached reads).

Why this module looks the way it does
--------------------------------------
The dangerous harness passes the primary's conclusion into supervisor
construction "for context". Every "please ignore the above" instruction is
downstream of that mistake and none of them can undo it — once a token is in the
supervisor's context it can be echoed. So independence is made STRUCTURAL, the
same move Phase 1 used for ``ExecuteAsync`` taking no payload:

    ``build_supervisor_input(intent)`` takes ONLY the banker intent. There is no
    parameter through which the primary's output could arrive. A leak is not
    "blocked" — it has no route to travel.

The behavioural token-scan (``independence_report``) is kept as a CROSS-CHECK,
never the primary defence: a scan over an empty haystack passes vacuously
(Phase 1 lesson #1), and paraphrase defeats it. The structural proof carries the
weight; the scan catches a regression that reintroduces a channel.

The public shapes here deliberately mirror the QA oracle in
``banker-copilot-service.Tests/spec/supervisor.py`` name-for-name, so the
blind-construction suite can be re-pointed from the oracle at THIS production
builder and prove the shipping harness, not just the specification.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence

import structlog

from app.events.bus import RunStream, RunStreamRegistry
from app.planner.limits import FanoutLimits
from app.planner.model_call import Attribution
from app.planner.verdicts import AGREE, NOT_COMPARABLE, compare_verdicts, is_verdict
from app.planner.approval_view import (
    primary_wire_assessment,
    supervisor_wire_assessment,
    verdict_for,
)
from app.tools.executor import ToolExecutor, ToolInvocationError
from app.tools.registry import ToolRegistry

logger = structlog.get_logger("banker-copilot-service")


class IndependenceViolation(RuntimeError):
    """A route was found by which the primary's output could reach the supervisor."""


# ---------------------------------------------------------------------------
# The two things the harness may carry into supervisor construction, and the one
# it may not. Distinct types so conflating them is a TypeError, not a review note.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BankerIntent:
    """The ORIGINAL banker request. §6.4(1): built from the banker's intent, never
    the primary's output. ``task_framing`` is the banker's own words; ``entity_ids``
    are the raw ids the request named — both known BEFORE the primary does any work.
    """

    task_framing: str
    entity_ids: tuple[str, ...]
    action_id: str = ""

    def __post_init__(self) -> None:
        if not self.task_framing.strip():
            raise ValueError("a supervisor with no task framing has nothing to independently work")
        for eid in self.entity_ids:
            if not isinstance(eid, str) or not eid.strip():
                raise ValueError(f"entity id {eid!r} is not a usable identifier")


@dataclass(frozen=True)
class PrimaryResult:
    """The primary agent's output — the thing that must NEVER reach supervisor
    construction. Modelled so a test can prove a distinctive value cannot appear in
    the supervisor's input. Every field is a channel §6.4(1) names by hand;
    ``cached_tool_results`` is §6.4(2), the reads the supervisor may not consume.
    """

    plan: tuple[str, ...] = ()
    narrative: str = ""
    recommendation: str = ""
    confidence: float = 0.0
    cached_tool_results: Mapping[str, Any] = field(default_factory=dict)

    def all_tokens(self) -> set[str]:
        """Every distinctive token this result put into the world. The scan corpus."""
        blob = json.dumps(
            {
                "plan": list(self.plan),
                "narrative": self.narrative,
                "recommendation": self.recommendation,
                "confidence": self.confidence,
                "cached": _jsonable(self.cached_tool_results),
            },
            sort_keys=True,
        )
        return {t for t in _tokenize(blob) if len(t) >= 4}


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _tokenize(text: str) -> set[str]:
    out: set[str] = set()
    word: list[str] = []
    for ch in text:
        if ch.isalnum() or ch in "_-":
            word.append(ch)
        else:
            if word:
                out.add("".join(word))
                word = []
    if word:
        out.add("".join(word))
    return out


# §6.4(3): adversarial posture, fixed and NOT caller-supplied. The primary is framed
# "work the case"; the supervisor "determine whether the requested action is
# defensible on the evidence you gather yourself, and state the strongest argument
# against it."
SUPERVISOR_POSTURE = (
    "Determine whether the requested action is defensible on the evidence you "
    "gather yourself, and state the strongest argument against it."
)


@dataclass(frozen=True)
class SupervisorInput:
    """What the supervisor agent is spawned with. §6.4(1): task framing and raw
    entity ids only. Note what is NOT here: no ``primary``, no ``plan``, no
    ``recommendation``, no ``context`` handle through which any of those could be
    reached. The field set IS the set of things the supervisor may know, made total.

    ``action_id`` is admissible under §6.4(1) and is NOT a blindness regression: it is
    the banker's own declared action, fixed at request time and known before the primary
    does any work. It is the same class of input as ``task_framing``.

    It is here because omitting it was a live defect, not a nicety. Measured against the
    deployed model, on an *adverse* action — rejecting an application with tampered
    documents — the supervisor reasoned correctly about the evidence and then returned
    ``decline`` four times out of four at 0.99 confidence, because with only free-text
    framing to go on it judged *opening* the account rather than *rejecting* it. Violent
    agreement was recorded as disagreement. A recommendation of "proceed" is meaningless
    unless the thing to proceed WITH is stated, and inferring the verb from prose is
    exactly the guess this contract exists to prevent.
    """

    task_framing: str
    entity_ids: tuple[str, ...]
    action_id: str = ""
    posture: str = SUPERVISOR_POSTURE

    def serialize(self) -> str:
        """Exactly the bytes handed to the fresh supervisor thread. The scan runs on this."""
        return json.dumps(
            {
                "framing": self.task_framing,
                "entityIds": list(self.entity_ids),
                "actionId": self.action_id,
                "posture": self.posture,
            },
            sort_keys=True,
        )


def build_supervisor_input(intent: BankerIntent) -> SupervisorInput:
    """Construct the supervisor's spawn input. §6.4(1).

    The signature IS the security control. ``intent`` is the only parameter, so the
    primary's output has no argument to travel through. This is deliberately NOT
    ``build_supervisor_input(intent, primary)`` with a promise to ignore ``primary``
    — a promise is what §6.4 forbids. A future edit that needs the primary here must
    change this signature, and that change is what ``builder_accepts_only_intent``
    and the blind-construction suite are positioned to catch.
    """
    return SupervisorInput(
        task_framing=intent.task_framing,
        entity_ids=tuple(intent.entity_ids),
        action_id=intent.action_id,
    )


# ---------------------------------------------------------------------------
# The supervisor's own read path and its structural output.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecondOpinion:
    """§6.4(5): structural output only. The supervisor returns a shape, never prose
    it could have echoed the primary into."""

    recommendation: str
    confidence: float
    key_factors: tuple[str, ...]
    strongest_counter_argument: str
    #: Which decider produced this, on which exact bytes (§P7.1). Attribution, not
    #: reproducibility: identical bytes produce split verdicts, so the record's job is to let a
    #: reader say WHICH model said this — including that it was the same base model as the
    #: primary's, which is the residual correlation §P1.2e requires be disclosed rather than
    #: papered over. Optional so a test decider need not supply one.
    attribution: "Attribution | None" = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "keyFactors": list(self.key_factors),
            "strongestCounterArgument": self.strongest_counter_argument,
        }


class SupervisorReader(Protocol):
    """The supervisor's ONLY route to evidence: its own reads. §6.4(2) — a second
    draw, never a view of the primary's cache."""

    async def gather(self, entity_ids: tuple[str, ...], bearer: str) -> dict[str, Any]: ...


@dataclass
class ToolEvidenceReader:
    """Production reader. Re-runs the action's read tools INDEPENDENTLY, binding
    arguments from the banker's raw inputs (payload/facts/context) — never from the
    primary's ``evidence``. It holds no reference to the primary's output; the leak
    it prevents has no object to travel through.

    Each read is a genuine second invocation against the upstream, capped by the
    per-subagent tool budget (§6.3), and reported through ``on_read`` so the
    supervisor's own trace records what it gathered.
    """

    executor: ToolExecutor
    registry: ToolRegistry
    raw_inputs: Mapping[str, Any]
    tool_ids: tuple[str, ...]
    tool_budget: int
    on_read: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None

    async def gather(self, entity_ids: tuple[str, ...], bearer: str) -> dict[str, Any]:
        own_evidence: dict[str, Any] = {}
        for tool_id in self.tool_ids[: self.tool_budget]:
            tool = self.registry.get(tool_id)
            if tool is None:
                continue
            arguments = {
                name: self.raw_inputs[name]
                for name in (tool.parameters.get("properties") or {})
                if name in self.raw_inputs and self.raw_inputs[name] is not None
            }
            try:
                result = await self.executor.invoke(tool_id, arguments, bearer)
            except ToolInvocationError as exc:
                own_evidence[tool_id] = {"error": f"{exc.code}: {exc.message}"}
                if self.on_read is not None:
                    await self.on_read(tool_id, {"toolId": tool_id, "ok": False})
                continue
            own_evidence[tool_id] = result.data
            if self.on_read is not None:
                await self.on_read(tool_id, {"toolId": tool_id, "ok": True, "summary": result.summary()})
        return own_evidence


# The default, no-model decider. A scripted stand-in for a supervisor model call —
# the same choice the deterministic planner makes, and for the same reason: a script
# can be made to attempt the exact leak a real model cannot be reliably steered into.
# It receives ONLY the SupervisorInput and the results of its OWN reads.
def deterministic_decider(spawn: SupervisorInput, own_evidence: Mapping[str, Any]) -> SecondOpinion:
    gathered = [tool_id for tool_id, data in own_evidence.items() if not _is_error(data)]
    missing = [tool_id for tool_id, data in own_evidence.items() if _is_error(data)]
    if gathered and not missing:
        recommendation = "proceed"
        confidence = 0.8
        counter = (
            "Even with the evidence gathered independently, the action is reversible only at "
            "cost; require the second human signature before executing."
        )
    else:
        recommendation = "hold"
        confidence = 0.4
        counter = (
            "The supervisor could not independently reproduce all of the evidence the action "
            f"relies on (missing: {sorted(missing) or 'none gathered'}); proceeding would rest "
            "on the primary's reads alone, which is the dependency this second opinion exists to remove."
        )
    return SecondOpinion(
        recommendation=recommendation,
        confidence=confidence,
        key_factors=tuple(sorted(gathered)),
        strongest_counter_argument=counter,
        # Named out loud: this opinion was SCRIPTED, not thought. The mode is the exact fact
        # `supervisor_mode` exists to keep visible, and it now travels with the opinion onto the
        # approval record instead of living only in a startup log line nobody re-reads.
        attribution=Attribution(mode="deterministic"),
    )


def _is_error(data: Any) -> bool:
    return isinstance(data, Mapping) and "error" in data


Decider = Callable[[SupervisorInput, Mapping[str, Any]], "SecondOpinion | Awaitable[SecondOpinion]"]


@dataclass
class SupervisorAgent:
    """An independent worker. It holds its OWN reader (§6.4(2)): its reads are a
    second draw from the evidence, not a view of the primary's cache. ``work``
    receives only the ``SupervisorInput`` and the results of its own reads — it is
    not given, and cannot reach, the primary's result.
    """

    reader: SupervisorReader
    decider: Decider = deterministic_decider

    async def work(self, spawn: SupervisorInput, bearer: str) -> SecondOpinion:
        own_evidence = await self.reader.gather(spawn.entity_ids, bearer)
        opinion = self.decider(spawn, own_evidence)
        if inspect.isawaitable(opinion):
            opinion = await opinion
        return opinion


@dataclass(frozen=True)
class FanOutResult:
    second_opinion: SecondOpinion
    #: Tri-state (§P4.3): ``agree`` | ``diverge`` | ``not_comparable``. A side that failed has no
    #: position, and ``not_comparable`` is excluded from every denominator rather than counted as
    #: dissent or as consensus.
    agreement: str
    supervisor_input: SupervisorInput
    subagent_run_id: str

    @property
    def agrees_with_primary(self) -> bool:
        """Kept for callers that only ask "did they agree?". Deliberately NOT the stored value.

        ``not_comparable`` is False here — a dead pipeline must never read as consensus — but a
        caller that needs to tell "they disagreed" from "there was nothing to compare" must read
        ``agreement``, and that is why the boolean is derived rather than authoritative.
        """
        return self.agreement == AGREE


# ---------------------------------------------------------------------------
# Subagent capability floor. §6.3: subagents inherit the parent's read allowlist
# and CANNOT call propose_action. Only the root harness proposes.
# ---------------------------------------------------------------------------


SUBAGENT_FORBIDDEN_TOOLS = frozenset({"propose_action"})


def subagent_tool_ids(parent_read_tool_ids: tuple[str, ...]) -> tuple[str, ...]:
    """The tools a subagent is offered: the parent's tools minus anything
    write-shaped. There is exactly one write-shaped affordance — ``propose_action``
    — and a subagent never gets it (§6.3)."""
    return tuple(t for t in parent_read_tool_ids if t not in SUBAGENT_FORBIDDEN_TOOLS)


def independence_report(spawn: SupervisorInput, primary: PrimaryResult) -> tuple[str, ...]:
    """Every distinctive primary token that appears in the supervisor's spawn bytes.
    Empty is the pass. Written to be ABLE to fail: if ``build_supervisor_input`` ever
    folds the primary's narrative into the framing, the offending tokens appear here
    by name."""
    haystack = _tokenize(spawn.serialize())
    return tuple(sorted(primary.all_tokens() & haystack))


def builder_accepts_only_intent() -> bool:
    """Structural assertion made queryable: the builder's parameters are exactly
    ``{intent}``. If someone adds a ``primary`` parameter this returns False and the
    test that calls it goes red."""
    return tuple(inspect.signature(build_supervisor_input).parameters) == ("intent",)


# Keys whose VALUE is a raw entity identifier. The banker's request named these; they
# exist before the primary runs, so carrying them is not carrying primary output.
def extract_entity_ids(*sources: Mapping[str, Any]) -> tuple[str, ...]:
    """Pull the raw entity ids the request named, from the banker's own inputs only.

    An id is a scalar value under a key ending in 'id' (case-insensitive). Sorted and
    de-duplicated so the spawn input is deterministic — a replay must reconstruct the
    exact bytes the supervisor was handed.
    """
    ids: set[str] = set()
    for source in sources:
        for key, value in (source or {}).items():
            if not isinstance(key, str) or not key.lower().endswith("id"):
                continue
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                text = str(value).strip()
                if text:
                    ids.add(text)
    return tuple(sorted(ids))


# ---------------------------------------------------------------------------
# The fan-out engine wired into the planner.
# ---------------------------------------------------------------------------


class FanOutEngine:
    """The Phase 3 fan-out coordinator.

    It is the ONLY object that ever holds both the primary's result and the
    supervisor's. It builds the supervisor's spawn input from the ORIGINAL request
    (§6.4(1)), spawns exactly one blind supervisor at L2 (§6.2 — the one mandatory
    fan-out), runs it under the config-driven limits (§6.3), and computes agreement
    by comparison AFTER both are in hand (§6.4(6)). Neither agent is ever handed the
    other's output.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        runs: RunStreamRegistry,
        limits: FanoutLimits,
        decider: Decider = deterministic_decider,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._runs = runs
        self._limits = limits
        self._decider = decider

    async def run_second_opinion(
        self,
        request: Any,
        stream: RunStream,
        approval: Mapping[str, Any],
        *,
        required_evidence_tool_ids: Sequence[str],
        depth: int = 1,
        parent_step_id: str = "",
    ) -> FanOutResult | None:
        """Spawn the blind L2 supervisor. Returns its result, or ``None`` if the
        depth ceiling forbids spawning (no grandchildren, §6.3)."""

        # Depth guard (§6.3). Root is depth 1; a child is depth 2 — allowed by the
        # config ceiling. A subagent that tried to fan out again would be depth 3 and
        # is refused HERE, structurally, so "no grandchildren" is a bound, not a hope.
        child_depth = depth + 1
        if child_depth > self._limits.max_subagent_depth:
            logger.warning(
                "Fan-out refused: depth ceiling reached",
                run_id=getattr(request, "run_id", None),
                depth=depth,
                max_depth=self._limits.max_subagent_depth,
            )
            return None

        # (1) Build the spawn input from the INTENT. The raw entity ids come from the
        #     banker's own inputs (payload/facts/context), never from the primary's evidence.
        raw_inputs: dict[str, Any] = {}
        raw_inputs.update(getattr(request.session, "context", None) or {})
        raw_inputs.update(request.payload or {})
        raw_inputs.update(request.facts or {})
        intent = BankerIntent(
            task_framing=request.objective,
            entity_ids=extract_entity_ids(raw_inputs),
            # The banker's declared action, fixed at request time. Read from the REQUEST,
            # never from the proposal body — the body is downstream of the primary, and
            # sourcing it there would route primary output into supervisor construction.
            action_id=getattr(request, "action_id", "") or "",
        )
        spawn = build_supervisor_input(intent)

        # The supervisor re-runs the SAME read tools THE ACTION REQUIRED — a second, independent
        # draw. It gets the parent's read allowlist minus propose_action.
        #
        # §P5.7, and this is the whole reason the parameter is a list of REQUIRED tool ids rather
        # than the primary's evidence. This line used to read `sorted(primary_evidence.keys())`.
        # That was correct only by coincidence — the two sets happened to be equal while the
        # primary could gather nothing beyond policy. The moment the evidence ceiling let
        # discretionary reads into that dict, the supervisor's independent draw would silently
        # have widened to follow the primary's CHOICES, and the diff that caused it would contain
        # no mention of the supervisor at all: blindness defeated by a data-flow change in another
        # module. Deriving from the action's `requiredEvidence` is both more correct — the second
        # draw should be defined by the action under review, which is policy — and structurally
        # safe, because there is no longer an argument here through which primary output can
        # travel. Held by a test that fails the day someone re-points this at the evidence dict.
        allowed = set(subagent_tool_ids(self._registry.tool_ids))
        reader_tool_ids = tuple(t for t in sorted(set(required_evidence_tool_ids)) if t in allowed)

        subagent_run_id = f"{request.run_id}::supervisor"
        child_stream = self._runs.create(
            subagent_run_id, request.session.id, parent_run_id=request.run_id
        )

        await stream.emit(
            "subagent.spawned",
            {
                # §4.2 SubagentSpawnedPayload. The trace rail renders from these fields; the
                # supervisor's structural conclusion is surfaced on the APPROVAL (opinions[]),
                # not smuggled into the spawn frame. entityIds/toolIds are deliberately NOT
                # here — the contract has no home for them and the UI reducer would drop them.
                "subagentId": subagent_run_id,
                "parentStepId": parent_step_id,
                "name": "Independent second opinion",
                "role": "supervisor",
                "depth": child_depth,
            },
        )
        await child_stream.emit(
            "run.started",
            {
                "taskId": subagent_run_id,
                "title": "Independent second opinion",
                "intent": spawn.task_framing[:120],
                "startedAt": _now(),
            },
        )

        tool_call_count = 0

        async def _on_read(tool_id: str, summary: dict[str, Any]) -> None:
            nonlocal tool_call_count
            tool_call_count += 1
            await stream.emit(
                "subagent.progress",
                {
                    # §4.2 SubagentProgressPayload. ``note`` names the tool the supervisor
                    # independently re-ran; it is a tool id, never the primary's read value.
                    "subagentId": subagent_run_id,
                    "note": f"independently re-ran {tool_id}",
                    "toolCallCount": tool_call_count,
                },
            )
            await child_stream.emit(
                "tool.completed",
                {
                    "toolCallId": f"call_{child_stream.last_seq + 1}",
                    "durationMs": 0,
                    "resultSummary": summary,
                },
            )

        reader = ToolEvidenceReader(
            executor=self._executor,
            registry=self._registry,
            raw_inputs=raw_inputs,
            tool_ids=reader_tool_ids,
            tool_budget=self._limits.per_subagent_tool_budget,
            on_read=_on_read,
        )
        supervisor = SupervisorAgent(reader=reader, decider=self._decider)

        # (2) The supervisor works from its OWN reads, under the wall-clock ceiling.
        try:
            opinion = await asyncio.wait_for(
                supervisor.work(spawn, request.bearer_token),
                timeout=self._limits.subagent_wall_clock_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Supervisor subagent exceeded wall-clock budget",
                run_id=request.run_id,
                budget_s=self._limits.subagent_wall_clock_seconds,
            )
            await child_stream.emit(
                "run.error",
                {"code": "subagent_timeout", "message": "wall-clock budget exceeded", "recoverable": False},
            )
            await child_stream.emit(
                "run.done",
                {"status": "failed", "durationMs": 0, "finalArtifactIds": [], "finalSeq": child_stream.last_seq + 1},
            )
            return None

        # (3) Agreement is COMPUTED by comparison, never read off the supervisor.
        #     §6.4(6): disagreement is first-class and does not gate proceeding.
        primary_recommendation = _primary_recommendation(approval)
        agreement = compare_verdicts(primary_recommendation, opinion.recommendation)

        await stream.emit(
            "subagent.completed",
            {
                # §4.2 SubagentCompletedPayload. This is the trace-rail verdict caption — a
                # short, server-derived summary of the STRUCTURAL opinion, never free prose the
                # supervisor authored. The full structural opinion rides on the approval below.
                "subagentId": subagent_run_id,
                "status": "complete",
                "confidence": opinion.confidence,
                "verdictSummary": verdict_for(opinion.recommendation),
                "durationMs": 0,
            },
        )
        await child_stream.emit(
            "run.done",
            {
                "status": "completed",
                "durationMs": 0,
                "finalArtifactIds": [],
                "finalSeq": child_stream.last_seq + 1,
            },
        )
        # Shipped contract (ui-app `types.ts` + `authorityWire.ts`): the reducer stores
        # `event.payload.approval` and the ONE mapper `toApproval` turns the wire body into the
        # client `Approval` the card renders — flattening the payload (which is what powers the
        # material-field disclosure gate) and assigning assessment ROLES from key position. The
        # supervisor's opinion is never persisted (zero write tools; it is evidence, never a
        # signature), so it exists only here: we nest it under `agentAssessment.supervisor`, a
        # shape `toApproval.toAssessments` already tolerates, alongside the primary. That keeps a
        # SINGLE wire->client mapper (no second client-shaper in Python; see decision record) and
        # makes the supervisor's role structural — it cannot silently render as the primary.
        # It is EVIDENCE for a human, never a signature: no signature is added and the state is
        # left exactly as it arrived.
        updated_approval = dict(approval)
        updated_approval["agentAssessment"] = {
            "primary": primary_wire_assessment(approval),
            "supervisor": supervisor_wire_assessment(
                subagent_run_id,
                opinion.recommendation,
                opinion.confidence,
                opinion.strongest_counter_argument,
                opinion.key_factors,
                reader_tool_ids,
                opinion.attribution,
            ),
            # Server-observed, tri-state, and stated rather than left to be inferred from two
            # verdict fields. `not_comparable` is the arm that must be visible: a card that
            # cannot tell "they disagreed" from "one of them never answered" has already
            # rendered "Independent review reached the same verdict" over two absent verdicts.
            "agreement": agreement,
        }
        await stream.emit("approval.updated", {"approval": updated_approval})

        return FanOutResult(
            second_opinion=opinion,
            agreement=agreement,
            supervisor_input=spawn,
            subagent_run_id=subagent_run_id,
        )


def _primary_recommendation(approval: Mapping[str, Any]) -> str | None:
    """The primary's stated verdict, or ``None`` when it stated none.

    It used to end in ``or "proceed"``, on the reasoning that the primary PROPOSED the action so
    its position must be to proceed. That was harmless only while the primary could not fail.
    Now that it can, the fallback manufactures a position for an agent that has none — and a
    supervisor ``hold`` against a manufactured ``proceed`` renders as genuine dissent. That is
    precisely the classification error Livingston had to correct by hand in the other direction
    (a failed supervisor counted as dissent), mirrored onto the primary side and living *inside
    the code* rather than inside a probe.

    So: no verdict, no position, and the comparison below returns ``not_comparable``.
    """
    assessment = approval.get("agentAssessment") or {}
    recommendation = assessment.get("recommendation")
    return str(recommendation) if is_verdict(recommendation) else None


def _now() -> str:
    from app.events.envelope import utc_now_iso

    return utc_now_iso()


__all__ = [
    "IndependenceViolation",
    "BankerIntent",
    "PrimaryResult",
    "SUPERVISOR_POSTURE",
    "SupervisorInput",
    "build_supervisor_input",
    "SecondOpinion",
    "SupervisorReader",
    "ToolEvidenceReader",
    "SupervisorAgent",
    "deterministic_decider",
    "FanOutResult",
    "FanOutEngine",
    "subagent_tool_ids",
    "independence_report",
    "builder_accepts_only_intent",
    "extract_entity_ids",
    "SUBAGENT_FORBIDDEN_TOOLS",
]
