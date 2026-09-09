"""The verdict vocabulary has exactly one home, and comparison is tri-state (§P2.1, §P4.3).

Both facts are load-bearing and both are the kind that stop being true silently:

  * a second definition of the tuple is a translation table waiting to happen, and this repo
    has already shipped the bug that table causes (`decline` rendering as "CONDITIONAL"); and
  * a boolean agreement has two arms for a three-case comparison, so the third case lands on
    one of the other two — and either landing is a claim the system cannot support.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.planner import approval_view, verdicts
from app.planner.verdicts import (
    AGREE,
    DIVERGE,
    NOT_COMPARABLE,
    RECOMMENDATIONS,
    compare_verdicts,
    is_verdict,
)

APP_ROOT = Path(verdicts.__file__).resolve().parents[1]


def _modules_defining_the_vocabulary() -> list[str]:
    """Every .py file under app/ that ASSIGNS the literal verdict tuple.

    An AST walk rather than a grep for the words: a module that merely *imports* or *mentions*
    the tokens is fine, and a module that assigns them is a second home regardless of the name
    it gives them.
    """
    tokens = set(RECOMMENDATIONS)
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                continue
            literals = {
                el.value
                for el in value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            }
            if tokens <= literals:
                offenders.append(str(path.relative_to(APP_ROOT.parent)))
    return offenders


def test_the_verdict_vocabulary_is_defined_exactly_once():
    """§P2.1: one vocabulary, one home. A second definition is a defect on sight."""
    assert _modules_defining_the_vocabulary() == ["app/planner/verdicts.py"]


def test_approval_view_imports_the_vocabulary_normally_not_deferred():
    """The deferred import disappears with the move.

    ``verdict_for`` used to import RECOMMENDATIONS *inside its own body* to dodge the
    supervisor_model -> fanout -> approval_view cycle. A cycle worked around is a design
    statement nobody made deliberately; this asserts the workaround is gone rather than
    trusting that nobody reintroduces it.
    """
    source = inspect.getsource(approval_view.verdict_for)
    assert "import" not in source, source


@pytest.mark.parametrize("token", RECOMMENDATIONS)
def test_every_vocabulary_token_is_a_verdict(token):
    assert is_verdict(token)


@pytest.mark.parametrize("token", ["", None, "PROCEED?", "approve", "conditional", 0.94, []])
def test_nothing_outside_the_vocabulary_is_a_verdict(token):
    assert not is_verdict(token)


def test_matching_verdicts_agree():
    assert compare_verdicts("proceed", "PROCEED") == AGREE


def test_different_verdicts_diverge():
    assert compare_verdicts("proceed", "hold") == DIVERGE


@pytest.mark.parametrize(
    "primary,supervisor",
    [
        (None, "hold"),
        ("proceed", None),
        ("", ""),
        ("gibberish", "gibberish"),
    ],
)
def test_a_side_with_no_verdict_is_not_comparable(primary, supervisor):
    """§P4.3. Two absent verdicts are not consensus, and two identical unreadable strings are
    agreement by coincidence, not by review. Both land on the third arm."""
    assert compare_verdicts(primary, supervisor) == NOT_COMPARABLE
