"""The verdict vocabulary — ONE closed set, in one neutral home (ruling §P2.1).

Two agents now state verdicts: the primary assessor (`primary_model.py`) and the independent
supervisor (`supervisor_model.py`). Agreement between them is computed by string comparison, so
a second vocabulary would need a translation table between the two — and this repo has already
shipped the bug that table causes: `decline`, the strongest objection available, matched no key
and fell through to ``"CONDITIONAL"``, the mildest word on the screen, indistinguishable from
"the model returned gibberish".

So the tuple lives here rather than in either agent's module. It used to live in
``supervisor_model``, and ``approval_view`` reached it through a *deferred* import to dodge the
``supervisor_model -> fanout -> approval_view`` cycle. That location was right when the
vocabulary belonged to one agent and is wrong now: a cycle worked around is a design statement
nobody made deliberately. This module imports nothing from the planner package, so every
consumer imports it normally.

**A second definition of this tuple, in any module or any language, is a defect on sight.**
"""

from __future__ import annotations

#: The closed verdict set, shared by both agents. Anything outside it is not a verdict, and a
#: thing that is not a verdict must never be treated as permission.
#:
#: The tokens read correctly for a proposer as well as a reviewer:
#:   proceed - taking THAT action is defensible on this evidence
#:   hold    - the evidence is insufficient or something needs resolving first
#:   decline - the evidence argues against taking THAT action
RECOMMENDATIONS = ("proceed", "hold", "decline")

#: What the card is shown when a token is not in the vocabulary. Deliberately NOT a real-looking
#: verdict: a fallback that reads like a mild verdict is how a broken pipeline renders as a
#: cautious one.
UNRECOGNISED_VERDICT = "UNRECOGNISED"

#: Tri-state agreement (§P4.3). ``not_comparable`` is returned whenever EITHER side has no
#: verdict — a side that failed has no position, and comparing against a manufactured one is the
#: classification error Livingston had to correct by hand, moved inside the code.
AGREE = "agree"
DIVERGE = "diverge"
NOT_COMPARABLE = "not_comparable"
AGREEMENT_STATES = (AGREE, DIVERGE, NOT_COMPARABLE)


def is_verdict(token: object) -> bool:
    """True only for a token inside the closed set. Empty, None and prose are all False."""
    return isinstance(token, str) and token.strip().casefold() in RECOMMENDATIONS


def compare_verdicts(primary: object, supervisor: object) -> str:
    """Tri-state comparison. ``not_comparable`` whenever either side stated no verdict.

    Deliberately NOT a boolean. A boolean has two arms and this comparison has three cases, so
    the third one has to land on one of the other two — and whichever it lands on is a claim the
    system is not entitled to make. ``False`` would report a dead pipeline as *dissent*; ``True``
    would report it as *consensus*, which is the banner sentence that has already shipped once
    over two absent verdicts.
    """
    if not is_verdict(primary) or not is_verdict(supervisor):
        return NOT_COMPARABLE
    p = str(primary).strip().casefold()
    s = str(supervisor).strip().casefold()
    return AGREE if p == s else DIVERGE


__all__ = [
    "RECOMMENDATIONS",
    "UNRECOGNISED_VERDICT",
    "AGREE",
    "DIVERGE",
    "NOT_COMPARABLE",
    "AGREEMENT_STATES",
    "is_verdict",
    "compare_verdicts",
]
