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

from typing import Any, Mapping, Sequence

from app.planner.verdicts import RECOMMENDATIONS, UNRECOGNISED_VERDICT, is_verdict

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
# The vocabulary is READ from `app.planner.verdicts` rather than restated here. It used to be
# read from `supervisor_model` through a DEFERRED import, because supervisor_model -> fanout ->
# approval_view is a real cycle at module-import time. That cycle existed because the vocabulary
# was living in one agent's module while two agents used it; moving it to a neutral home (§P2.1)
# removes both the cycle and the deferred import. A restatement would be a third copy of the rule
# that can drift from both of the two it claims to hold together.


def verdict_for(recommendation: str) -> str:
    token = str(recommendation or "").strip().casefold()
    return token.upper() if token in RECOMMENDATIONS else UNRECOGNISED_VERDICT


def primary_wire_assessment(approval: Mapping[str, Any]) -> dict[str, Any]:
    """The PRIMARY's assessment, in the wire shape ``toApproval.toAssessments`` consumes.

    It ENRICHES what the primary actually stated with the caption the card renders. It no longer
    manufactures anything, and the two deletions matter more than the code that remains:

      * ``recommendation = str(existing.get("recommendation") or "proceed")`` invented a verdict
        for an agent that stated none. That default is how "Primary agent — PROCEED" came to be
        rendered over an assessment nobody made, and — once the primary could FAIL — it would
        have manufactured a position for a failed agent, against which a supervisor ``hold``
        renders as genuine dissent. A defaulted verdict is not a smaller lie than a fabricated
        rationale; it is the same lie in the field a reader trusts most.
      * ``existing["rationale"] = summary`` promoted the banker's echoed objective into the
        primary's reasoning. The proposal no longer sends ``summary`` at all.

    After this work the assessment either arrived and parsed, or it failed and says so. There is
    no third state for a default to serve — and while the default existed, the failure was
    invisible.

    A missing verdict therefore stays missing. The client's ``AgentAssessment.verdict`` is
    optional, so it renders as absent rather than as a mild verdict; ``failure`` and the failsafe
    ``rationale`` are what say, positively, that no assessment was formed.
    """
    existing = dict(approval.get("agentAssessment") or {})
    existing.setdefault("agentName", PRIMARY_AGENT_NAME)
    recommendation = existing.get("recommendation")
    if is_verdict(recommendation):
        existing["verdict"] = verdict_for(str(recommendation))
    elif recommendation is not None:
        # A token that is not a verdict is not permission and is not silence either. It is a
        # contract violation, and it is named as one.
        existing["verdict"] = UNRECOGNISED_VERDICT
    ids = existing.get("evidenceToolIds")
    if ids and "citedEvidenceIds" not in existing:
        existing["citedEvidenceIds"] = list(ids)
    return existing


