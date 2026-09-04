"""Redaction applied at emit, never at render.

Persisted traces outlive the session and are replayed offline by #333. PII scrubbed only in the
UI would still be sitting in `copilot-traces` forever. So redaction happens once, on the way
into both the model context and the trace frame, using the manifest's JSONPath list (§3.2).

A deliberately small JSONPath subset is supported — enough for the expressions the manifest
actually uses — and anything outside it is rejected by the manifest loader's caller rather than
silently matching nothing. A redaction rule that matches nothing is indistinguishable from a
redaction rule that worked, which is the worst possible failure mode for this particular code.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[redacted]"

_SEGMENT = re.compile(r"^(?:\[\*\]|\[(\d+)\]|([A-Za-z_][A-Za-z0-9_]*))$")


class RedactionPathError(ValueError):
    """An unsupported JSONPath expression. Fatal — never downgraded to a no-op."""


def _tokenize(path: str) -> list[str]:
    if not path.startswith("$"):
        raise RedactionPathError(f"redaction path {path!r} must start with '$'")

    if ".." in path:
        raise RedactionPathError(
            f"redaction path {path!r} uses recursive descent, which is not supported. Left "
            "unhandled it silently degrades to a top-level field match — a rule that appears "
            "to scrub everything while scrubbing almost nothing."
        )

    remainder = path[1:]
    tokens: list[str] = []
    for chunk in remainder.replace("[", ".[").split("."):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not _SEGMENT.match(chunk):
            raise RedactionPathError(
                f"redaction path {path!r} uses unsupported segment {chunk!r}. Supported forms "
                "are $.field, $.a.b, $[*], $[*].field and $.a[*].b."
            )
        tokens.append(chunk)

    if not tokens:
        raise RedactionPathError(f"redaction path {path!r} selects the whole document")
    return tokens


def _apply(node: Any, tokens: list[str]) -> Any:
    if not tokens:
        return REDACTED

    head, tail = tokens[0], tokens[1:]

    if head == "[*]":
        if not isinstance(node, list):
            return node
        return [_apply(item, tail) for item in node]

    if head.startswith("["):
        index = int(head[1:-1])
        if not isinstance(node, list) or index >= len(node):
            return node
        copied = list(node)
        copied[index] = _apply(copied[index], tail)
        return copied

    if not isinstance(node, dict) or head not in node:
        return node

    copied = dict(node)
    copied[head] = _apply(copied[head], tail)
    return copied


def validate_paths(paths: tuple[str, ...] | list[str]) -> None:
    """Tokenize every path so a malformed expression fails at startup, not at emit."""
    for path in paths:
        _tokenize(path)


def redact(document: Any, paths: tuple[str, ...] | list[str]) -> Any:
    """Return a copy of ``document`` with every matching node replaced by ``[redacted]``."""
    result = document
    for path in paths:
        result = _apply(result, _tokenize(path))
    return result
