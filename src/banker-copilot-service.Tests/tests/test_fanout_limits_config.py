"""Fan-out limits are configuration, and the loader must FAIL CLOSED (epic §6.3, I-3).

Two failure modes are guarded here, mirroring the tool-manifest discipline:

  1. The shipped `config/harness-limits.yaml` must match the numbers the epic ratifies. The
     epic's own §6.3 text is parsed here rather than transcribed, so a change to either side is
     caught instead of a hand-copied expectation silently winning (the Phase 1 lesson).

  2. A missing, malformed, or out-of-bounds file must RAISE, never default. A hardcoded fallback
     concurrency ceiling is precisely what I-3 forbids.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

TESTS_ROOT = Path(__file__).resolve().parent.parent


def _repo_root() -> Path:
    d = TESTS_ROOT
    while d != d.parent:
        if (d / ".git").exists():
            return d
        d = d.parent
    raise RuntimeError("repository root not found")


REPO_ROOT = _repo_root()
SERVICE_ROOT = REPO_ROOT / "src" / "banker-copilot-service"
sys.path.insert(0, str(SERVICE_ROOT))

from app.planner.limits import (  # noqa: E402
    FanoutLimits,
    FanoutLimitsError,
    load_fanout_limits,
    parse_fanout_limits,
)

LIMITS_FILE = REPO_ROOT / "config" / "harness-limits.yaml"
EPIC = REPO_ROOT / "docs" / "epics" / "banker-copilot.md"


def _epic_limit(key: str) -> int:
    """Pull `key: N` out of the epic §6.3 code-font text rather than transcribing it."""
    text = EPIC.read_text(encoding="utf-8")
    match = re.search(rf"{re.escape(key)}:\s*(\d+)", text)
    assert match, f"epic §6.3 no longer states {key!r}; the config contract moved"
    return int(match.group(1))


def test_shipped_limits_match_the_epic():
    limits = load_fanout_limits(str(LIMITS_FILE))

    # Parsed straight from the epic — if §6.3 changes a number, this fails loudly.
    assert limits.max_concurrent_subagents == _epic_limit("maxConcurrentSubagents")
    assert limits.max_subagent_depth == _epic_limit("maxSubagentDepth")
    # These two are prose in §6.3 ("per-subagent tool budget 20", "wall-clock budget 60s").
    assert limits.per_subagent_tool_budget == 20
    assert limits.subagent_wall_clock_seconds == 60


def test_no_grandchildren_is_representable():
    # Depth 2 means the root spawns subagents and those may not spawn their own (§6.3).
    limits = load_fanout_limits(str(LIMITS_FILE))
    assert limits.max_subagent_depth == 2


def test_missing_file_raises_not_defaults():
    with pytest.raises(FanoutLimitsError):
        load_fanout_limits(str(REPO_ROOT / "config" / "does-not-exist.yaml"))


def test_unknown_api_version_is_refused():
    with pytest.raises(FanoutLimitsError):
        parse_fanout_limits(
            {
                "apiVersion": "harness-limits/v999",
                "fanout": {
                    "maxConcurrentSubagents": 4,
                    "maxSubagentDepth": 2,
                    "perSubagentToolBudget": 20,
                    "subagentWallClockSeconds": 60,
                },
            }
        )


@pytest.mark.parametrize("missing", [
    "maxConcurrentSubagents",
    "maxSubagentDepth",
    "perSubagentToolBudget",
    "subagentWallClockSeconds",
])
def test_a_missing_bound_is_not_silently_defaulted(missing):
    fanout = {
        "maxConcurrentSubagents": 4,
        "maxSubagentDepth": 2,
        "perSubagentToolBudget": 20,
        "subagentWallClockSeconds": 60,
    }
    del fanout[missing]
    with pytest.raises(FanoutLimitsError):
        parse_fanout_limits({"apiVersion": "harness-limits/v1", "fanout": fanout})


@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_bounds_are_refused(bad):
    with pytest.raises(FanoutLimitsError):
        parse_fanout_limits(
            {
                "apiVersion": "harness-limits/v1",
                "fanout": {
                    "maxConcurrentSubagents": bad,
                    "maxSubagentDepth": 2,
                    "perSubagentToolBudget": 20,
                    "subagentWallClockSeconds": 60,
                },
            }
        )


def test_frozen_limits_cannot_be_mutated_at_runtime():
    limits = FanoutLimits(4, 2, 20, 60)
    with pytest.raises(Exception):
        limits.max_concurrent_subagents = 999  # type: ignore[misc]
