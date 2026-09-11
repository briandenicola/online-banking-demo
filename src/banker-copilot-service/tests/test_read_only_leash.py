"""Write actions were cut from the demo, so prove the cut is structural and not editorial.

A scope cut that lives only in the demo script is not a scope cut. If a banker types a write
objective on stage — or an attendee asks them to try one — the planner must not walk the propose
path, because the money-path work behind it is unfinished (see
`.squad/decisions/inbox/turk-account-ownership-binding.md`).

There are TWO doors to a propose step, which is why there are two layers and why these tests
exercise both:

  1. the intent model choosing an action from the catalogue, and
  2. `_plan_steps` building a propose step from an `action_id` with no model involved at all.

A leash on the model alone would be a leash with a second door. The tests that matter most here
are the ones asserting **no approval record was created** — `forbidden_action` on the wire is the
banker-facing half, but `authority.propose_calls == []` is the half that means money did not move.

Both layers were verified to BITE rather than assumed to: disabling layer 2 fails
`test_a_scripted_propose_step_cannot_reach_authority_either` with a real approval reaching the
fake authority, and disabling layer 1 fails
`test_the_model_is_shown_no_proposable_action_at_all`.

One result from that exercise is worth stating plainly, because it is a limit of these tests.
With layer 1 disabled, the OUTCOME tests still passed — layer 2 caught the run and emitted the
same `forbidden_action`. That is defence in depth doing its job, and it also means a layer-1
regression is invisible to every test here except the boundary one that reads back what the model
was actually handed. Which is the argument for that test existing: outcome assertions cannot
distinguish "the model was never offered an action" from "the model was offered one and something
downstream caught it", and only the first is the leash the scope cut claims.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.config import PROPOSE_ENABLED_ENV, load_settings
from conftest import judging_assessor, shipped_assessment_limits

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.intent_model import IntentDecision, build_intent_prompt
from app.planner.loop import Planner, PlannerRequest

from test_demo_prompt_acceptance import (
    _Authority,
    _Executor,
    _Registry,
    _Session,
    _Store,
    _answerer_requiring_evidence,
)

WRITE_OBJECTIVE = "Refund a $35 overdraft fee on retail's checking as goodwill"
READ_OBJECTIVE = "Summarise casey's accounts and recent activity"


async def _run(
    decision: IntentDecision,
    objective: str,
    *,
    propose_enabled: bool,
    action_id=None,
    payload=None,
):
    authority = _Authority()
    store = _Store()
    captured: dict[str, object] = {}

    async def selector(obj: str, **kwargs) -> IntentDecision:
        captured.update(kwargs)
        return decision

    planner = Planner(
        registry=_Registry(),
        executor=_Executor(),
        authority=authority,
        max_iterations=20,
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
        intent_selector=selector,
        answerer=_answerer_requiring_evidence,
        store=store,
        propose_enabled=propose_enabled,
    )
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    stream = runs.create("run_leash", "sess_leash")
    await planner.run(
        PlannerRequest(
            session=_Session(),
            run_id="run_leash",
            objective=objective,
            action_id=action_id,
            payload=dict(payload or {}),
            facts=dict(payload or {}),
            bearer_token="tok",
        ),
        stream,
    )
    return list(runs.sink._frames["run_leash"]), authority, captured  # type: ignore[attr-defined]


def _codes(frames) -> list[str]:
    out = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"code", "error", "reasonCode"} and isinstance(value, str) and value:
                    out.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(list(frames))
    return out


# --------------------------------------------------------------------------------------
# Door 1: the model choosing an action.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_write_objective_is_refused_as_forbidden_not_unmappable():
    """The refusal CODE is the deliverable, not merely the fact of a refusal.

    "I won't, and here is where that authority lives" is a far better answer on stage than "I
    can't find anything that does that" — and the latter is the confabulation shape that has
    bitten this planner repeatedly. Any of `objective_unmappable` or
    `authority_catalogue_unavailable` here would be a regression even though all three refuse.
    """
    decision = IntentDecision(
        kind="propose",
        action_id="account.balance.adjust",
        payload_draft={"amount": "35.00", "direction": "credit", "reason": "goodwill"},
        subject_hints={"customer": "retail", "accountType": "checking"},
    )
    frames, _authority, _ = await _run(decision, WRITE_OBJECTIVE, propose_enabled=False)

    codes = _codes(frames)
    assert "forbidden_action" in codes, codes
    assert "objective_unmappable" not in codes, codes
    assert "authority_catalogue_unavailable" not in codes, codes


@pytest.mark.asyncio
async def test_a_refused_write_objective_creates_no_approval_record():
    """The half that means money did not move.

    A `forbidden_action` frame proves what the banker was told. Only an empty `propose_calls`
    proves nothing reached authority, and that is the claim the scope cut actually makes.
    """
    decision = IntentDecision(
        kind="propose",
        action_id="account.balance.adjust",
        payload_draft={"amount": "35.00", "direction": "credit", "reason": "goodwill"},
        subject_hints={"customer": "retail", "accountType": "checking"},
    )
    _frames, authority, _ = await _run(decision, WRITE_OBJECTIVE, propose_enabled=False)

    assert authority.propose_calls == []


@pytest.mark.asyncio
async def test_the_model_is_shown_no_proposable_action_at_all():
    """Layer 1 at its boundary: what the model was HANDED, not what it happened to answer.

    Read back from the selector rather than inferred from the outcome, because a model that
    refuses for its own reasons would make a leaky catalogue look leashed.
    """
    decision = IntentDecision(kind="refuse", reason_code="forbidden_action", message="no")
    _frames, _authority, captured = await _run(decision, WRITE_OBJECTIVE, propose_enabled=False)

    assert captured["actions"] == []
    assert captured["forbidden_actions"], "the model must still see where the authority lives"


@pytest.mark.asyncio
async def test_the_leash_is_off_by_default_for_the_library():
    """Guards against the leash becoming unconditional and silently deleting the propose path.

    The acceptance corpus still exercises propose on purpose — writes come back one day and that
    coverage is the record of how they worked — so a change that leashed the library everywhere
    would hide behind a green suite rather than failing.
    """
    decision = IntentDecision(kind="refuse", reason_code="forbidden_action", message="no")
    _frames, _authority, captured = await _run(decision, WRITE_OBJECTIVE, propose_enabled=True)

    assert captured["actions"], "propose_enabled=True must still offer actions"


# --------------------------------------------------------------------------------------
# Door 2: a propose step planned without the model.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_scripted_propose_step_cannot_reach_authority_either():
    """The second door. `_plan_steps` builds a propose step from `action_id` with no model.

    This is the test that makes "structurally unreachable" true rather than aspirational: it
    bypasses the intent model entirely, exactly as the scripted prompts do.
    """
    decision = IntentDecision(kind="refuse", reason_code="forbidden_action", message="n/a")
    payload = {
        "accountId": "acct_retail_checking",
        "amount": "35.00",
        "direction": "credit",
        "reason": "goodwill",
    }
    frames, authority, _ = await _run(
        decision,
        WRITE_OBJECTIVE,
        propose_enabled=False,
        action_id="account.balance.adjust",
        payload=payload,
    )

    assert authority.propose_calls == []
    assert "forbidden_action" in _codes(frames)


# --------------------------------------------------------------------------------------
# The read path — the demo spine.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_read_objective_is_unaffected_by_the_leash():
    """The leash must cost the demo nothing. Read is 3/3 in the cloud and must stay there."""
    decision = IntentDecision(
        kind="read",
        read_plan=[{"toolId": "list_customer_accounts", "arguments": {}}],
        answer_goal="Summarise the accounts",
        subject_hints={"customer": "casey"},
    )
    frames, authority, _ = await _run(decision, READ_OBJECTIVE, propose_enabled=False)

    codes = _codes(frames)
    assert "forbidden_action" not in codes, codes
    assert authority.propose_calls == []
    assert any(f.get("kind") == "run.done" for f in frames)


@pytest.mark.asyncio
async def test_the_read_path_behaves_identically_with_the_leash_on_and_off():
    """Differential, because "reads still work" is weaker than "reads are unchanged".

    A leash that subtly altered the read plan would pass the test above while degrading the one
    path the demo depends on.
    """
    def decision():
        return IntentDecision(
            kind="read",
            read_plan=[{"toolId": "list_customer_accounts", "arguments": {}}],
            answer_goal="Summarise the accounts",
            subject_hints={"customer": "casey"},
        )

    leashed, leashed_authority, _ = await _run(decision(), READ_OBJECTIVE, propose_enabled=False)
    free, free_authority, _ = await _run(decision(), READ_OBJECTIVE, propose_enabled=True)

    assert [f.get("kind") for f in leashed] == [f.get("kind") for f in free]
    assert _codes(leashed) == _codes(free)
    assert leashed_authority.propose_calls == free_authority.propose_calls == []


# --------------------------------------------------------------------------------------
# The deployed default, and the prompt.
# --------------------------------------------------------------------------------------


def test_an_unset_env_var_means_leashed():
    """Fail closed. A new environment that never heard of this flag must not re-arm writes.

    Every other flag here reads "off unless asked"; this one reads the same way, but here "off"
    is the safe state, which is why the polarity was chosen rather than inherited.
    """
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop(PROPOSE_ENABLED_ENV, None)
        assert load_settings().propose_enabled is False


@pytest.mark.parametrize("value,expected", [("1", True), ("0", False), ("", False), ("true", True)])
def test_the_flag_is_read_from_the_environment(value: str, expected: bool):
    with patch.dict(os.environ, {PROPOSE_ENABLED_ENV: value}):
        assert load_settings().propose_enabled is expected


def test_the_prompt_says_read_only_in_words_when_there_are_no_actions():
    """An empty JSON list is the underspecified action side that makes this model confabulate.

    Shown a bare `[]` it infers a reason and reports the inference as a fact about the bank.
    Told plainly, it refuses because the build is read-only — true, and the better sentence.
    """
    prompt = build_intent_prompt("x", actions=[], forbidden_actions=[], read_tools=[])

    assert "READ-ONLY" in prompt
    assert "forbidden_action" in prompt


def test_the_prompt_is_unchanged_when_actions_are_present():
    """A prompt is a shared global; two measured regressions this session came from editing one.

    The added text is conditional precisely so the corpus still measures the prompt it was
    baselined against.
    """
    prompt = build_intent_prompt(
        "x", actions=[{"id": "a"}], forbidden_actions=[], read_tools=[]
    )

    assert "READ-ONLY" not in prompt
