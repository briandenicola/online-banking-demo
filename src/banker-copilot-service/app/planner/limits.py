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