def primary_proposal_assessment(
    assessment,
    *,
    required_evidence_tool_ids: Sequence[str],
    discretionary_evidence_tool_ids: Sequence[str],
    refused_evidence_requests: Sequence[Mapping[str, str]],
    assessment_iterations: int,
    converged: bool,
) -> dict[str, Any]:
    """The primary's assessment as it goes ONTO the proposal — the body authority-service stores.

    Two provenances, deliberately not blurred (§P3.3, §P5.5):

      * the model's CLAIM — verdict, confidence, rationale, key factors, what it could not
        verify. Its citations have already been checked against what was gathered, by the parser.
      * the harness's OBSERVATION — which tools the policy required, which the model was granted
        beyond them, which requests were refused and why, how many passes it took and whether it
        stopped because it was satisfied. Every one of these is server-derived; not one of them
        is read off the model.

    ``requiredEvidenceToolIds`` is a CONTROL and ``discretionaryEvidenceToolIds`` is a CHOICE.
    They stay in separate fields because "the copilot reviewed the account" must not mean
    something different run to run while reading identically.

    There is **no ``value`` parameter and no ``concern`` parameter**, here or on ``KeyFactor``. A
    flat model factor is a statement, not a dimension-and-measurement pair, so there is no second
    half to populate and anything populating one is invented. A future edit that wants one has to
    widen this signature, and that widening is what the key-factor shape test catches.
    """
    wire: dict[str, Any] = {
        "agentName": PRIMARY_AGENT_NAME,
        # Server-observed, never model-asserted. `evidenceToolIds` remains the full gathered set
        # so the record's statement of WHAT WAS GATHERED is an observation; only the citations
        # below are the model's claim.
        "evidenceToolIds": sorted({*required_evidence_tool_ids, *discretionary_evidence_tool_ids}),
        "requiredEvidenceToolIds": list(required_evidence_tool_ids),
        "discretionaryEvidenceToolIds": list(discretionary_evidence_tool_ids),
        "refusedEvidenceRequests": [dict(r) for r in refused_evidence_requests],
        "assessmentIterations": assessment_iterations,
        # A POSITIVE recorded fact, never an absence. Without it, "hit the cap while still
        # unsatisfied" and "was satisfied on the first pass" read identically.
        "converged": converged,
        "rationale": assessment.rationale,
    }

    if assessment.verdict is not None:
        wire["recommendation"] = assessment.verdict
    if assessment.self_reported_confidence is not None:
        # Absent on a failed assessment, never 0.0. A zero is a number: it can be plotted,
        # averaged and compared, and a sentinel number gets pooled into a statistic by accident.
        #
        # The field is still spelled `confidence` on the wire because the rename to
        # `selfReportedConfidence` crosses the language boundary and the golden wire, and the
        # ruling defers it (§P7.2, §P9). What is required NOW and holds here: nothing ranks,
        # sorts, colour-scales or gates on this number, and no threshold on it exists anywhere.
        wire["confidence"] = assessment.self_reported_confidence
    if assessment.key_factors:
        wire["keyFactors"] = [
            {"label": factor.label, "citedEvidenceIds": list(factor.cited_evidence_ids)}
            for factor in assessment.key_factors
        ]
        cited = sorted({c for factor in assessment.key_factors for c in factor.cited_evidence_ids})
        if cited:
            wire["citedEvidenceIds"] = cited
    if assessment.unverified:
        # The primary's honest half of the asymmetry: what it could NOT establish. Optional,
        # because absent is honest and an empty-string filler is not.
        wire["unverified"] = list(assessment.unverified)
    if assessment.requested_evidence:
        wire["requestedEvidenceToolIds"] = list(assessment.requested_evidence)
    if assessment.failure is not None:
        # A stated failure, not an absence a renderer is left to interpret. The client's fields
        # are all optional, so a missing verdict renders as blank; this is the positive value on
        # the wire that says which failure occurred.
        wire["failure"] = assessment.failure
        wire["failureReason"] = assessment.failure_reason
    if assessment.attribution is not None:
        wire.update(assessment.attribution.to_wire())
    return wire


def supervisor_wire_assessment(
    agent_id: str,
    recommendation: str,
    confidence: float,
    counter_argument: str,
    key_factors,
    cited_evidence_ids,
    attribution=None,
) -> dict[str, Any]:
    """The SUPERVISOR's second opinion, in the same wire shape.

    ``role`` is NOT set here on purpose: the single mapper assigns it from the ``supervisor`` key
    this dict arrives under, so it is structural and cannot be dropped. Nothing here is authored
    prose the supervisor could have echoed the primary into — the verdict is derived from its
    structural recommendation, the rationale is its own counter-argument, and the cited evidence is
    the ids of the tools it re-ran itself.

    ``keyFactors`` carries the supervisor's OWN stated factors and nothing else. Each used to be
    paired with the constant string "independently corroborated", which was not a value read off
    anything — no corroboration is performed, and the sentinel ``supervisor_unavailable`` that
    ``_failsafe`` emits when the model could not be reached rendered as
    "supervisor_unavailable — independently corroborated". A factor is a STATEMENT, not a
    measurement, so it carries a label and no value; the client decides how to show it.
    ``concern`` is likewise omitted rather than defaulted: this decider does not classify its own
    factors, and defaulting the field would let the card assert a judgement nobody made.
    """
    return {
        "agentId": agent_id,
        "agentName": SUPERVISOR_AGENT_NAME,
        "verdict": verdict_for(recommendation),
        "confidence": confidence,
        "rationale": counter_argument,
        "keyFactors": [{"label": factor} for factor in key_factors],
        "citedEvidenceIds": list(cited_evidence_ids),
        # Attribution (§P7.1): which decider, which model, which exact bytes. Carried on BOTH
        # assessments so a reader can see for themselves that the "independent" second opinion
        # came from the same base model as the primary — a residual correlation that cannot be
        # engineered away this week and so must be disclosed rather than papered over.
        **(attribution.to_wire() if attribution is not None else {}),
    }
