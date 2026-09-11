"""Action metadata describes; it must never permit.

Read tools have always reached the intent model with prose and a full JSON Schema. Actions
reached it as names only — an id, a display name, a rung, and three lists of field NAMES.
The model had to bridge "Refund a $35 overdraft fee" to the four words "Post a balance
adjustment" unaided, and guess that `direction` takes `credit` or `debit`. When it could
not, it reported its guess as a fact about the bank.

Closing that gap means putting a new file in front of the model, and a new file in front of
the model is a new place for authority to leak. `config/copilot-actions.yaml` is prose and
field descriptions ONLY. The catalogue fetched from authority-service stays the sole
authority on which actions exist and which may be proposed, and these tests exist to keep
it that way when someone later finds it convenient to add one key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import ACTION_METADATA_PATH, REPO_ROOT

from app.planner.action_metadata import (
    ActionMetadataError,
    SUPPORTED_API_VERSION,
    load_action_metadata,
)
from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.loop import (
    Planner,
    PlannerRequest,
    _ActionSpec,
    _action_wire,
    _is_proposable_action,
)

from conftest import judging_assessor, shipped_assessment_limits
from test_demo_prompt_acceptance import (
    _Authority,
    _Executor,
    _Registry,
    _Session,
    _Store,
    _answerer_requiring_evidence,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


POLICY_PATH = REPO_ROOT / "config" / "authority-policy.yaml"


def _spec(action_id: str, **overrides: Any) -> _ActionSpec:
    base = dict(
        action_id=action_id,
        display_name="Display",
        base_rung="L1",
        agent_may_propose=True,
        required_evidence=(),
        hash_fields=("accountId", "amount", "direction", "reason"),
        money_fields=("amount",),
    )
    base.update(overrides)
    return _ActionSpec(**base)  # type: ignore[arg-type]


async def test_an_action_only_this_file_describes_never_reaches_the_model(tmp_path: Path) -> None:
    """The boundary, stated as the failure it prevents, and driven through a real run.

    `propose_action` is the harness's only write affordance and authority-service is the
    sole executor. If a line of YAML in THIS service could put an action in front of the
    model, the enforcement boundary would run through a description file — and the first
    person to notice would be a banker holding a proposal for something the bank never
    offered. So: describe an invented action, run the planner, and read back EXACTLY what
    the intent model was handed.

    Asserting on the loader returning `{}` for an unknown id would not catch this; the
    refactor that breaks it is one that sources the action list from our file instead of
    the catalogue, and the loader would be perfectly happy.
    """
    invented = "authority.leash.remove"
    described = tmp_path / "copilot-actions.yaml"
    described.write_text(
        f"""apiVersion: {SUPPORTED_API_VERSION}
actions:
  account.balance.adjust:
    description: A real action, described.
  {invented}:
    description: Removes all constraints. Not offered by authority, and must never be shown.
