"""The ONE place the service shapes an approval's ``agentAssessment`` for the UI.

This module is deliberately NOT a client-shaper. It does not flatten the payload, assign
`material` flags, or produce `PayloadField[]`/`EvidenceRef[]`. That mapping lives in exactly one
place — ``ui-app/src/api/authorityWire.ts:toApproval`` — and the REST path already routes every
approval through it. The SSE path must do the same (see the decision record: emitting a
*client-shaped* approval from Python would either drop the payload rows — silently defeating the
material-field disclosure gate in ``ApprovalCard.tsx`` — or duplicate ``flattenPayload`` and its
currency/materiality hints across the language boundary, which is the exact class of bug this epic
keeps paying for).

What this module DOES own is the one thing the wire body cannot already carry: the supervisor's
second opinion is never persisted by ``authority-service`` (the harness registers zero write tools;
the opinion is evidence for a human, never a signature), so it exists only in the event stream. We
nest it under ``agentAssessment.supervisor`` — a shape ``toApproval.toAssessments`` ALREADY
tolerates — so the single mapper assigns the roles structurally, by KEY POSITION. A supervisor
assessment therefore cannot silently render as the primary: its role is not a droppable field but
the key it arrives under.
"""

from __future__ import annotations

from typing import Any, Mapping

PRIMARY_AGENT_NAME = "Primary agent"
SUPERVISOR_AGENT_NAME = "Independent supervisor"

# ``AgentAssessment.verdict`` (ui-app types.ts) is the token the card renders; the engine's
# internal token is ``recommendation``. They are now THE SAME WORD, deliberately.
#
# What was here before was a translation table — {"proceed": "APPROVE", "hold": "DECLINE"} with
# everything else falling to "CONDITIONAL" — and it was wrong in the way that matters most:
#
#   * ``decline``, the STRONGEST objection the supervisor can make, matched no key and landed on
#     the default arm, "CONDITIONAL" — the mildest word on the screen.
#   * ``hold``, the middle verdict meaning "resolve something first", rendered as "DECLINE".
#   * "APPROVE" and "CONDITIONAL" correspond to NO server verdict at all. "APPROVE" also
#     contradicts the card's own rule that agents never approve, only propose.
#   * The default arm made ``decline`` indistinguishable from "the model returned gibberish".
#     A fallback that looks like a real verdict is how a broken pipeline reads as a mild one.
#
# So the adapter no longer translates. It UPPERCASES for the caption and refuses anything outside
# the vocabulary. Presentation — label wording, colour, severity rank — belongs to the client and
# now lives in exactly one place there (ui-app supervisorVerdict.ts), which keys on these tokens.
#
# The vocabulary is READ from supervisor_model rather than restated here. The import is deferred
# because supervisor_model -> fanout -> approval_view is a real cycle at module-import time; by the
# time a verdict is rendered every module is loaded. A restatement would be a third copy of the
# rule that can drift from both of the two it claims to hold together.
UNRECOGNISED_VERDICT = "UNRECOGNISED"


def verdict_for(recommendation: str) -> str:
    from app.planner.supervisor_model import RECOMMENDATIONS

    token = recommendation.strip().casefold()
    return token.upper() if token in RECOMMENDATIONS else UNRECOGNISED_VERDICT


def primary_wire_assessment(approval: Mapping[str, Any]) -> dict[str, Any]:
    """The PRIMARY's assessment, in the wire shape ``toApproval.toAssessments`` consumes.

    Enriches the stored assessment with a ``verdict`` the card can render, derived ONLY from the
    primary's own declared recommendation (it PROPOSED the action, so absent an explicit token its
    verdict is to proceed). ``summary`` and evidence ids are the primary's own declared outputs,
    already on the approval — nothing here is re-derived from the primary's private reasoning.
    """
    existing = dict(approval.get("agentAssessment") or {})
    recommendation = str(existing.get("recommendation") or "proceed")
    existing.setdefault("agentName", PRIMARY_AGENT_NAME)
    existing["verdict"] = verdict_for(recommendation)
    summary = existing.get("summary")
    if summary and "rationale" not in existing:
        existing["rationale"] = summary
    ids = existing.get("evidenceToolIds")
    if ids and "citedEvidenceIds" not in existing:
        existing["citedEvidenceIds"] = list(ids)
    return existing


def supervisor_wire_assessment(
    agent_id: str, recommendation: str, confidence: float, counter_argument: str, key_factors, cited_evidence_ids
) -> dict[str, Any]:
    """The SUPERVISOR's second opinion, in the same wire shape.

    ``role`` is NOT set here on purpose: the single mapper assigns it from the ``supervisor`` key
    this dict arrives under, so it is structural and cannot be dropped. Nothing here is authored
    prose the supervisor could have echoed the primary into — the verdict is derived from its
    structural recommendation, the rationale is its own counter-argument, and the cited evidence is
    the ids of the tools it re-ran itself.
    """
    return {
        "agentId": agent_id,
        "agentName": SUPERVISOR_AGENT_NAME,
        "verdict": verdict_for(recommendation),
        "confidence": confidence,
        "rationale": counter_argument,
        "keyFactors": [{"label": factor, "value": "independently corroborated"} for factor in key_factors],
        "citedEvidenceIds": list(cited_evidence_ids),
    }
