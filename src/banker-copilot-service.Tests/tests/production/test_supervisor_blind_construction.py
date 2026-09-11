"""Blind construction, proven against the SHIPPING harness — not the oracle.

The oracle suite (`spec/supervisor.py` + `tests/test_blind_construction.py`) proves
the SPEC is coherent and leak-free. It does NOT prove Turk's production
`app.planner.fanout`. This file closes that gap now that the production module
exists: it imports the real builder and re-runs the structural independence attack
against it, deriving every expectation from §6.4 rather than from Turk's code.

Independence is asserted STRUCTURALLY: the builder's SIGNATURE is the control (only
`intent` may enter), and the supervisor input TYPE carries no field a primary output
could ride on. The byte-scan is a cross-check with a positive control, so it cannot
pass on an empty corpus (learning #1).
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from . import service_import  # noqa: F401 — importing IS the fail-not-skip guard

from app.planner import fanout  # type: ignore  # noqa: E402


# The names §6.4(1) forbids from reaching supervisor construction. Derived from the
# spec's own list of channels, not from the production field set.
FORBIDDEN_PRIMARY_CHANNELS = frozenset(
    {"primary", "plan", "narrative", "recommendation", "conclusion",
     "reasoning", "confidence", "cached_tool_results", "cache", "context",
     "primary_result", "primaryresult"}
)


def test_the_builder_signature_admits_only_the_banker_intent():
    """§6.4(1): the primary's output has no argument to travel through. The signature
    IS the barrier — a builder that also took the primary could 'ignore' it only by
    a promise, and a promise is what §6.4 forbids."""
    sig = inspect.signature(fanout.build_supervisor_input)
    params = list(sig.parameters.values())

    assert len(params) == 1, (
        f"build_supervisor_input must take exactly one parameter; it takes "
        f"{[p.name for p in params]}. A second parameter is a channel for the "
        f"primary's output, however it is named."
    )
    only = params[0]
    assert only.name == "intent"
    # No var-positional / var-keyword backdoor (`*args`/`**kwargs`) that would let a
    # primary result slip in past a one-name signature.
    assert only.kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), f"parameter kind {only.kind} could admit extra arguments"
    for p in params:
        assert p.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), "a *args/**kwargs builder can be handed the primary result anyway"


def test_the_builder_rejects_a_primary_result_positionally():
    """Belt-and-braces on the signature: calling the real builder with a second
    positional argument (a PrimaryResult) must raise, not silently absorb it."""
    intent = fanout.BankerIntent(task_framing="reverse the wire", entity_ids=("trf_1",))
    primary = fanout.PrimaryResult(recommendation="APPROVE", narrative="looks fine")
    with pytest.raises(TypeError):
        fanout.build_supervisor_input(intent, primary)  # type: ignore[call-arg]


def test_the_supervisor_input_type_has_no_primary_bearing_field():
    """§6.4(1): 'the field set IS the set of things the supervisor may know.' So no
    field may name — or be typed as — a primary output channel. Structural: introspect
    the dataclass, don't trust the docstring."""
    assert dataclasses.is_dataclass(fanout.SupervisorInput)
    field_names = {f.name.lower() for f in dataclasses.fields(fanout.SupervisorInput)}

    leaks = field_names & FORBIDDEN_PRIMARY_CHANNELS
    assert not leaks, (
        f"SupervisorInput exposes {sorted(leaks)} — a field a primary output could "
        f"ride on. The supervisor's knowable set must be intent + posture only."
    )
    # And no field typed as PrimaryResult under an innocent name.
    for f in dataclasses.fields(fanout.SupervisorInput):
        assert f.type not in (fanout.PrimaryResult, "PrimaryResult"), (
            f"field {f.name!r} is typed PrimaryResult — a renamed leak"
        )


def test_no_distinctive_primary_token_survives_into_the_spawn_bytes():
    """§6.4 cross-check: build the supervisor input from an intent, and prove that
    a primary result full of distinctive sentinels shares NONE of its tokens with the
    bytes the supervisor is actually spawned with."""
    intent = fanout.BankerIntent(
        task_framing="Assess whether reversing this wire is defensible.",
        entity_ids=("trf_88a2", "cust_4417"),
    )
    primary = fanout.PrimaryResult(
        plan=("zqxjv_step_one", "zqxjv_step_two"),
        narrative="conclusion zqxjvwomble the customer is clearly fraudulent",
        recommendation="zqxjv_DENY",
        confidence=0.99,
        cached_tool_results={"zqxjv_ledger": {"balance": "zqxjv_secret"}},
    )

    spawn_bytes = fanout.build_supervisor_input(intent).serialize()
    spawn_tokens = {t for t in _tokenize(spawn_bytes) if len(t) >= 4}

    leaked = primary.all_tokens() & spawn_tokens
    assert not leaked, (
        f"primary tokens {sorted(leaked)} appear in the supervisor spawn bytes — "
        f"the primary's output reached the supervisor after all"
    )


def test_the_token_scan_is_not_vacuous():
    """Positive control (learning #1): if a distinctive token IS placed where the
    supervisor can see it — the banker's own framing — the scan MUST find it. A scan
    that reports 'clean' on everything is the dead assertion this guards against."""
    sentinel = "zqxjvwomble"
    intent = fanout.BankerIntent(
        task_framing=f"Assess the {sentinel} transfer.",
        entity_ids=("trf_1",),
    )
    spawn_tokens = {t for t in _tokenize(fanout.build_supervisor_input(intent).serialize())}
    assert sentinel in spawn_tokens, (
        "the token scan cannot see a token placed in plain sight; it would report any "
        "leak as clean and prove nothing"
    )


def _tokenize(text: str) -> set[str]:
    out: set[str] = set()
    word: list[str] = []
    for ch in text:
        if ch.isalnum() or ch in "_-":
            word.append(ch)
        else:
            if word:
                out.add("".join(word))
                word = []
    if word:
        out.add("".join(word))
    return out
