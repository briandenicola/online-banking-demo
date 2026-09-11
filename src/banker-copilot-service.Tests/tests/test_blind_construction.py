"""Blind construction — the L2 supervisor never sees the primary's work.

Epic §6.4. This is the Phase 3 headline: prove independence STRUCTURALLY — assert
on what the supervisor was actually handed, not that it was told to ignore
something. A test that checks for a "please disregard the above" instruction
proves nothing, because the leak has already happened by the time the instruction
is read.

Each test below tries to CONSTRUCT a leak through a specific channel §6.4 names —
a shared context object, a trace envelope, session state, cached tool results, the
artifact — and proves the route does not exist. The positive control at the end is
the one that makes the whole file honest: it demonstrates the token-scan can go
red, so a green scan is evidence rather than vacuum.

Oracle scope (stated plainly, repeated in the plan and the findings): a pass here
proves §6.4 admits a leak-free construction. The shipping harness does not yet
implement fan-out — planner/loop.py is single-threaded and says so — so the claim
"Turk's supervisor is blind" is UNVERIFIED and recorded as a failing
integration-ledger entry, not implied here.
"""

from __future__ import annotations

import inspect

import pytest

from spec.registry import DomainReadTransport
from spec.supervisor import (
    BankerIntent,
    FanOutResult,
    Harness,
    IndependenceViolation,
    PrimaryResult,
    SecondOpinion,
    SupervisorAgent,
    SupervisorInput,
    build_supervisor_input,
    builder_accepts_only_intent,
    independence_report,
    subagent_tool_ids,
)

# A primary result whose every field carries a distinctive, unmistakable sentinel.
# If any of these strings reaches the supervisor's spawn bytes, independence is
# broken and the scan names the exact token. The sentinels are long and unique so
# they cannot appear by coincidence in framing or an entity id.
SENTINEL_RECO = "PRIMARY_SENTINEL_RELEASE_THE_WIRE_9c3f"
SENTINEL_NARRATIVE = "PRIMARY_SENTINEL_NARRATIVE_because_priorReversals_zero_a71b"
SENTINEL_PLAN_STEP = "PRIMARY_SENTINEL_PLAN_call_get_flagged_transaction_d40e"
SENTINEL_CACHED = "PRIMARY_SENTINEL_CACHED_balance_18240_55_ff02"


def _primary() -> PrimaryResult:
    return PrimaryResult(
        plan=(SENTINEL_PLAN_STEP, "then assemble the bundle"),
        narrative=SENTINEL_NARRATIVE,
        recommendation=SENTINEL_RECO,
        confidence=0.82,
        cached_tool_results={"get_flagged_transaction": {"note": SENTINEL_CACHED}},
    )


def _intent() -> BankerIntent:
    # The banker's own words plus the raw ids the request named. Nothing here is
    # derived from a model run — this is exactly what §6.4(1) permits.
    return BankerIntent(
        task_framing="The $250,000 wire on the Delgado account was flagged this morning. Work it up.",
        entity_ids=("txn_delgado_1", "acc_delgado"),
    )


# A supervisor decider that would ECHO anything it could see, to make a leak
# maximally observable. It returns its own reads' presence, never the primary.
def _honest_supervisor_decider(spawn: SupervisorInput, own_evidence) -> SecondOpinion:
    return SecondOpinion(
        recommendation="hold for review",
        confidence=0.6,
        key_factors=tuple(sorted(own_evidence.keys())),
        strongest_counter_argument="A $250k wire with a thin baseline warrants a second human.",
    )


# ---------------------------------------------------------------------------
# 1. The structural core: the builder has no parameter for the primary's output.
# ---------------------------------------------------------------------------


def test_the_builder_takes_only_the_intent():
    """§6.4(1). The leak channel is closed by the FUNCTION SIGNATURE, the strongest
    available form. The primary's output cannot be passed because there is no
    parameter to pass it to — the same proof shape as Phase 1's ``ExecuteAsync``
    taking no payload argument."""
    assert builder_accepts_only_intent(), (
        "build_supervisor_input grew a parameter beyond `intent`; the primary's "
        "output now has an argument to travel through and independence is by promise"
    )
    params = inspect.signature(build_supervisor_input).parameters
    assert list(params) == ["intent"]
    # PEP 563 stringises annotations; compare by name.
    assert params["intent"].annotation in (BankerIntent, "BankerIntent")


def test_passing_the_primary_result_to_the_builder_is_a_type_error():
    """The attack, executed. Handing the builder the primary's result must fail to
    bind — Python's own argument binding refuses it, not a guard I wrote."""
    with pytest.raises(TypeError):
        build_supervisor_input(_intent(), _primary())  # type: ignore[call-arg]


