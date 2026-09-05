"""Blind construction of the L2 supervisor's second opinion — the headline of Phase 3.

Contract of record: epic §6.4 (independence of the second opinion), §6.2 (the L2
fan-out is the one non-negotiable trigger), §6.3 (subagents inherit the read
allowlist and cannot call ``propose_action``).

    "A 'second opinion' that reads the first opinion is a rubber stamp with extra
    latency. Enforce independence structurally, not by prompting." — §6.4

Read that sentence twice, because it dictates the ENTIRE shape of this module and
of the tests over it. The tempting way to build a supervisor is to hand it the
primary's write-up and instruct it to "form your own view, and disregard the
recommendation above." That is independence by request. §6.4 rules it out: the
supervisor's input is *constructed by the harness from the original banker intent
and the raw entity ids only* — never the primary's plan, narrative,
recommendation, or confidence.

The failure this module makes UNREPRESENTABLE
----------------------------------------------
The dangerous version of the harness passes the primary's conclusion downstream
"just in case the supervisor wants context." Every prompt-injection defence and
every "please ignore" instruction is downstream of that mistake, and none of them
can undo it — once a token is in the supervisor's context window it can be echoed.

So the structural move here is the same one Phase 1 used for ``ExecuteAsync``
taking no payload parameter: **the function that builds the supervisor's input
takes only the banker intent as an argument.** There is no parameter through
which the primary's output could arrive. A leak is not "blocked" — it has no
route to travel. A test that tries to pass a ``PrimaryResult`` to the builder
gets a ``TypeError`` from Python's own argument binding, not from a guard I wrote
and could get wrong.

The behavioural token-scan (§6.4's "constructed prompt contains none of the
primary's output tokens") is kept as a CROSS-CHECK, not the primary defence — a
scan can be defeated by paraphrase, and a scan over an empty haystack passes
vacuously (Phase 1 lesson #1). The structural proof is what carries the weight;
the scan catches a regression that reintroduces a channel.

Nothing in this module is a copy of ``src/banker-copilot-service/``. It is an
executable oracle for §6.4. A green run here proves the SPECIFICATION admits a
leak-free construction; it says nothing about Turk's harness, which does not yet
implement fan-out (planner/loop.py is still single-threaded). That gap is a
FAILING integration-ledger entry, never a skip.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .registry import DomainReadTransport, HttpCall


class IndependenceViolation(RuntimeError):
    """A route was found by which the primary's output could reach the supervisor."""


# ---------------------------------------------------------------------------
# The two things the harness is allowed to carry into supervisor construction,
# and the one thing it is not. These are distinct types so that conflating them
# is a TypeError rather than a code review — the same discipline Run/Session use.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BankerIntent:
    """The ORIGINAL banker request. §6.4(1): "constructed from the original banker
    intent, not from the primary's output."

    ``task_framing`` is the banker's own words. ``entity_ids`` are the raw ids the
    request named (an account, a flagged transaction). Nothing here is derived from
    a model run — it is what the human typed and the ids that were resolved from it,
    both available *before* the primary agent does any work.
    """

    task_framing: str
    entity_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.task_framing.strip():
            raise ValueError("a supervisor with no task framing has nothing to independently work")
        for eid in self.entity_ids:
            if not isinstance(eid, str) or not eid.strip():
                raise ValueError(f"entity id {eid!r} is not a usable identifier")


@dataclass(frozen=True)
class PrimaryResult:
    """The primary agent's output. This is the thing that must NEVER reach the
    supervisor's construction. It is modelled so a test can prove a specific,
    distinctive value cannot appear in the supervisor's input.

    Every field here is a channel §6.4(1) names by hand: plan, narrative,
    recommendation, confidence. ``cached_tool_results`` is §6.4(2) — the reads the
    supervisor may not consume.
    """

    plan: tuple[str, ...]
    narrative: str
    recommendation: str
    confidence: float
    cached_tool_results: Mapping[str, Any] = field(default_factory=dict)

    def all_tokens(self) -> set[str]:
        """Every distinctive token this result put into the world. The scan corpus."""
        blob = json.dumps(
            {
                "plan": list(self.plan),
                "narrative": self.narrative,
                "recommendation": self.recommendation,
                "confidence": self.confidence,
                "cached": dict(self.cached_tool_results),
            }
        )
        return {t for t in _tokenize(blob) if len(t) >= 4}


def _tokenize(text: str) -> set[str]:
    out: set[str] = set()
    word = []
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


# ---------------------------------------------------------------------------
# The supervisor's input. Frozen, and — this is the whole point — built ONLY
# from a BankerIntent. There is no field on it, and no parameter on its builder,
# that can carry the primary's output.
# ---------------------------------------------------------------------------


# §6.4(3): adversarial posture, fixed and not caller-supplied. The primary is
# framed "work the case"; the supervisor "determine whether the requested action
# is defensible on the evidence, and state the strongest argument against it."
SUPERVISOR_POSTURE = (
    "Determine whether the requested action is defensible on the evidence you "
    "gather yourself, and state the strongest argument against it."
)


@dataclass(frozen=True)
class SupervisorInput:
    """What the supervisor agent is spawned with. §6.4(1): task framing and raw
    entity ids only.

    Note what is NOT here: no ``primary``, no ``plan``, no ``recommendation``, no
    ``context`` handle through which any of those could be reached. The set of
    fields is the set of things the supervisor is permitted to know, made total.
    """

    task_framing: str
    entity_ids: tuple[str, ...]
    posture: str = SUPERVISOR_POSTURE

    def serialize(self) -> str:
        """Exactly the bytes handed to the fresh Foundry thread. The scan runs on this."""
        return json.dumps(
            {"framing": self.task_framing, "entityIds": list(self.entity_ids), "posture": self.posture},
            sort_keys=True,
        )