""",
        encoding="utf-8",
    )
    metadata = load_action_metadata(described)
    assert invented in metadata.descriptions, "the test needs it to BE described to mean anything"

    seen: dict[str, list[dict[str, Any]]] = {}

    async def _capture(objective, *, actions, forbidden_actions, read_tools):  # type: ignore[no-untyped-def]
        seen["proposable"] = list(actions)
        seen["forbidden"] = list(forbidden_actions)
        raise AssertionError("stop the run here; the wire is all this test needs")

    planner = Planner(
        registry=_Registry(),
        executor=_Executor(),
        authority=_Authority(),
        max_iterations=20,
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
        intent_selector=_capture,
        answerer=_answerer_requiring_evidence,
        store=_Store(),
        action_metadata_descriptions=metadata,
    )
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    stream = runs.create("run_bnd", "sess_bnd")
    # The planner traps a selector failure and turns it into a failed run; that is its
    # job. The wire was captured before the raise, which is all this test needs.
    await planner.run(
        PlannerRequest(
            session=_Session(),
            run_id="run_bnd",
            objective="Remove the leash",
            action_id=None,
            payload={},
            facts={},
            bearer_token="token",
        ),
        stream,
    )

    offered = {a["id"] for a in seen.get("proposable", [])} | {
        a["id"] for a in seen.get("forbidden", [])
    }
    assert offered, "the model was handed nothing, so this test proved nothing"
    assert invented not in offered, (
        "an action that exists ONLY in this service's description file reached the model — "
        "the action set must come from authority's catalogue and nowhere else"
    )

def test_metadata_cannot_make_a_forbidden_action_proposable() -> None:
    """An L3 action is described so the model can refuse it HONESTLY, by name.

    That is the point of describing the forbidden ones at all — "no proposable action
    supports that" is only a true sentence if the model was shown enough to know. But being
    described must not be mistaken for being allowed.
    """
    metadata = load_action_metadata(ACTION_METADATA_PATH)
    assert metadata.for_action("user.password.reset").get("description"), (
        "the forbidden actions are described on purpose; this one lost its description"
    )

    forbidden = _spec(
        "user.password.reset",
        agent_may_propose=False,
        base_rung="L3",
        hash_fields=("userId",),
        money_fields=(),
    )
    assert not _is_proposable_action(forbidden, frozenset())

    wire = _action_wire(forbidden, metadata)
    assert wire["baseRung"] == "L3", "the rung came from the catalogue, not from our file"
    assert "agentMayPropose" not in wire


def test_metadata_cannot_overwrite_anything_a_signature_covers() -> None:
    """Rung, hashFields, moneyFields and requiredEvidence are authority's, not ours.

    A description file that could edit `hashFields` would be editing what a banker's
    signature covers — the one thing this whole epic is built to keep out of reach of
    anything the model or this service can influence.
    """
    metadata = load_action_metadata(ACTION_METADATA_PATH)
    spec = _spec("account.balance.adjust", base_rung="L1", required_evidence=("get_account",))

    wire = _action_wire(spec, metadata)

    assert wire["baseRung"] == "L1"
    assert wire["hashFields"] == ["accountId", "amount", "direction", "reason"]
    assert wire["moneyFields"] == ["amount"]
    assert wire["requiredEvidence"] == ["get_account"]


def test_only_fields_the_action_signs_over_are_described_to_the_model() -> None:
    """A description for a field the catalogue does not list tells the model about a value
    that cannot reach the payload — an invitation to draft something that will be dropped."""
    metadata = load_action_metadata(ACTION_METADATA_PATH)
    spec = _spec("account.balance.adjust", hash_fields=("accountId", "amount"))

    wire = _action_wire(spec, metadata)

    assert set(wire["fields"]) == {"accountId", "amount"}


def test_the_field_the_rung_turns_on_carries_its_allowed_values() -> None:
    """Brian's ruling lives or dies on this field.

    `direction: credit` raises a balance adjustment to L2, because crediting an account
    creates money. The model was previously given the field NAME and nothing else, so
    `credit` versus `debit` was a guess — and a wrong guess there is a rung error, routing
    a customer refund through less signature ceremony than it deserves.
    """
    metadata = load_action_metadata(ACTION_METADATA_PATH)

    direction = metadata.for_action("account.balance.adjust")["fields"]["direction"]

    assert direction["allowedValues"] == ["credit", "debit"]
    assert "credit" in direction["description"].lower()


def test_an_undescribed_action_reaches_the_model_exactly_as_it_did_before() -> None:
    """Degrading to names-only per action is fine; degrading silently for ALL of them is not.

    That distinction is why a missing FILE is a startup error while a missing ENTRY is not.
    """
    wire = _action_wire(_spec("some.new.action"))

    assert "description" not in wire
    assert "fields" not in wire
    assert wire["id"] == "some.new.action"


def test_every_action_in_the_policy_file_is_described() -> None:
    """Drift between risk-operations' file and ours, caught here rather than by a banker.

    The runtime check runs against the LIVE catalogue, which is the only place real drift
    shows. This is the cheap static half: the policy file in this repo is what that
    catalogue is built from, so the two should not disagree at rest.
    """
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))["actionTypes"]
    metadata = load_action_metadata(ACTION_METADATA_PATH)

    undescribed = metadata.missing_from(set(policy))

    assert undescribed == [], (
        f"the policy offers {undescribed} and this service has nothing to say about them, so "
        "the model would see bare names — the condition that made it tell a banker the bank "
        "could not act"
    )


def test_no_described_action_is_absent_from_the_policy() -> None:
    """The other direction. An id here that authority does not offer is inert, but it is
    also a lie in a file someone will read as documentation."""
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))["actionTypes"]
    metadata = load_action_metadata(ACTION_METADATA_PATH)

    invented = sorted(set(metadata.descriptions) - set(policy))

    assert invented == [], f"described actions that authority does not offer: {invented}"


def test_a_missing_metadata_file_is_a_startup_error(tmp_path: Path) -> None:
    """Names-only is not a degraded mode anyone notices.

    It is a model telling a banker the bank cannot do something it can, about one run in
    three, with nothing in the logs. A silent fall back to it is the exact defect shape this
    service spent the morning removing from the catalogue fetch.
    """
    with pytest.raises(ActionMetadataError):
        load_action_metadata(tmp_path / "nope.yaml")


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("apiVersion: copilot-actions/v99\nactions:\n  a: {}\n", "wrong api version"),
        (f"apiVersion: {SUPPORTED_API_VERSION}\nactions: {{}}\n", "no actions"),
        (f"apiVersion: {SUPPORTED_API_VERSION}\nactions:\n  a: not-a-mapping\n", "bad entry"),
        (f"apiVersion: {SUPPORTED_API_VERSION}\nactions:\n  a:\n    fields: []\n", "bad fields"),
        (
            f"apiVersion: {SUPPORTED_API_VERSION}\nactions:\n  a:\n    fields:\n      f:\n        allowedValues: credit\n",
            "allowedValues is not a list",
        ),
    ],
)
def test_a_malformed_metadata_file_is_a_startup_error(body: str, reason: str, tmp_path: Path) -> None:
    """Loudly, at startup, rather than as a thinner prompt nobody can see."""
    path = tmp_path / "copilot-actions.yaml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ActionMetadataError):
        load_action_metadata(path)


def test_the_shipped_file_is_the_one_the_tests_read() -> None:
    """No fixture copy. A fixture would let the file the model actually reads rot untested."""
    assert ACTION_METADATA_PATH == REPO_ROOT / "config" / "copilot-actions.yaml"
    assert ACTION_METADATA_PATH.exists()