def test_the_supervisor_input_has_no_field_that_can_hold_primary_output():
    """§6.4(1),(5). The set of fields IS the set of things the supervisor may know.
    A ``primary``/``plan``/``recommendation``/``context`` field would be a hole even
    if unused today, because a later edit populates unused fields."""
    fields = set(inspect.signature(SupervisorInput).parameters)
    forbidden = {"primary", "plan", "narrative", "recommendation", "confidence",
                 "context", "primary_result", "cached_tool_results", "run_context"}
    assert not (fields & forbidden), (
        f"SupervisorInput exposes {fields & forbidden}; a field that can hold the "
        "primary's output reintroduces the leak the signature closed"
    )
    assert fields == {"task_framing", "entity_ids", "posture"}


# ---------------------------------------------------------------------------
# 2. The behavioural cross-check: no primary token in the supervisor's bytes.
# ---------------------------------------------------------------------------


def test_no_primary_token_appears_in_the_supervisor_spawn_bytes():
    """§6.4(1),(5). The scan corpus is the primary's real output tokens, and the
    haystack is exactly the bytes the supervisor thread is spawned with — not a
    prose summary of them."""
    spawn = build_supervisor_input(_intent())
    leaked = independence_report(spawn, _primary())
    assert leaked == (), f"primary tokens reached the supervisor spawn: {leaked}"


def test_the_scan_is_not_vacuous_the_corpus_is_non_empty():
    """Phase 1 lesson #1: a scan over an empty corpus passes proving nothing. The
    primary must actually contribute distinctive tokens, or the previous test is
    green for the wrong reason."""
    corpus = _primary().all_tokens()
    assert len(corpus) >= 4
    assert any(SENTINEL_RECO == t or SENTINEL_RECO in t for t in _primary().all_tokens()) or \
        SENTINEL_RECO in _primary().recommendation


# ---------------------------------------------------------------------------
# 3. Shared-context leak. The coordinator holds both; the supervisor is handed
#    only its spawn input.
# ---------------------------------------------------------------------------


def test_the_supervisor_agent_work_signature_cannot_receive_the_primary():
    """§6.4. ``SupervisorAgent.work`` takes the spawn input and a bearer — nothing
    else. There is no ``primary``/``context`` parameter, so the coordinator cannot
    'helpfully' pass the first opinion in even if it wanted to."""
    params = set(inspect.signature(SupervisorAgent.work).parameters) - {"self"}
    assert params == {"spawn", "bearer"}, (
        f"SupervisorAgent.work parameters are {params}; anything beyond the spawn "
        "input and the bearer is a channel for the primary's conclusion"
    )


def test_the_harness_computes_agreement_it_does_not_read_it_off_the_supervisor():
    """§6.4(6). The supervisor never receives the primary, so 'agreement' can only be
    a comparison the coordinator makes after both are in hand. Prove the flag tracks
    the two independent recommendations, not a value the supervisor was told."""
    transport = DomainReadTransport()
    harness = Harness(SupervisorAgent(transport=transport, decider=_honest_supervisor_decider))
    result = harness.second_opinion_for(_intent(), _primary(), "tok")

    # The supervisor recommended "hold for review"; the primary the sentinel. They
    # differ, so the coordinator must have compared them — it could not have copied.
    assert result.agrees_with_primary is False
    assert result.second_opinion.recommendation == "hold for review"
    # And the supervisor's output carries none of the primary's tokens.
    assert SENTINEL_RECO not in result.second_opinion.recommendation
    assert SENTINEL_NARRATIVE not in result.second_opinion.strongest_counter_argument


def test_disagreement_does_not_block_proceeding():
    """§6.4(6): "prose-agreement is not required to proceed — the human decides."
    A harness that refused to continue on disagreement would quietly convert the
    supervisor into a veto, which is a different control than the spec's."""
    transport = DomainReadTransport()
    harness = Harness(SupervisorAgent(transport=transport, decider=_honest_supervisor_decider))
    # Disagreement is produced; the call still returns a full result rather than raising.
    result = harness.second_opinion_for(_intent(), _primary(), "tok")
    assert isinstance(result, FanOutResult)
    assert result.agrees_with_primary is False


# ---------------------------------------------------------------------------
# 4. Cached tool results. §6.4(2): the supervisor re-executes its own reads and
#    may not consume the primary's cache.
# ---------------------------------------------------------------------------


