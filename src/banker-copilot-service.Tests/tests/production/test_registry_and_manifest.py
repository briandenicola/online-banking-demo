"""The shipping tool manifest and registry — zero write tools, fail closed.

Runs against ``src/banker-copilot-service`` and ``config/copilot-tools.yaml``.
A failure here is a defect in the service, not in the specification.

**Spec divergence, recorded rather than accommodated.** The shipped schema is
NOT epic §3.2's. It has no ``mode``, no ``actionId``, no ``authority``, no
``requiredEvidence``, no ``idempotencyKeyFrom``; it constrains ``method`` to a
read allowlist and refuses those keys by name. The argument in the docstring is
good — "there is no way to spell a write" is stronger than "no entry says
write" — but the epic's §3.2/§3.3 are ratified, and epic §3.3's own worked
manifest **cannot be loaded by this loader**. That is finding F2-4: it is
Danny's to arbitrate, and it is asserted below rather than smoothed over,
because a test that quietly adopts the implementation as the expectation is the
Phase 1 ``ProductionRoleModelTests`` mistake repeating itself.
"""

from __future__ import annotations

import copy

import pytest
import yaml

from . import service_import  # noqa: F401  (side effect: sys.path + existence assertion)
from .service_import import TOOL_MANIFEST

from app.tools.manifest import (  # noqa: E402
    READ_METHODS,
    ManifestError,
    ReadTool,
    ToolTarget,
    load_manifest,
    parse_manifest,
)
from app.tools.registry import (  # noqa: E402
    PROPOSE_TOOL_ID,
    ToolRegistry,
    WriteToolRegistrationError,
    assert_zero_write_tools,
)