def build_supervisor_input(intent: BankerIntent) -> SupervisorInput:
    """Construct the supervisor's spawn input. §6.4(1).

    The signature is the security control. ``intent`` is the only parameter, so
    the primary's output has no argument to travel through. This is deliberately
    NOT ``build_supervisor_input(intent, primary)`` with a promise to ignore
    ``primary`` — a promise is what §6.4 forbids. If a future edit needs the
    primary here, it has to change this signature, and that change is what the
    tests below are positioned to catch.
    """
    return SupervisorInput(task_framing=intent.task_framing, entity_ids=tuple(intent.entity_ids))


# ---------------------------------------------------------------------------
# The fan-out itself. Two agents, two transports, one comparison done AFTER the
# fact by the harness — never by either agent reading the other.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecondOpinion:
    """§6.4(5): structural output only. The supervisor returns a shape, never prose
    it could have echoed the primary into."""

    recommendation: str
    confidence: float
    key_factors: tuple[str, ...]
    strongest_counter_argument: str


@dataclass
class SupervisorAgent:
    """An independent worker. It holds its OWN transport (§6.4(2)): its reads are a
    second draw from the evidence, not a view of the primary's cache.

    ``decide`` is a scripted stand-in for a model call — the same choice the Phase 2
    harness made, and for the same reason: a script can attempt the exact leak a
    real model cannot be reliably steered into. Crucially, ``decide`` receives ONLY
    the ``SupervisorInput`` and the results of its own reads; it is not given, and
    cannot reach, the primary's result.
    """

    transport: DomainReadTransport
    decider: Any  # Callable[[SupervisorInput, dict[str, Any]], SecondOpinion]

    def work(self, spawn: SupervisorInput, bearer: str) -> SecondOpinion:
        own_evidence: dict[str, Any] = {}
        for entity_id in spawn.entity_ids:
            # A SECOND, independent read. Same route as any read tool: GET only.
            own_evidence[entity_id] = self.transport.request(
                "GET", "evidence-service", f"/api/evidence/{entity_id}", {"Authorization": "******"}
            )
        return self.decider(spawn, own_evidence)


@dataclass
class FanOutResult:
    primary: PrimaryResult
    second_opinion: SecondOpinion
    agrees_with_primary: bool
    supervisor_input: SupervisorInput


class Harness:
    """The Phase 3 fan-out coordinator, reduced to the independence-bearing parts.

    It is the ONLY object that ever holds both the primary's result and the
    supervisor's. It computes agreement by comparing two independently-produced
    recommendations — §6.4(6) — and it does so AFTER both are in hand. Neither
    agent is ever handed the other's output.
    """

    def __init__(self, supervisor: SupervisorAgent) -> None:
        self._supervisor = supervisor

    def second_opinion_for(
        self, intent: BankerIntent, primary: PrimaryResult, bearer: str
    ) -> FanOutResult:
        # (1) Construct the spawn input from the INTENT. `primary` is in scope here
        #     and is deliberately not passed — the builder has no parameter for it,
        #     so even an accidental `build_supervisor_input(intent, primary)` fails
        #     to bind rather than silently leaking.
        spawn = build_supervisor_input(intent)

        # (2) The supervisor works from its own reads. It never sees `primary`.
        opinion = self._supervisor.work(spawn, bearer)

        # (3) Agreement is COMPUTED by comparison, not read off the supervisor.
        #     §6.4(6): disagreement is first-class and does not gate proceeding.
        agrees = _recommendations_agree(primary.recommendation, opinion.recommendation)

        return FanOutResult(
            primary=primary,
            second_opinion=opinion,
            agrees_with_primary=agrees,
            supervisor_input=spawn,
        )


def _recommendations_agree(primary_reco: str, supervisor_reco: str) -> bool:
    return primary_reco.strip().casefold() == supervisor_reco.strip().casefold()


# ---------------------------------------------------------------------------
# Subagent capability floor. §6.3: subagents inherit the parent's read allowlist
# and CANNOT call propose_action. Only the root harness proposes.
# ---------------------------------------------------------------------------


SUBAGENT_FORBIDDEN_TOOLS = frozenset({"propose_action"})


def subagent_tool_ids(parent_read_tool_ids: tuple[str, ...]) -> tuple[str, ...]:
    """The tools a subagent is offered: the parent's READ tools, minus anything
    write-shaped. There is exactly one write-shaped affordance in the system —
    ``propose_action`` — and a subagent never gets it (§6.3)."""
    return tuple(t for t in parent_read_tool_ids if t not in SUBAGENT_FORBIDDEN_TOOLS)


def independence_report(spawn: SupervisorInput, primary: PrimaryResult) -> tuple[str, ...]:
    """Every distinctive primary token that appears in the supervisor's spawn bytes.

    Empty is the pass. This is the §6.4 behavioural cross-check, and it is written
    to be *able to fail*: if `build_supervisor_input` ever folds the primary's
    narrative into the framing, the offending tokens show up here by name.
    """
    haystack = _tokenize(spawn.serialize())
    leaked = sorted(primary.all_tokens() & haystack)
    return tuple(leaked)


def builder_accepts_only_intent() -> bool:
    """Structural assertion made queryable: the builder's parameters are exactly
    ``{intent}``. If someone adds a ``primary`` parameter, this returns False and
    the test that calls it goes red."""
    params = inspect.signature(build_supervisor_input).parameters
    return tuple(params) == ("intent",)
