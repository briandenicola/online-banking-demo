"""The live harness must not quietly model a smaller bank than production.

Every live-model number produced this session was measured against a tool surface **smaller
than the one the deployed service registers**, and that is not a cosmetic difference.

Measured, not reasoned. Adding exactly one read tool — `get_account_by_number`, which the real
manifest has always carried — to the fake registry moved the refund prompt's propose rate from
**7/12 to 2/12** across two matched n=12 live runs in one session. One tool. The model's action
mapping is sensitive to the *read* surface, not just to the prompt and the action catalogue.

Which means the read-tool list is a shared global with the same blast radius as the prompt, and
a harness that under-represents it produces numbers that cannot be compared with the cloud — the
likeliest candidate yet for the local/cloud divergence Danny has been carrying as unexplained.

This test does not close the gap; closing it needs executor fixtures for six more tools and
re-baselining every live measurement, which is a decision about evidence, not a patch. What it
does is make the gap **impossible to widen silently**, and impossible to forget.
"""

from __future__ import annotations

import pytest
import yaml

from conftest import MANIFEST_PATH

from test_demo_prompt_acceptance import _Registry

#: Tools the DEPLOYED service registers that the live harness does not model.
#:
#: Every entry here is a way the live suite's model sees a smaller bank than a banker does.
#: Shrink this list; never grow it. If a new tool ships and lands here by default, that is the
#: drift this test exists to catch.
KNOWN_UNMODELLED = {
    "get_account_application",
    "get_application_audit",
    "get_flagged_transaction",
    "get_transaction",
    "get_transfer",
    "list_account_applications",
}


def _manifest_tool_ids() -> set[str]:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {tool["toolId"] for tool in manifest["tools"]}


def test_the_harness_never_offers_a_tool_production_does_not_have():
    """A tool the real service lacks would let a live run prove a capability that does not exist."""
    invented = set(_Registry().tool_ids) - _manifest_tool_ids()

    assert invented == set(), (
        f"the live harness models tools the deployed manifest does not have: {sorted(invented)}"
    )


def test_the_gap_between_the_harness_and_production_does_not_widen():
    """The list is pinned, so a new unmodelled tool fails here instead of skewing a live number.

    Deliberately an equality check and not a subset check. A subset check would pass while the
    gap grew, which is precisely how a harness drifts away from the system it stands in for.
    """
    unmodelled = _manifest_tool_ids() - set(_Registry().tool_ids)

    assert unmodelled == KNOWN_UNMODELLED, (
        "the live harness's tool surface drifted from the deployed manifest. Measured effect of "
        "ONE tool on live action mapping: 7/12 -> 2/12 propose. Either model the new tool or "
        "update KNOWN_UNMODELLED deliberately, and re-baseline the live numbers if you do.\n"
        f"  now unmodelled: {sorted(unmodelled)}\n"
        f"  pinned:         {sorted(KNOWN_UNMODELLED)}"
    )


@pytest.mark.parametrize("tool_id", sorted(KNOWN_UNMODELLED))
def test_each_unmodelled_tool_is_named_so_the_gap_is_legible(tool_id: str):
    """One failing name per missing tool, rather than one opaque set difference.

    The gap is 6 of 15 — the harness models 60% of the bank. That number belongs in the test
    output where someone reading a live result will see it, not only in a decision record.
    """
    assert tool_id in _manifest_tool_ids(), (
        f"{tool_id} is pinned as unmodelled but is no longer in the manifest; remove it from "
        "KNOWN_UNMODELLED"
    )