def test_the_supervisor_reads_through_its_own_transport_not_the_primarys_cache():
    """§6.4(2). The supervisor's evidence is a SECOND draw. Prove it by giving the
    primary a cache full of sentinels and a distinct transport to the supervisor,
    then asserting the supervisor's reads went out over its own transport and its
    result contains none of the cached sentinels."""
    primary = _primary()
    supervisor_transport = DomainReadTransport(
        responder=lambda call: {"independentlyFetched": call.path}
    )
    harness = Harness(
        SupervisorAgent(transport=supervisor_transport, decider=_honest_supervisor_decider)
    )

    result = harness.second_opinion_for(_intent(), primary, "tok")

    # The supervisor issued its own GETs — one per entity — over its own transport.
    assert len(supervisor_transport.calls) == len(_intent().entity_ids)
    assert all(c.method == "GET" for c in supervisor_transport.calls)
    # None of the primary's cached sentinels appear in the supervisor's output.
    assert SENTINEL_CACHED not in result.second_opinion.strongest_counter_argument
    assert SENTINEL_CACHED not in "".join(result.second_opinion.key_factors)


def test_the_supervisor_transport_is_a_different_object_than_any_primary_cache():
    """Two draws means two transports. If the supervisor shared the primary's
    transport, its 'independent' reads could be served from a warmed cache — the
    correlated-error risk §6.4(2) and risk 2 name. Prove the objects are distinct."""
    primary_transport = DomainReadTransport()
    supervisor_transport = DomainReadTransport()
    assert primary_transport is not supervisor_transport
    agent = SupervisorAgent(transport=supervisor_transport, decider=_honest_supervisor_decider)
    assert agent.transport is supervisor_transport
    assert agent.transport is not primary_transport


# ---------------------------------------------------------------------------
# 5. The artifact / trace-envelope channel. The supervisor input is built from
#    the intent, so no artifact or trace frame the primary produced can reach it.
# ---------------------------------------------------------------------------


def test_a_primary_artifact_cannot_be_smuggled_through_the_intent():
    """§6.4(1). Even if a caller tries to stuff the primary's recommendation into the
    banker intent's framing (the artifact-leak route), the intent is the banker's
    words by construction. Model the attack: a framing that embeds the sentinel is a
    caller error, but if it somehow occurs the scan still catches it — defence in
    depth. Here we assert the *legitimate* intent carries no primary tokens, and
    that a poisoned one is caught, so neither silently passes."""
    clean = build_supervisor_input(_intent())
    assert independence_report(clean, _primary()) == ()

    poisoned = BankerIntent(
        task_framing=f"Work it up. {SENTINEL_RECO}",  # simulate an artifact bleed
        entity_ids=("txn_delgado_1",),
    )
    leaked = independence_report(build_supervisor_input(poisoned), _primary())
    assert SENTINEL_RECO in leaked, (
        "the scan failed to catch a primary token injected into the framing; a real "
        "artifact bleed would then be invisible"
    )


# ---------------------------------------------------------------------------
# 6. Subagents cannot propose. §6.3.
# ---------------------------------------------------------------------------


def test_a_subagent_is_never_offered_propose_action():
    """§6.3: "subagents inherit the parent's capability allowlist and cannot call
    ``propose_action``. Only the root harness proposes." The supervisor is a
    subagent; if it could propose, it could both review and act."""
    parent_tools = ("get_flagged_transaction", "list_account_transactions", "propose_action")
    child_tools = subagent_tool_ids(parent_tools)
    assert "propose_action" not in child_tools
    assert set(child_tools) == {"get_flagged_transaction", "list_account_transactions"}


def test_subagent_read_tools_are_a_subset_of_the_parents():
    """§6.3: 'inherit', so a subagent cannot gain a tool the parent lacked — the
    floor is the parent's read set, and the only thing removed is the write-shaped
    affordance."""
    parent_tools = ("get_user", "get_account", "propose_action")
    child_tools = subagent_tool_ids(parent_tools)
    assert set(child_tools).issubset(set(parent_tools))
    assert set(parent_tools) - set(child_tools) == {"propose_action"}


# ---------------------------------------------------------------------------
# 7. The positive control — proof the scan can fail.
# ---------------------------------------------------------------------------


def test_a_leaky_builder_is_caught_by_the_scan_positive_control():
    """The honest test in the file. A tampered builder that folds the primary's
    narrative into the framing MUST be caught, or every green scan above is worth
    nothing. This models the exact regression the structural signature test guards
    against, and proves the behavioural net underneath it has holes of the right
    size."""
    primary = _primary()

    def leaky_build(intent: BankerIntent, primary_result: PrimaryResult) -> SupervisorInput:
        # The mistake §6.4 forbids: "context for the supervisor".
        return SupervisorInput(
            task_framing=f"{intent.task_framing}\n\nPrimary said: {primary_result.narrative}",
            entity_ids=tuple(intent.entity_ids),
        )

    leaked = independence_report(leaky_build(_intent(), primary), primary)
    assert leaked != (), (
        "the scan did NOT catch a builder that embedded the primary's narrative; the "
        "clean runs above are therefore not evidence of anything"
    )
    # And the specific sentinel tokens are named, not just 'something leaked'.
    assert any("SENTINEL" in t for t in leaked)
