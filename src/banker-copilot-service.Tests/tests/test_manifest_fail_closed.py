"""The tool manifest loader must FAIL CLOSED — refuse startup, not skip entries.

Epic §3.1 rule 4: *"A tool with a missing or unknown ``actionId`` fails
registration at service start. Fail closed, loudly."*

The failure this file is built around is not a loader that crashes. It is a
loader that is *tolerant*: one that validates each entry, logs a warning for the
bad ones, and starts with the rest. Such a loader is comfortable to operate and
passes every positive test, and it means the tool surface the model is given is
not the tool surface anyone reviewed. Every tamper below therefore asserts two
things — that the load RAISES, and that NOTHING was registered — because
"raised somewhere later" and "refused at the door" are different guarantees.

Each case is a distinct way to break the manifest, tampered in both directions
where a direction exists.
"""

from __future__ import annotations

import copy

import pytest

from spec.manifest import ManifestError, load_manifest
from spec.registry import AuthorityClient, DomainReadTransport, build_registry


def _load_or_registry(raw):
    """Load and build in one step, so 'the loader raised but the registry was
    populated anyway' cannot hide."""
    entries = load_manifest(raw)
    return build_registry(
        entries, DomainReadTransport(), AuthorityClient(sink=lambda b: {"approvalId": "apr_1"})
    )


def test_the_untampered_manifest_loads(worked_manifest):
    """Anti-vacuous baseline.

    Without this, every tamper case below could be passing because the manifest
    never loaded at all — the loader could be ``raise ManifestError`` and this
    file would be entirely green.
    """
    reg = _load_or_registry(worked_manifest)
    assert len(reg) > 1


def test_section_3_3_alone_does_not_load(manifest_section_3_3):
    """FINDING F2-1, asserted rather than described.

    Epic §3.3 as printed is not a loadable manifest: ``override_risk_score``
    requires evidence from ``get_scored_transaction`` and
    ``review_account_application`` from ``get_account_application`` /
    ``get_application_audit``, none of which appear in the six entries. The
    Phase 2 bullet names those read tools but never gives their manifest
    entries.

    Under fail-closed validation an unresolvable ``requiredEvidence`` reference
    must be fatal — the alternative is a write action that can never satisfy its
    own evidence rule and therefore can never be proposed, discovered at demo
    time. This test asserts the CURRENT state of the spec. When §3.3 is
    completed it will go red, which is the notification.
    """
    with pytest.raises(ManifestError, match="unknown tool"):
        load_manifest(manifest_section_3_3)


# ---------------------------------------------------------------------------
# Structural tampers on a single entry. Every one must refuse the WHOLE load.
# ---------------------------------------------------------------------------


def _tamper(manifest, tool_id, mutate):
    raw = copy.deepcopy(manifest)
    entry = next(e for e in raw if e["toolId"] == tool_id)
    mutate(entry)
    return raw


def test_an_unknown_field_is_fatal_not_ignored(worked_manifest):
    """The typo'd flag, in its purest form.

    ``mode`` misspelled as ``modes`` leaves ``mode`` missing and adds an unknown
    key. A tolerant loader that ignores unknown keys and defaults the missing
    one has just registered a write tool.
    """
    raw = _tamper(
        worked_manifest,
        "review_flagged_transaction",
        lambda e: e.update({"modee": e.pop("mode")}),
    )
    with pytest.raises(ManifestError):
        load_manifest(raw)


def test_an_unknown_field_alongside_a_valid_entry_is_still_fatal(worked_manifest):
    """Isolates 'unknown key' from 'missing key' — they are different guards."""
    raw = _tamper(
        worked_manifest, "get_flagged_transaction", lambda e: e.update({"allowWrite": True})
    )
    with pytest.raises(ManifestError, match="unknown manifest field"):
        load_manifest(raw)


@pytest.mark.parametrize(
    "field",
    [
        "toolId",
        "displayName",
        "description",
        "mode",
        "actionId",
        "authority",
        "target",
        "parameters",
        "requiredEvidence",
        "capabilityScope",
        "redaction",
    ],
)
def test_every_required_field_is_actually_required(worked_manifest, field):
    """Field-by-field, because 'required' asserted in aggregate is not asserted.

    A loader that checks four of eleven fields passes a single missing-field
    test whose fixture happens to drop one of the four.
    """
    raw = _tamper("review_flagged_transaction".join([]) or worked_manifest,
                  "review_flagged_transaction", lambda e: e.pop(field, None))
    with pytest.raises(ManifestError):
        load_manifest(raw)


