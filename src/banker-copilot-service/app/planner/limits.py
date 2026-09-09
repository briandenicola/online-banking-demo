"""Fan-out limits — the config surface for the subagent fan-out engine (epic §6.3).

This module is the platform lane's contract with the fan-out engine: it reads
`config/harness-limits.yaml` and hands back a validated, frozen :class:`FanoutLimits`. The
engine (`asyncio.gather` orchestration, §6.1/§6.5) imports this and holds NO literals of its
own — invariant I-3 requires every concurrency bound to be configuration.

Fail-closed, exactly like the tool manifest: a missing file, malformed YAML, an unexpected
schema version, or a non-positive bound all abort at load rather than silently defaulting. A
harness that cannot state its own concurrency ceiling must not spawn a single subagent.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

SUPPORTED_API_VERSION = "harness-limits/v1"


class FanoutLimitsError(RuntimeError):
    """Raised when the fan-out limits file is missing, malformed or out of bounds. Never swallowed."""


class AssessmentLimitsError(RuntimeError):
    """Raised when the assessment bounds are missing, malformed or out of bounds (§P5.2).

    Separate from :class:`FanoutLimitsError` so a service that fails to start says WHICH ceiling
    it could not state. Both are fatal; neither has a default, because a default in code would be
    a second home for a number whose only home is the file (invariant I-3).
    """


@dataclass(frozen=True)
class FanoutLimits:
    """The validated §6.3 bounds. Frozen so the engine cannot mutate a limit at runtime."""

    max_concurrent_subagents: int
    max_subagent_depth: int
    per_subagent_tool_budget: int
    subagent_wall_clock_seconds: int


def _require_positive_int(document: dict, key: str, path: str) -> int:
    if key not in document:
        raise FanoutLimitsError(
            f"harness limits at {path!r} is missing required key 'fanout.{key}'. There is no "
            "default — a fan-out bound absent from the file would be a hardcoded fallback, which "
            "invariant I-3 forbids."
        )
    value = document[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise FanoutLimitsError(
            f"harness limits 'fanout.{key}' must be an integer, got {value!r}."
        )
    if value < 1:
        raise FanoutLimitsError(
            f"harness limits 'fanout.{key}' must be >= 1, got {value}. A zero or negative bound "
            "either disables fan-out silently or is nonsensical; refusing to start."
        )
    return value


@dataclass(frozen=True)
class AssessmentLimits:
    """The validated §P5.2 bounds for the primary's assessment loop. Frozen at load.

    ``per_run_additional_tool_budget`` is a BUDGET, never a feature flag. Zero is a legitimate,
    fully-traversed configuration — the loop runs, the model is asked, its requests are parsed
    and recorded, and every one of them is refused as ``budget_exhausted``. Nothing branches on
    it being zero, so stage 1 exercises the code stage 2 ships (§P5.1).
    """

    per_run_additional_tool_budget: int
    max_assessment_iterations: int


def _require_non_negative_int(document: dict, key: str, path: str) -> int:
    """Like :func:`_require_positive_int`, but 0 is IN RANGE rather than nonsensical.

    A separate reader rather than a relaxed shared one: for a fan-out bound, zero disables
    fan-out silently and must abort; for the evidence budget, zero is stage 1 and is the value
    we are shipping. Merging the two would let a future edit relax the fan-out floor by touching
    a line that appears to be about the assessment.
    """
    if key not in document:
        raise AssessmentLimitsError(
            f"harness limits at {path!r} is missing required key 'assessment.{key}'. There is no "
            "default — the assessment loop's bounds have exactly one home, and a fallback here "
            "would be a threshold stated twice."
        )
    value = document[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssessmentLimitsError(
            f"harness limits 'assessment.{key}' must be an integer, got {value!r}."
        )
    if value < 0:
        raise AssessmentLimitsError(
            f"harness limits 'assessment.{key}' must be >= 0, got {value}."
        )
    return value


def parse_assessment_limits(document: object, path: str = "<memory>") -> AssessmentLimits:
    if not isinstance(document, dict):
        raise AssessmentLimitsError(f"harness limits at {path!r} must be a YAML mapping.")

    api_version = document.get("apiVersion")
    if api_version != SUPPORTED_API_VERSION:
        raise AssessmentLimitsError(
            f"harness limits at {path!r} has apiVersion {api_version!r}; this build understands "
            f"only {SUPPORTED_API_VERSION!r}. Refusing to guess at an unknown schema."
        )

    assessment = document.get("assessment")
    if not isinstance(assessment, dict):
        raise AssessmentLimitsError(
            f"harness limits at {path!r} must carry an 'assessment' mapping (§P5.2)."
        )

    iterations = _require_non_negative_int(assessment, "maxAssessmentIterations", path)
    if iterations < 1:
        raise AssessmentLimitsError(
            "harness limits 'assessment.maxAssessmentIterations' must be >= 1, got 0. Zero would "
            "mean the primary is never asked at all, which is the no-assessment state this "
            "feature exists to end — and it would be indistinguishable on the card from a model "
            "that failed. The budget may be zero; the number of judgements may not."
        )

    return AssessmentLimits(
        per_run_additional_tool_budget=_require_non_negative_int(
            assessment, "perRunAdditionalToolBudget", path
        ),
        max_assessment_iterations=iterations,
    )


def load_assessment_limits(path: str) -> AssessmentLimits:
    """Read and validate the assessment bounds. A missing or invalid file aborts startup."""
    return parse_assessment_limits(_read(path, AssessmentLimitsError), path)


def _read(path: str, error: type[RuntimeError]) -> object:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise error(
            f"harness limits not found at {path!r}. A harness that starts without its declared "
            "bounds would run with an undefined ceiling; refusing to start."
        ) from exc
    except yaml.YAMLError as exc:
        raise error(f"harness limits at {path!r} is not valid YAML: {exc}") from exc


def parse_fanout_limits(document: object, path: str = "<memory>") -> FanoutLimits:
    if not isinstance(document, dict):
        raise FanoutLimitsError(f"harness limits at {path!r} must be a YAML mapping.")

    api_version = document.get("apiVersion")
    if api_version != SUPPORTED_API_VERSION:
        raise FanoutLimitsError(
            f"harness limits at {path!r} has apiVersion {api_version!r}; this build understands "
            f"only {SUPPORTED_API_VERSION!r}. Refusing to guess at an unknown schema."
        )

    fanout = document.get("fanout")
    if not isinstance(fanout, dict):
        raise FanoutLimitsError(
            f"harness limits at {path!r} must carry a 'fanout' mapping (epic §6.3)."
        )

    return FanoutLimits(
        max_concurrent_subagents=_require_positive_int(fanout, "maxConcurrentSubagents", path),
        max_subagent_depth=_require_positive_int(fanout, "maxSubagentDepth", path),
        per_subagent_tool_budget=_require_positive_int(fanout, "perSubagentToolBudget", path),
        subagent_wall_clock_seconds=_require_positive_int(fanout, "subagentWallClockSeconds", path),
    )


def load_fanout_limits(path: str) -> FanoutLimits:
    """Read and validate the fan-out limits file. A missing or invalid file aborts startup."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise FanoutLimitsError(
            f"harness limits not found at {path!r}. A harness that starts without its fan-out "
            "bounds would spawn with an undefined concurrency ceiling; refusing to start."
        ) from exc
    except yaml.YAMLError as exc:
        raise FanoutLimitsError(f"harness limits at {path!r} is not valid YAML: {exc}") from exc

    return parse_fanout_limits(document, path)
