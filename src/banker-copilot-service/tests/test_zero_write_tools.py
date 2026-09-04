"""The proof this epic rests on: banker-copilot-service registers ZERO write tools.

These tests are written to fail loudly rather than pass quietly. Where a count would do, a set
comparison is used instead — a count is satisfied by arithmetic and a miscount passes silently,
whereas a set difference names the offender.
"""

from __future__ import annotations

import copy

import pytest
import yaml

from app.tools.manifest import (
    READ_METHODS,
    ManifestError,
    load_manifest,
    parse_manifest,
)
from app.tools.registry import (
    PROPOSE_TOOL_ID,
    ToolRegistry,
    WriteToolRegistrationError,
    assert_zero_write_tools,
    build_registry,
)

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


@pytest.fixture
def raw_manifest(manifest_path):
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- zero writes ----


def test_registry_uses_only_read_methods(registry: ToolRegistry):
    """Set difference, not a count. Names the offending method if this ever regresses."""
    assert registry.methods_in_use() - READ_METHODS == frozenset()
    assert registry.methods_in_use() <= READ_METHODS


def test_registry_has_no_write_tools(registry: ToolRegistry):
    assert registry.write_tools() == ()
    assert_zero_write_tools(registry)


def test_every_capability_scope_is_a_read_scope(registry: ToolRegistry):
    non_read = {
        tool.capability_scope
        for tool in registry.tools
        if not tool.capability_scope.endswith(".read")
    }
    assert non_read == set()


def test_propose_action_is_not_a_registered_tool(registry: ToolRegistry):
    """The sole write affordance must never be reachable as an ordinary tool call."""
    assert PROPOSE_TOOL_ID not in registry.tool_ids


@pytest.mark.parametrize("method", WRITE_METHODS)
def test_manifest_refuses_a_write_method(raw_manifest, method):
    """Tamper test: add a write tool, confirm the loader refuses. A guard never observed
    failing is not proven."""
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"].append(
        {
            "toolId": "review_flagged_transaction",
            "displayName": "Clear or confirm a flagged transaction",
            "description": "Record a review decision on a flagged transaction.",
            "target": {
                "service": "ai-service",
                "method": method,
                "path": "/api/admin/flagged-transactions/{txId}/review",
                "timeoutMs": 8000,
            },
            "parameters": {
                "type": "object",
                "properties": {"txId": {"type": "string"}},
                "required": ["txId"],
                "additionalProperties": False,
            },
            "capabilityScope": "risk.read",
            "redaction": [],
        }
    )

    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(mutated)

    assert "read-method allowlist" in str(excinfo.value)


def test_manifest_refuses_a_write_capability_scope(raw_manifest):
    """Even with a GET, a write scope is not registrable — belt and braces on two axes."""
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"][0]["capabilityScope"] = "risk.write"

    with pytest.raises(ManifestError, match="read scopes only"):
        parse_manifest(mutated)


@pytest.mark.parametrize(
    "key, value",
    [
        ("mode", "write"),
        ("actionId", "transaction.flag.review"),
        ("authority", {"declaredRung": "L1", "policyRef": "read.any"}),
        ("idempotencyKeyFrom", ["txId"]),
        ("requiredEvidence", ["get_flagged_transaction"]),
        ("cosignerId", "usr_supervisor_1"),
    ],
)
def test_manifest_refuses_write_path_keys_by_name(raw_manifest, key, value):
    """Refused, never ignored.

    A key that is silently dropped looks exactly like a key that works: someone would write
    `mode: write`, read it back, and believe the manifest supports write tools.
    """
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"][0][key] = value

    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(mutated)

    assert key in str(excinfo.value)


def test_registry_rejects_a_tool_claiming_the_propose_id(raw_manifest, settings):
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"][0]["toolId"] = PROPOSE_TOOL_ID

    with pytest.raises(WriteToolRegistrationError, match="reserved tool id"):
        build_registry(parse_manifest(mutated), settings)


def test_assert_zero_write_tools_actually_fires(settings, registry):
    """The assertion itself is tamper-tested by constructing a registry the loader would
    never produce. Without this, `assert_zero_write_tools` could be a no-op and every other
    test here would still pass."""
    from dataclasses import replace

    poisoned_tool = replace(
        registry.tools[0],
        target=replace(registry.tools[0].target, method="DELETE"),
    )
    poisoned = ToolRegistry(
        manifest=replace(registry.manifest, tools=(poisoned_tool,)),
        service_urls=registry.service_urls,
    )

    with pytest.raises(WriteToolRegistrationError, match="ZERO write tools"):
        assert_zero_write_tools(poisoned)


# ------------------------------------------------------------- fail closed ----


