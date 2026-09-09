"""The evidence ceiling: the primary may gather MORE than policy requires, never less (§P5).

What this module is
-------------------
One function — :func:`additional_evidence` — and the refusal record it produces. It answers a
single question: *of the tool ids the primary asked for, which may it have, and why not for the
rest?*

**It returns ADDITIONS. It cannot return a plan.** The signature is the control, the same move as
``build_supervisor_input(intent)``: the caller hands over what was REQUESTED and what was already
GATHERED, and gets back ids to add. There is no return value that can express "instead of",
"reorder", or "drop", so no model reply and no future edit inside this function can lower the
evidence floor. The floor is held one layer up and earlier, by ordering: required evidence is
gathered first and unconditionally, before the model is consulted at all. There is nothing to
validate because there is no sequence in which it happens.

**The budget is not a flag** (§P5.1). At ``budget=0`` this function still runs, still classifies
every request, and still returns a refusal for each one — ``budget_exhausted``. Nothing branches
on zero. That is what makes stage 1 a measurement of the shipping path rather than of a
configuration nobody runs, and ``refused`` is the only place stage 1's demand for the ceiling is
visible at all.

**Tool ids only, never arguments** (§P5.3). Nothing in this module accepts, constructs or returns
an argument. Arguments are bound by ``_bind_arguments`` from the banker's own inputs — session
context, payload, facts — exactly as they are for required evidence. That is the boundary that
matters most here: a model that could choose arguments could read *another customer's* account
and file it in *this* customer's approval record, which is a data-boundary breach dressed as
evidence gathering and a far larger hole than tool selection. A tool whose parameters cannot be
bound from those sources is refused as ``unbindable`` and never invented.

Nor does anything here touch a credential. The ceiling widens no authority because it changes no
identity: a discretionary read travels on the session's own bearer token, so a read the session
may not perform returns 403 upstream exactly as a required one would. **No discretionary read may
use any credential, token, header or identity other than the one the required reads used.** An
edit that needs a service identity to make a discretionary read succeed is undoing Gate A.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

# ---------------------------------------------------------------- refusal vocabulary ----
#
# A refusal is a positive stated fact with a NAMED reason, never a silent drop. Without the
# name, "did not look" and "was not allowed to look" read identically in the record.

BUDGET_EXHAUSTED = "budget_exhausted"
UNKNOWN_TOOL = "unknown_tool"
UNBINDABLE = "unbindable"
QUARANTINED = "quarantined"
ALREADY_GATHERED = "already_gathered"
#: Requested on the last permitted pass, when no further gathering step can run. Distinct from
#: `budget_exhausted` on purpose: conflating them would report unspent budget as spent and
#: corrupt the one number stage 1 exists to produce.
ITERATIONS_EXHAUSTED = "iterations_exhausted"
#: Recorded by the CALLER, not here — this module classifies requests before any read happens,
#: and a 403 is only knowable after one. Named here so the vocabulary has one home.
READ_REFUSED_403 = "read_refused_403"

REFUSAL_REASONS = (
    BUDGET_EXHAUSTED,
    UNKNOWN_TOOL,
    UNBINDABLE,
    QUARANTINED,
    ALREADY_GATHERED,
    ITERATIONS_EXHAUSTED,
    READ_REFUSED_403,
)

#: The §R5 quarantine, named rather than derived (Gate B evidence-contract ruling §R5).
#:
#: `list_login_audits` is filtered upstream by RECENCY, not by user, so no projection can honestly
#: assert whose logins are in the list. Gate B refused it a projection for that reason and closed
#: the front door; letting it in through a discretionary door would put an unfiltered global audit
#: list into one customer's approval record by another route.
#:
#: This is deliberately NOT spelled as "tools without a projection". §P5.4(3) rules that an
#: unprojected tool remains gatherable and its raw response stored — honest, because it is
#: labelled discretionary and asserts nothing about a subject. The quarantine is the narrower set
#: where raw storage would imply a subject that cannot be established, so it is stated by name and
#: a tool joins it by a human deciding it should.
DISCRETIONARY_QUARANTINE = frozenset({"list_login_audits"})


@dataclass(frozen=True)
class RefusedEvidenceRequest:
    """One request the harness declined, and why. Server-observed; the model asserts nothing here."""

    tool_id: str
    reason: str

    def to_wire(self) -> dict[str, str]:
        return {"toolId": self.tool_id, "reason": self.reason}


def additional_evidence(
    requested: Sequence[str],
    *,
    gathered: Iterable[str],
    known_tool_ids: Iterable[str],
    bindable_tool_ids: Iterable[str],
    budget: int,
    quarantined: Iterable[str] = DISCRETIONARY_QUARANTINE,
) -> tuple[tuple[str, ...], tuple[RefusedEvidenceRequest, ...]]:
    """Decide which requested tool ids are granted, and name a reason for every one that is not.

    Returns ``(granted, refused)``. ``granted`` is disjoint from ``gathered`` by construction, so
    a discretionary read can never satisfy a required evidence key even accidentally — Gate B's
    ``EvidenceComplete`` checks named keys and is untouched, strictly additive as ruled (§P5.4).

    Order of classification is deliberate: **budget is checked LAST.** A request for an unknown or
    quarantined tool is refused for what it is, and does not consume budget it was never going to
    spend. Refusing everything as ``budget_exhausted`` at stage 1 would be true but useless — the
    demand measurement needs to know that the model asked for a tool that does not exist.

    A duplicate request is refused once, by its first classification, and is not counted twice
    against the budget.
    """
    known = frozenset(known_tool_ids)
    bindable = frozenset(bindable_tool_ids)
    held = set(gathered)
    quarantine = frozenset(quarantined)

    granted: list[str] = []
    refused: list[RefusedEvidenceRequest] = []
    seen: set[str] = set()
    remaining = max(0, int(budget))

    for raw in requested:
        tool_id = str(raw).strip()
        if not tool_id or tool_id in seen:
            continue
        seen.add(tool_id)

        if tool_id in held:
            # The function returns ADDITIONS. Something already in hand is not one, and re-reading
            # it would put two draws of the same tool under one key with no way to say which is
            # which. A required read that FAILED never reaches here: that aborts the plan, so the
            # loop is not running. Stated because "correct via a fact about another code path" is
            # how a dependency nobody meant to create comes into existence.
            refused.append(RefusedEvidenceRequest(tool_id, ALREADY_GATHERED))
        elif tool_id in quarantine:
            refused.append(RefusedEvidenceRequest(tool_id, QUARANTINED))
        elif tool_id not in known:
            # A model naming a tool that does not exist is a model being wrong, not a config being
            # wrong. Refused by name and recorded; never fatal.
            refused.append(RefusedEvidenceRequest(tool_id, UNKNOWN_TOOL))
        elif tool_id not in bindable:
            refused.append(RefusedEvidenceRequest(tool_id, UNBINDABLE))
        elif remaining <= 0:
            # Stage 1 lands every well-formed request here, and this record is the whole
            # measurement: which tools the primary asked for and how often, from real runs,
            # which is the evidence for whether the stage-2 budget is the right one.
            refused.append(RefusedEvidenceRequest(tool_id, BUDGET_EXHAUSTED))
        else:
            granted.append(tool_id)
            remaining -= 1

    return tuple(granted), tuple(refused)


__all__ = [
    "ALREADY_GATHERED",
    "BUDGET_EXHAUSTED",
    "DISCRETIONARY_QUARANTINE",
    "ITERATIONS_EXHAUSTED",
    "QUARANTINED",
    "READ_REFUSED_403",
    "REFUSAL_REASONS",
    "RefusedEvidenceRequest",
    "UNBINDABLE",
    "UNKNOWN_TOOL",
    "additional_evidence",
]