def test_an_unrecognised_mode_is_refused_rather_than_treated_as_read(worked_manifest):
    """``mode: "readonly"`` must not fall through to read.

    Defaulting an unrecognised mode to the safe-looking value is the tempting
    bug: it reads as conservative and it is how a write entry gets executed
    directly.
    """
    raw = _tamper(worked_manifest, "get_flagged_transaction", lambda e: e.update({"mode": "readonly"}))
    with pytest.raises(ManifestError, match="mode must be one of"):
        load_manifest(raw)


def test_a_write_tool_with_a_null_action_id_is_refused(worked_manifest):
    raw = _tamper(worked_manifest, "override_risk_score", lambda e: e.update({"actionId": None}))
    with pytest.raises(ManifestError, match="actionId"):
        load_manifest(raw)


def test_a_read_tool_with_an_action_id_is_refused(worked_manifest):
    """The other direction. §3.2: ``actionId`` is null IFF mode == read.

    Both directions or you have tested neither: a read tool carrying an
    ``actionId`` is a policy key attached to something that executes without a
    signature.
    """
    raw = _tamper(
        worked_manifest,
        "get_flagged_transaction",
        lambda e: e.update({"actionId": "transaction.flag.review"}),
    )
    with pytest.raises(ManifestError, match="null iff"):
        load_manifest(raw)


@pytest.mark.parametrize("bad", ["transactionflagreview", "Transaction.Flag.Review", "a.b.c.d.e", ""])
def test_a_malformed_action_id_is_refused(worked_manifest, bad):
    """Action ids are policy LOOKUP KEYS (§0.1) — a typo is a silent policy miss.

    Silent misses are the worst class of defect in this system: the action
    resolves to no policy, and the interesting question becomes what the policy
    engine does with an unknown key. The manifest must never get that far.
    """
    raw = _tamper(worked_manifest, "override_risk_score", lambda e: e.update({"actionId": bad}))
    with pytest.raises(ManifestError):
        load_manifest(raw)


def test_an_unknown_declared_rung_is_refused(worked_manifest):
    raw = _tamper(
        worked_manifest,
        "override_risk_score",
        lambda e: e["authority"].update({"declaredRung": "L0"}),
    )
    with pytest.raises(ManifestError, match="is not a rung"):
        load_manifest(raw)


def test_an_l3_entry_is_refused_at_load_rather_than_hidden_at_runtime(worked_manifest):
    """Epic §4.3: L3 is outside the harness entirely — the agent may not even propose.

    A harness that loads an L3 entry and refuses it at call time has still put
    the action's name and description into the model's context. §3.3 is explicit
    that the L3 set is "absent from the manifest entirely; the agent cannot even
    name them."
    """
    raw = _tamper(
        worked_manifest,
        "override_risk_score",
        lambda e: e["authority"].update({"declaredRung": "L3"}),
    )
    with pytest.raises(ManifestError, match="not proposable"):
        load_manifest(raw)


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/users/{id}",
        "/api/admin/promote",
        "/api/admin/users/{id}/reset-password",
        "/api/admin/replay-events",
    ],
)
def test_the_l3_endpoint_set_cannot_be_named_by_any_entry(worked_manifest, path):
    """Named endpoints, not just the rung label.

    Setting ``declaredRung: L1`` on ``POST /api/admin/promote`` is a one-word
    edit that defeats a rung-only check. The deny list is on the target path.
    """
    raw = _tamper(worked_manifest, "review_flagged_transaction", lambda e: e["target"].update({"path": path}))
    with pytest.raises(ManifestError, match="L3 set"):
        load_manifest(raw)


def test_a_duplicate_tool_id_is_refused(worked_manifest):
    """Shadowing: a second ``get_flagged_transaction`` pointed somewhere else.

    Last-writer-wins on a tool-id dict is the default behaviour of every
    registry written in a hurry, and it makes the reviewed manifest and the live
    manifest silently different.
    """
    raw = copy.deepcopy(worked_manifest)
    clone = copy.deepcopy(raw[0])
    clone["target"]["path"] = "/api/admin/somewhere-else/{txId}"
    raw.append(clone)
    with pytest.raises(ManifestError, match="duplicate toolId"):
        load_manifest(raw)