def test_missing_manifest_refuses_to_start(tmp_path):
    with pytest.raises(ManifestError, match="refusing to start"):
        load_manifest(str(tmp_path / "does-not-exist.yaml"))


def test_malformed_yaml_refuses_to_start(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("tools: [\n  - toolId: oops\n", encoding="utf-8")

    with pytest.raises(ManifestError, match="not valid YAML"):
        load_manifest(str(path))


def test_unknown_top_level_key_is_refused(raw_manifest):
    mutated = copy.deepcopy(raw_manifest)
    mutated["writeTools"] = []

    with pytest.raises(ManifestError, match="unknown key"):
        parse_manifest(mutated)


def test_unknown_tool_key_is_refused_not_skipped(raw_manifest):
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"][1]["sideEffects"] = "none"

    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(mutated)

    message = str(excinfo.value)
    assert "sideEffects" in message
    assert "never skipped" in message


def test_unsupported_api_version_is_refused(raw_manifest):
    mutated = copy.deepcopy(raw_manifest)
    mutated["apiVersion"] = "copilot-tools/v2"

    with pytest.raises(ManifestError, match="Refusing to guess"):
        parse_manifest(mutated)


def test_duplicate_tool_id_is_refused(raw_manifest):
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"].append(copy.deepcopy(mutated["tools"][0]))

    with pytest.raises(ManifestError, match="duplicate toolId"):
        parse_manifest(mutated)


def test_open_parameter_object_is_refused(raw_manifest):
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"][1]["parameters"].pop("additionalProperties")

    with pytest.raises(ManifestError, match="additionalProperties"):
        parse_manifest(mutated)


def test_unbound_path_parameter_is_refused(raw_manifest):
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"][1]["target"]["path"] = "/api/admin/flagged-transactions/{missingId}"

    with pytest.raises(ManifestError, match="which no parameter supplies"):
        parse_manifest(mutated)


def test_optional_path_parameter_is_refused(raw_manifest):
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"][1]["parameters"]["required"] = []

    with pytest.raises(ManifestError, match="optional"):
        parse_manifest(mutated)


def test_missing_timeout_is_refused(raw_manifest):
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"][0]["target"].pop("timeoutMs")

    with pytest.raises(ManifestError, match="timeoutMs"):
        parse_manifest(mutated)


def test_unusable_redaction_path_is_refused(raw_manifest):
    mutated = copy.deepcopy(raw_manifest)
    mutated["tools"][0]["redaction"] = ["$..customer..ssn[?(@.x)]"]

    with pytest.raises(ManifestError, match="redaction path"):
        parse_manifest(mutated)


def test_unresolvable_upstream_refuses_to_start(raw_manifest, settings, monkeypatch):
    monkeypatch.delenv("DOWNSTREAM__transfer-service", raising=False)
    from app.config import load_settings

    with pytest.raises(ManifestError, match="no base URL configured"):
        build_registry(parse_manifest(raw_manifest), load_settings())


# ------------------------------------------------------- the shipped manifest ----


EXPECTED_TOOL_IDS = frozenset(
    {
        "list_flagged_transactions",
        "get_flagged_transaction",
        "get_scored_transaction",
        "get_transaction",
        "list_account_transactions",
        "get_account",
        "get_transfer",
        "get_user",
        "list_login_audits",
        "list_account_applications",
        "get_account_application",
        "get_application_audit",
    }
)


def test_shipped_manifest_registers_exactly_the_expected_tools(registry: ToolRegistry):
    """Set equality, both directions.

    A subset check would pass if someone added a tool; a superset check would pass if someone
    removed one. Testing one direction is testing neither.
    """
    assert registry.tool_ids == EXPECTED_TOOL_IDS


def test_evidence_tools_named_by_the_authority_policy_all_exist(registry: ToolRegistry):
    """Cross-service seam check.

    `config/authority-policy.yaml` names the evidence a proposal must carry. If it names an
    evidence id the harness cannot produce, the ladder demands proof that is unobtainable —
    and each file would be internally coherent while the system is broken, which is exactly
    how Phase 1's privilege escalation survived review.
    """
    import pathlib

    policy_path = (
        pathlib.Path(__file__).resolve().parents[3] / "config" / "authority-policy.yaml"
    )
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))

    referenced: set[str] = set()
    for action in (policy.get("actionTypes") or {}).values():
        referenced.update(action.get("requiredEvidence") or [])

    # Loan-origination evidence belongs to Phase 4 (#140) and has no tool yet — excluded
    # explicitly and by name, so the exclusion is visible rather than hidden in a subset check.
    phase_4 = {"get_loan_application", "get_underwriting_decision", "get_policy_evaluation"}

    assert (referenced - phase_4) - registry.tool_ids == set()
