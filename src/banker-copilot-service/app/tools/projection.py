"""Evidence projection — the place where the system states what a piece of evidence *means*.

`authority-policy.yaml` says an approval for `account.balance.adjust` needs
`list_account_transactions` evidence carrying `[accountId, count]`. That is a genuinely good
assertion: **this evidence is about THIS account, and it is non-empty.** The tool returns a bare
JSON array, which asserts neither. This module is the declared adapter between the two.

It is deliberately the least powerful thing that closes that gap.

**Four verbs, and nothing else** (Danny, Gate B ruling §R2):

===========  ==========================================================================
``rename``   emit an existing response field under a more specific name (``id`` → ``accountId``)
``bind``     emit a value from the tool's own bound invocation argument (``$args.accountId``)
``count``    emit the arity of the response array
``collect``  emit the array under a named key
===========  ==========================================================================

Refused at load, by name, with a reason, fatally: literals, defaults, filters, predicates,
arithmetic, conditionals, cross-tool references, and **any reference to the proposal payload**.

The last is the security boundary, and it is the reason this grammar is closed rather than
convenient. ``$args`` is admissible because a bound argument is a statement about the HTTP call
that actually happened — the trace holds the same value on the `tool.completed` frame, so the
claim is checkable. **The moment a projection can read `payload.userId`, the proposer can stamp
its own conclusion onto its own evidence and the approval record becomes self-attesting.**

``bind`` may only name a *required* parameter of its own tool. That is not a convenience check
against missing keys — it is §R5 made unspellable. A projection is legitimate only where the
subject identity is already determined by the call that was made; where the call was not scoped
to the subject, no reshaping can make it so. `list_login_audits` filters by recency, not by user,
so ``userId`` is not among its parameters, so ``bind: $args.userId`` cannot be written here. The
alternative — reaching for the payload to fill the gap — would put *"here are user X's recent
logins, N of them"* into an audit record when the truth is *"here are the last N logins of
anybody at all."* That is how a formatting fix becomes a false record.

**Projection is lossless.** It may add and rename; it may not drop. ``collect`` keeps the full
array, ``rename`` leaves the original field in place, and a key that would overwrite existing
material is refused rather than silently applied. A projection that could discard fields would
turn the approval record from a record into a curated exhibit chosen by the party seeking
approval.

TODO(#332, required before `main`, Gate B ruling §R4): the ``accountId`` this module emits is
*asserted by the proposer*. `EvidenceComplete` should additionally require that evidence identity
fields match the corresponding payload identity, converting the claim into a checked claim. Not
done here: it changes a ratified evaluator's semantics and must arrive with its own test.

TODO(#332, required before `main`, Gate B ruling §R3): a per-key provenance envelope on the
approval itself (``toolId``, method + path called, bound args, upstream status, ``toolCallId``),
so the record stands alone without the trace. Today joinability rests on ``sessionId`` /
``correlationId``, which are persisted (held by
`authority-service.UnitTests/EvidenceContractSeamTests.An_approval_is_joinable_to_the_run_that_produced_it`)
but require the trace to resolve. The envelope changes the approval schema and deserves its own test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: The whole grammar. Anything else is refused at load.
VERBS: frozenset[str] = frozenset({"rename", "bind", "count", "collect"})

#: Verbs refused *by name*, because a construct rejected with "unknown key" reads like a typo
#: while these are deliberate attempts to make the projection compute something.
_REFUSED_VERBS: dict[str, str] = {
    "literal": (
        "'literal' would let the manifest write a value into evidence that no upstream call "
        "produced. Evidence states what a service returned, not what the manifest wished it had."
    ),
    "const": "'const' is a literal under another name; see 'literal'.",
    "value": "'value' is a literal under another name; see 'literal'.",
    "default": (
        "'default' invents a value exactly when the real one is missing, which is exactly when "
        "the evidence gap is real. A missing field must surface as an incomplete evidence "
        "refusal, not be papered over at the last moment before the record is written."
    ),
    "filter": (
        "'filter' would let the projection choose which records reach the approval record. "
        "Projection is lossless by construction: the party seeking approval does not curate the "
        "evidence for the party granting it."
    ),
    "where": "'where' is a filter under another name; see 'filter'.",
    "select": "'select' is a filter under another name; see 'filter'.",
    "first": (
        "'first' drops every record but one. Projection may add and rename; it may not drop."
    ),
    "if": (
        "'if' makes the emitted shape depend on the data, so two approval records with the same "
        "keys could mean different things. Evidence shape must be readable without re-running "
        "the condition that produced it."
    ),
    "when": "'when' is a conditional under another name; see 'if'.",
    "predicate": (
        "'predicate' evaluates a claim inside the evidence. Evidence carries material and "
        "identity; the judgement belongs to authority-service's policy evaluator, which is "
        "where it can be audited."
    ),
    "sum": (
        "'sum' computes a figure that no upstream service stated. A derived number in an "
        "approval record cannot be checked against the call that produced it."
    ),
    "expr": "'expr' is an open computation grammar; this one is closed on purpose.",
    "template": "'template' is an open computation grammar; this one is closed on purpose.",
    "tool": (
        "'tool' would reference another tool's response. Each evidence key must stand on its "
        "own call, or the trace stops being the citation index for the record."
    ),
    "evidence": "'evidence' is a cross-tool reference; see 'tool'.",
    "payload": (
        "'payload' reads the proposal being justified. This is the one absolute refusal in this "
        "grammar: a projection that can read the payload lets the proposer stamp its own "
        "conclusion onto its own evidence, and the approval record becomes self-attesting."
    ),
    "facts": (
        "'facts' is proposer-supplied context, not upstream response material; see 'payload'."
    ),
}

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ARGS_REF = re.compile(r"^\$args\.([A-Za-z_][A-Za-z0-9_]*)$")


class ProjectionError(ValueError):
    """A projection that cannot be trusted. Fatal at startup; never downgraded to a no-op."""


@dataclass(frozen=True)
class ProjectionRule:
    """One emitted key. Exactly one verb, one operand, no nesting."""

    key: str
    verb: str
    operand: str


def parse_projection(
    raw: Any, tool_id: str, required_parameters: frozenset[str]
) -> tuple[ProjectionRule, ...]:
    """Validate a declared ``evidenceProjection`` block. Raises :class:`ProjectionError`.

    ``required_parameters`` is the tool's own ``parameters.required`` set — ``bind`` is confined
    to it, so a projection can only assert a subject the call was actually scoped by.
    """
    if not isinstance(raw, dict) or not raw:
        raise ProjectionError(
            f"tool {tool_id!r} 'evidenceProjection' must be a non-empty mapping of "
            "outputKey -> { verb: operand }"
        )

    rules: list[ProjectionRule] = []

    for key, spec in raw.items():
        if not isinstance(key, str) or not _IDENTIFIER.match(key):
            raise ProjectionError(
                f"tool {tool_id!r} evidenceProjection key {key!r} must be a plain identifier; "
                "the emitted key is read by a policy document and by a human a year from now."
            )

        if not isinstance(spec, dict) or len(spec) != 1:
            raise ProjectionError(
                f"tool {tool_id!r} evidenceProjection key {key!r} must declare exactly one verb "
                f"from {sorted(VERBS)}, got {spec!r}. Two verbs on one key is a computation."
            )

        verb, operand = next(iter(spec.items()))

        if verb in _REFUSED_VERBS:
            raise ProjectionError(
                f"tool {tool_id!r} evidenceProjection key {key!r} uses refused verb {verb!r}: "
                f"{_REFUSED_VERBS[verb]}"
            )

        if verb not in VERBS:
            raise ProjectionError(
                f"tool {tool_id!r} evidenceProjection key {key!r} uses unknown verb {verb!r}. "
                f"The projection grammar is closed: {sorted(VERBS)} and nothing else. A verb "
                "this loader does not fully understand is refused, never skipped."
            )

        if not isinstance(operand, str) or not operand.strip():
            raise ProjectionError(
                f"tool {tool_id!r} evidenceProjection key {key!r} verb {verb!r} needs a string "
                f"operand, got {operand!r}"
            )

        operand = operand.strip()

        if verb == "rename":
            if not _IDENTIFIER.match(operand):
                raise ProjectionError(
                    f"tool {tool_id!r} evidenceProjection key {key!r} 'rename' operand "
                    f"{operand!r} must be a single top-level response field name. Paths are not "
                    "supported: a rename adds specificity to a value the response already "
                    "states, it does not go looking for one."
                )

        elif verb == "bind":
            if operand.startswith("$payload") or operand.startswith("$facts"):
                raise ProjectionError(
                    f"tool {tool_id!r} evidenceProjection key {key!r} binds {operand!r}. A "
                    "projection may reference the tool's own arguments, never the proposal. "
                    "Reading the payload here would let the proposer stamp its own conclusion "
                    "onto its own evidence, and the approval record would become self-attesting."
                )
            match = _ARGS_REF.match(operand)
            if match is None:
                raise ProjectionError(
                    f"tool {tool_id!r} evidenceProjection key {key!r} 'bind' operand "
                    f"{operand!r} must be of the form '$args.<parameterName>'."
                )
            argument = match.group(1)
            if argument not in required_parameters:
                raise ProjectionError(
                    f"tool {tool_id!r} evidenceProjection key {key!r} binds "
                    f"'$args.{argument}', which is not a REQUIRED parameter of this tool "
                    f"(required: {sorted(required_parameters)}). A projection may only assert a "
                    "subject the call was actually scoped by. Where the upstream call was not "
                    "scoped to the subject, no reshaping can make it so — and an optional "
                    "argument is absent exactly when the assertion would be false."
                )
            operand = argument

        elif verb in ("count", "collect"):
            if operand != "$":
                raise ProjectionError(
                    f"tool {tool_id!r} evidenceProjection key {key!r} verb {verb!r} takes the "
                    f"whole response '$' and nothing else, got {operand!r}. Counting or "
                    "collecting a sub-selection would be a filter."
                )

        rules.append(ProjectionRule(key=key, verb=verb, operand=operand))

    keys = [rule.key for rule in rules]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ProjectionError(
            f"tool {tool_id!r} evidenceProjection emits duplicate key(s) {duplicates}"
        )

    if any(rule.verb == "count" for rule in rules) and not any(
        rule.verb == "collect" for rule in rules
    ):
        raise ProjectionError(
            f"tool {tool_id!r} evidenceProjection declares 'count' without 'collect'. Counting "
            "an array while not carrying it would leave the approval record asserting an arity "
            "with no material behind it — an unfalsifiable claim. Projection is lossless."
        )

    return tuple(rules)


def project(
    document: Any, rules: tuple[ProjectionRule, ...], arguments: dict[str, Any]
) -> Any:
    """Apply a validated projection to one tool response. Raises :class:`ProjectionError`.

    Lossless: an object response is carried through whole and added to; an array response is
    carried whole under the declared ``collect`` key.
    """
    if not rules:
        return document

    collects = [rule for rule in rules if rule.verb == "collect"]

    if isinstance(document, list):
        if not collects:
            raise ProjectionError(
                "projection of an array response must declare a 'collect' key; without one the "
                "array itself would not reach the approval record"
            )
        projected: dict[str, Any] = {}
    elif isinstance(document, dict):
        if collects:
            raise ProjectionError(
                "'collect' was declared but the response is an object, not an array"
            )
        # Lossless: start from everything the service said, then add.
        projected = dict(document)
    else:
        raise ProjectionError(
            f"cannot project a {type(document).__name__} response; projection describes objects "
            "and arrays only"
        )

    for rule in rules:
        if rule.verb == "rename":
            if not isinstance(document, dict) or rule.operand not in document:
                raise ProjectionError(
                    f"projection cannot rename {rule.operand!r} to {rule.key!r}: the response "
                    "has no such field. The manifest describes a shape this service did not "
                    "return."
                )
            value: Any = document[rule.operand]
        elif rule.verb == "bind":
            if rule.operand not in arguments:
                raise ProjectionError(
                    f"projection cannot bind '$args.{rule.operand}' for {rule.key!r}: the "
                    "argument was not supplied to this call"
                )
            value = arguments[rule.operand]
        elif rule.verb == "count":
            if not isinstance(document, list):
                raise ProjectionError(
                    f"projection cannot count {rule.key!r}: the response is not an array"
                )
            value = len(document)
        else:  # collect
            value = document

        if rule.key in projected:
            raise ProjectionError(
                f"projection key {rule.key!r} would overwrite material the response already "
                "carries. Projection adds and renames; it never replaces."
            )

        projected[rule.key] = value

    return projected
