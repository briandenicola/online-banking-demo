"""Blind construction of the L2 supervisor, proven against the SHIPPING harness.

This is the promotion of the ``phase3-supervisor-blind-construction`` integration-ledger
entry (``banker-copilot-service.Tests/pending-integration.manifest.json``). The oracle
(``spec/supervisor.py``) proved the SPECIFICATION admits a leak-free construction; these tests
prove ``app.planner.fanout`` — the module the harness actually spawns from — is blind.

The load-bearing property (epic §6.4): the supervisor's input is constructed from the banker
intent and raw entity ids ONLY. Never the primary's plan, narrative, recommendation, confidence
or cached reads. Independence is STRUCTURAL (no parameter to leak through), with a token-scan as
a cross-check that is written to be able to fail.
"""

from __future__ import annotations

import inspect

import pytest

from app.planner.fanout import (
    BankerIntent,
    PrimaryResult,
    SUPERVISOR_POSTURE,
    SupervisorAgent,
    SupervisorInput,
    build_supervisor_input,
    builder_accepts_only_intent,
    extract_entity_ids,
    independence_report,
    subagent_tool_ids,
)


# A primary result stuffed with distinctive tokens that must NEVER reach the supervisor.
PRIMARY = PrimaryResult(
    plan=("pull_kyc_zt7", "score_risk_zt7"),
    narrative="The payment to beneficiary QURKLE9 is consistent with prior payroll runs.",
    recommendation="approve-immediately",
    confidence=0.97,
    cached_tool_results={"get_flagged_transaction": {"beneficiary": "QURKLE9", "verdict": "clean"}},
)

INTENT = BankerIntent(
    task_framing="Review the flagged wire on account acc_11 and its flagged transaction tx_1.",
    entity_ids=("acc_11", "tx_1"),
)


# --------------------------------------------------------------- structural ----


def test_the_builder_takes_only_the_intent():
    """The signature IS the control. If someone adds a ``primary`` parameter this is where it
    is caught, before any prompt-injection defence is even relevant."""
    assert builder_accepts_only_intent() is True
    assert tuple(inspect.signature(build_supervisor_input).parameters) == ("intent",)


def test_the_primary_has_no_argument_to_travel_through():
    """The dangerous edit is ``build_supervisor_input(intent, primary)``. Python's own argument
    binding refuses it — a leak is not blocked by a guard I wrote and could get wrong, it has no
    route to travel."""
    with pytest.raises(TypeError):
        build_supervisor_input(INTENT, PRIMARY)  # type: ignore[call-arg]


def test_the_supervisor_input_field_set_is_total():
    """The set of fields on the spawn input is the set of things the supervisor may know. No
    ``primary``, ``plan``, ``recommendation`` or ``context`` handle exists on it."""
    spawn = build_supervisor_input(INTENT)
    assert set(spawn.__dataclass_fields__) == {"task_framing", "entity_ids", "posture"}
    assert spawn.posture == SUPERVISOR_POSTURE
    # Frozen: nothing can staple the primary onto it after construction.
    with pytest.raises(Exception):
        spawn.task_framing = PRIMARY.narrative  # type: ignore[misc]


def test_the_supervisor_work_cannot_receive_the_primary():
    """``work`` takes only the spawn input and a bearer. There is no parameter through which the
    primary's result could be handed to the agent."""
    params = tuple(inspect.signature(SupervisorAgent.work).parameters)
    assert params == ("self", "spawn", "bearer")


# ------------------------------------------------------- behavioural cross-check ----


def test_no_primary_token_appears_in_the_spawn_bytes():
    """§6.4 behavioural cross-check. Empty is the pass. Runs over a NON-empty corpus, so it is
    not passing vacuously (Phase 1 lesson #1: a scan over an empty haystack proves nothing)."""
    assert PRIMARY.all_tokens(), "the scan corpus must be non-empty or this test is vacuous"
    spawn = build_supervisor_input(INTENT)
    assert independence_report(spawn, PRIMARY) == ()


def test_the_scan_is_able_to_fail():
    """Anti-vacuous. If a regression folded the primary's narrative into the framing, the scan
    MUST name the offending tokens. Proven by handing it exactly that leak and asserting it fires."""
    leaked = SupervisorInput(
        task_framing="Review the wire. Prior note: the beneficiary QURKLE9 is clean, approve-immediately.",
        entity_ids=("acc_11",),
    )
    report = independence_report(leaked, PRIMARY)
    assert "QURKLE9" in report
    assert "approve-immediately" in report


# ------------------------------------------------------------- entity ids ----


def test_entity_ids_come_from_the_banker_inputs_not_the_primary():
    """§6.4(1): the raw entity ids are pulled from the banker's own request, which exists before
    the primary runs. The primary's cached reads are never a source."""
    ids = extract_entity_ids(
        {"transactionId": "tx_1", "accountId": "acc_11", "decision": "cleared", "amount": 250000}
    )
    assert ids == ("acc_11", "tx_1")
    # A value from the primary's narrative is not an id-shaped key, so it cannot be swept in.
    assert "QURKLE9" not in extract_entity_ids({"note": "beneficiary QURKLE9"})


# ------------------------------------------------------------- subagent floor ----


def test_a_subagent_never_gets_propose_action():
    """§6.3: subagents inherit the read allowlist and CANNOT propose. Only the root harness holds
    the one write-shaped affordance."""
    offered = subagent_tool_ids(("get_flagged_transaction", "propose_action", "list_account_transactions"))
    assert "propose_action" not in offered
    assert set(offered) == {"get_flagged_transaction", "list_account_transactions"}