@pytest.fixture(scope="module")
def manifest_document() -> dict:
    assert TOOL_MANIFEST.exists(), f"{TOOL_MANIFEST} is the shipping tool manifest"
    return yaml.safe_load(TOOL_MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture
def document(manifest_document) -> dict:
    return copy.deepcopy(manifest_document)


def _registry(document) -> ToolRegistry:
    manifest = parse_manifest(document)
    return ToolRegistry(
        manifest=manifest,
        service_urls={t.target.service: "http://stub" for t in manifest.tools},
    )


# ---------------------------------------------------------------------------
# Baseline. Anti-vacuous for everything that follows.
# ---------------------------------------------------------------------------


def test_the_shipping_manifest_loads_and_is_not_empty():
    manifest = load_manifest(str(TOOL_MANIFEST))
    assert len(manifest.tools) >= 6, (
        "anti-vacuous: an empty or near-empty manifest makes every zero-write assertion "
        "below trivially true"
    )


def test_every_shipping_tool_is_a_read(document):
    registry = _registry(document)
    assert registry.methods_in_use() <= READ_METHODS
    assert registry.write_tools() == ()
    assert_zero_write_tools(registry)


def test_the_manifest_covers_the_read_tools_phase_2_promised(document, repo_root):
    """Coverage, derived from the epic rather than from the manifest.

    A test that reads the tool ids out of the manifest and asserts they are
    present is a tautology. These names come from the epic's Phase 2 bullet.
    """
    epic = (repo_root / "docs" / "epics" / "banker-copilot.md").read_text(encoding="utf-8")
    idx = epic.find("- Read tools for the six manifest entries in §3.3 plus")
    assert idx > 0, "the Phase 2 read-tool bullet moved; this expectation is unanchored"

    import re

    promised = set(re.findall(r"`([a-z_]+)`", epic[idx : epic.find("\n-", idx + 1)]))
    registered = {t.tool_id for t in parse_manifest(document).tools}

    missing = sorted(promised - registered)
    assert not missing, f"Phase 2 promises read tools that are not registered: {missing}"


# ---------------------------------------------------------------------------
# The zero-write invariant, in its structural form.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_mutating_method_in_the_manifest_refuses_startup(document, method):
    document["tools"][0]["target"]["method"] = method
    with pytest.raises(ManifestError):
        parse_manifest(document)


def test_a_write_capability_scope_is_refused(document):
    """Two independent refusals, and the loader orders them so BOTH are observable.

    ``_parse_tool`` parses the target before checking the scope, with a comment
    saying why: "a rule that can only ever fire behind another rule is a rule
    nobody can observe working." That is precisely the redundancy trap Phase 1
    hit, and it is worth an explicit test that the scope rule fires ON ITS OWN —
    method left as GET.
    """
    document["tools"][0]["target"]["method"] = "GET"
    document["tools"][0]["capabilityScope"] = "risk.write"
    with pytest.raises(ManifestError, match="capabilityScope"):
        parse_manifest(document)


def test_the_reserved_propose_action_id_cannot_be_claimed_by_a_manifest_entry(document):
    """A manifest entry named ``propose_action`` would be executed as an ordinary
    read call, silently bypassing the ladder while looking exactly right in the
    UI's tool list."""
    document["tools"][0]["toolId"] = PROPOSE_TOOL_ID
    registry = _registry(document)
    with pytest.raises(WriteToolRegistrationError, match="reserved tool id"):
        assert_zero_write_tools(registry)


def test_the_startup_assertion_catches_a_write_tool_that_bypassed_the_loader(document):
    """Isolates the registry guard from the loader guard.

    Two guards exercised only together are one guard. This one builds the
    offending ``ReadTool`` by hand — the loader never sees it — so only
    ``assert_zero_write_tools`` can fail it.
    """
    manifest = parse_manifest(document)
    smuggled = ReadTool(
        tool_id="quietly_writes",
        display_name="x",
        description="x",
        target=ToolTarget(service="ai-service", method="PUT", path="/api/admin/x", timeout_ms=1000),
        parameters={"type": "object", "additionalProperties": False},
        capability_scope="risk.read",
    )
    registry = ToolRegistry(
        manifest=type(manifest)(
            api_version=manifest.api_version,
            manifest_id=manifest.manifest_id,
            tools=manifest.tools + (smuggled,),
        ),
        service_urls={"ai-service": "http://stub"},
    )

    assert smuggled.is_read is False
    with pytest.raises(WriteToolRegistrationError, match="quietly_writes"):
        assert_zero_write_tools(registry)


def test_propose_action_is_not_a_member_of_the_registry(document):
    """"Iterate the tools" must never include the write affordance.

    ``propose_action`` is a separate attribute by design. If it were in the
    tuple, every present and future loop over ``registry.tools`` would silently
    include it — including the one that renders the tool list to the banker.
    """
    registry = _registry(document)
    assert PROPOSE_TOOL_ID not in registry.tool_ids
    assert all(t.tool_id != PROPOSE_TOOL_ID for t in registry.tools)
    assert all(d["toolId"] != PROPOSE_TOOL_ID for d in registry.describe())


def test_the_model_facing_description_never_leaks_a_resolved_url(document):
    registry = _registry(document)
    for described in registry.describe():
        assert "http" not in str(described.get("path", ""))
        assert "url" not in {k.lower() for k in described}


# ---------------------------------------------------------------------------
# Fail closed — refuse, never skip.
# ---------------------------------------------------------------------------


def test_an_unknown_tool_key_refuses_the_whole_manifest(document):
    document["tools"][0]["allowWrite"] = True
    with pytest.raises(ManifestError, match="unknown key"):
        parse_manifest(document)


@pytest.mark.parametrize(
    "key,value",
    [
        ("mode", "write"),
        ("mode", "read"),
        ("actionId", "transaction.flag.review"),
        ("authority", {"declaredRung": "L1", "policyRef": "read.any"}),
        ("idempotencyKeyFrom", ["txId"]),
        ("requiredEvidence", ["get_flagged_transaction"]),
        ("cosignerId", "usr_supervisor_1"),
    ],
)
def test_every_refused_key_is_refused_by_name_including_the_innocent_looking_one(
    document, key, value
):
    """``mode: read`` is refused too, and that is the interesting case.

    A loader that only rejects ``mode: write`` teaches the next person that
    ``mode`` is a supported field with one bad value — and the day the check is
    relaxed, ``mode: write`` arrives already looking normal.
    """
    document["tools"][0][key] = value
    with pytest.raises(ManifestError, match=key):
        parse_manifest(document)


def test_one_bad_entry_refuses_the_entire_manifest(document):
    """The tolerant-loader test. Six good entries plus one bad must yield nothing."""
    good = len(document["tools"])
    document["tools"].append({"toolId": "broken"})
    with pytest.raises(ManifestError):
        parse_manifest(document)
    assert good >= 6, "anti-vacuous: there must have been valid entries to skip past"


def test_an_unknown_api_version_is_refused_rather_than_guessed(document):
    document["apiVersion"] = "copilot-tools/v2"
    with pytest.raises(ManifestError, match="apiVersion"):
        parse_manifest(document)


def test_an_empty_tool_list_is_refused(document):
    """Zero tools satisfies "zero write tools" perfectly. It is also what a
    mis-mounted ConfigMap produces."""
    document["tools"] = []
    with pytest.raises(ManifestError, match="non-empty"):
        parse_manifest(document)


def test_a_duplicate_tool_id_is_refused(document):
    clone = copy.deepcopy(document["tools"][0])
    clone["target"]["path"] = clone["target"]["path"] + "/elsewhere"
    document["tools"].append(clone)
    with pytest.raises(ManifestError, match="duplicate toolId"):
        parse_manifest(document)


def test_an_open_parameter_object_is_refused(document):
    document["tools"][0]["parameters"]["additionalProperties"] = True
    with pytest.raises(ManifestError, match="additionalProperties"):
        parse_manifest(document)


def test_an_optional_path_parameter_is_refused(document):
    """A path segment filled from nowhere resolves to a different endpoint —
    ``/api/admin/flagged-transactions/`` is a list, not an item."""
    tool = next(t for t in document["tools"] if "{" in t["target"]["path"])
    tool["parameters"]["required"] = []
    with pytest.raises(ManifestError, match="optional"):
        parse_manifest(document)


def test_an_unusable_redaction_path_is_refused(document):
    document["tools"][0]["redaction"] = ["customer.ssn"]
    with pytest.raises(ManifestError, match="redaction"):
        parse_manifest(document)


def test_an_unresolvable_upstream_refuses_startup(document, monkeypatch):
    from app.config import load_settings
    from app.tools.registry import build_registry

    document["tools"][0]["target"]["service"] = "service-that-does-not-exist"
    monkeypatch.delenv("SERVICE_THAT_DOES_NOT_EXIST_URL", raising=False)
    with pytest.raises(ManifestError, match="base URL"):
        build_registry(parse_manifest(document), load_settings())


# ---------------------------------------------------------------------------
# F2-4 — the spec divergence, asserted.
# ---------------------------------------------------------------------------


def test_the_epic_worked_manifest_cannot_be_loaded_by_the_shipping_loader(manifest_section_3_3):
    """FINDING F2-4, in its least deniable form.

    Epic §3.2 defines the manifest schema and §3.3 prints six worked entries.
    The shipping loader refuses them — the schemas are mutually incompatible,
    and both are currently presented as normative.

    This is not an argument that the loader is wrong; "there is no way to spell
    a write" is a stronger property than §3.2's ``mode`` flag, and duplicating
    ``requiredEvidence`` outside the policy file is the defect class that cost
    Phase 1 a privilege escalation. It IS an argument that one of the two
    documents must be amended, by the person who owns the contract, before
    anybody builds a second manifest from §3.3 and finds out at startup.

    Asserts the current state. Goes red when the divergence is resolved.
    """
    document = {
        "apiVersion": "copilot-tools/v1",
        "metadata": {"manifestId": "epic-3-3"},
        "tools": manifest_section_3_3,
    }
    with pytest.raises(ManifestError) as exc:
        parse_manifest(document)
    assert "mode" in str(exc.value), (
        "the loader now accepts epic §3.3's schema, or refuses it for a different "
        "reason — either way F2-4 has moved and this test must be revisited"
    )
