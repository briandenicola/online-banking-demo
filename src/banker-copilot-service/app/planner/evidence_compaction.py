"""Deterministic, loss-aware compaction for model-facing evidence payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CompactionRecord:
    """Server-derived accounting for one evidence payload handed to a model."""

    compacted_ids: tuple[str, ...]
    original_tokens_estimate: int
    compacted_tokens_estimate: int


def _token_estimate(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))) // 4


def _window(values: list[Any], shown: int) -> list[Any]:
    if shown >= len(values):
        return list(values)
    if shown <= 0:
        return []
    head = (shown + 1) // 2
    tail = shown - head
    return values[:head] + (values[-tail:] if tail else [])


def compact_evidence(
    evidence: Mapping[str, Any], budget_tokens: int
) -> tuple[dict[str, Any], CompactionRecord]:
    """Compact only list-shaped evidence while retaining every evidence id."""
    original = dict(evidence)
    original_estimate = _token_estimate(original)
    limit = budget_tokens
    if original_estimate <= limit:
        return original, CompactionRecord((), original_estimate, original_estimate)

    candidates = {
        key: value for key, value in original.items() if isinstance(value, list) and value
    }
    if not candidates:
        return original, CompactionRecord((), original_estimate, original_estimate)

    shown = {key: len(value) for key, value in candidates.items()}

    def build() -> dict[str, Any]:
        compacted = dict(original)
        for key, values in candidates.items():
            count = shown[key]
            if count < len(values):
                compacted[key] = {
                    "items": _window(values, count),
                    "truncated": {"originalCount": len(values), "shown": count},
                }
        return compacted

    compacted = build()
    while _token_estimate(compacted) > limit and any(shown.values()):
        key = max(shown, key=lambda candidate: (shown[candidate], candidate))
        shown[key] -= 1
        compacted = build()

    compacted_ids = tuple(
        key for key in original if key in candidates and shown[key] < len(candidates[key])
    )
    return compacted, CompactionRecord(
        compacted_ids, original_estimate, _token_estimate(compacted)
    )


__all__ = ["CompactionRecord", "compact_evidence"]