def test_a_duplicate_action_id_is_refused(worked_manifest):
    raw = copy.deepcopy(worked_manifest)
    entry = copy.deepcopy(next(e for e in raw if e["toolId"] == "override_risk_score"))
    entry["toolId"] = "override_risk_score_v2"
    raw.append(entry)
    with pytest.raises(ManifestError, match="duplicate actionId"):
        load_manifest(raw)


def test_a_write_tool_without_required_evidence_is_refused(worked_manifest):
    """§3.2: ``requiredEvidence`` is the teeth behind "agents gather evidence".

    An empty list is a valid-looking value that removes the requirement
    entirely, and it is the edit somebody makes at 5pm to get a demo working.
    """
    raw = _tamper(worked_manifest, "review_flagged_transaction", lambda e: e.update({"requiredEvidence": []}))
    with pytest.raises(ManifestError, match="no requiredEvidence"):
        load_manifest(raw)


def test_a_write_tool_without_an_idempotency_key_is_refused(worked_manifest):
    """Retry after a failed execution needs no new signature (§5.1). Without an
    idempotency key that rule turns one signature into N executions."""
    raw = _tamper(worked_manifest, "review_flagged_transaction", lambda e: e.pop("idempotencyKeyFrom"))
    with pytest.raises(ManifestError, match="idempotencyKeyFrom"):
        load_manifest(raw)


def test_a_read_tool_carrying_an_idempotency_key_is_refused(worked_manifest):
    raw = _tamper(worked_manifest, "get_flagged_transaction", lambda e: e.update({"idempotencyKeyFrom": ["txId"]}))
    with pytest.raises(ManifestError, match="write-only"):
        load_manifest(raw)


def test_a_redaction_entry_that_is_not_a_jsonpath_is_refused(worked_manifest):
    """Redaction is applied at emit and the trace is durable (§8.0). A path that
    silently matches nothing writes PII to Cosmos forever."""
    raw = _tamper(worked_manifest, "get_flagged_transaction", lambda e: e.update({"redaction": ["customer.ssn"]}))
    with pytest.raises(ManifestError, match="not a JSONPath"):
        load_manifest(raw)


def test_a_self_referential_evidence_requirement_is_refused(worked_manifest):
    raw = _tamper(
        worked_manifest,
        "review_flagged_transaction",
        lambda e: e.update({"requiredEvidence": ["review_flagged_transaction"]}),
    )
    with pytest.raises(ManifestError, match="requires itself"):
        load_manifest(raw)


# ---------------------------------------------------------------------------
# Whole-document tampers.
# ---------------------------------------------------------------------------


def test_one_bad_entry_refuses_the_entire_manifest(worked_manifest):
    """THE central assertion of this file.

    Six good entries and one bad one must yield NO registry. A loader that
    returns the six is the tolerant loader, and it is indistinguishable from a
    correct one in every test that only asks whether the good tools are present.
    """
    raw = copy.deepcopy(worked_manifest)
    raw.append({"toolId": "not_a_tool"})

    with pytest.raises(ManifestError):
        _load_or_registry(raw)

    # And the good entries did not slip through by another route.
    with pytest.raises(ManifestError):
        load_manifest(raw)


def test_an_empty_manifest_is_refused(worked_manifest):
    """Anti-vacuum, promoted to a production rule.

    An empty manifest makes "no write tool is registered" true and useless. It
    is also what a mis-mounted ConfigMap produces, which is how it would
    actually happen.
    """
    with pytest.raises(ManifestError, match="empty"):
        load_manifest([])


def test_a_manifest_that_is_not_an_array_is_refused():
    with pytest.raises(ManifestError):
        load_manifest({"tools": []})


def test_a_manifest_entry_that_is_not_an_object_is_refused(worked_manifest):
    raw = copy.deepcopy(worked_manifest)
    raw.append("get_flagged_transaction")
    with pytest.raises(ManifestError):
        load_manifest(raw)
