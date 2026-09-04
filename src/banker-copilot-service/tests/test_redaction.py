"""Redaction — applied at emit, because persisted traces outlive the session."""

from __future__ import annotations

import pytest

from app.tools.redaction import REDACTED, RedactionPathError, redact, validate_paths


def test_object_field_is_redacted():
    result = redact({"customer": {"ssn": "123-45-6789", "name": "Ada"}}, ["$.customer.ssn"])
    assert result["customer"]["ssn"] == REDACTED
    assert result["customer"]["name"] == "Ada"


def test_wildcard_over_a_list_redacts_every_element():
    payload = [{"ipAddress": "a"}, {"ipAddress": "b"}]
    result = redact(payload, ["$[*].ipAddress"])
    assert [row["ipAddress"] for row in result] == [REDACTED, REDACTED]


def test_redaction_does_not_mutate_the_source_document():
    original = {"customer": {"ssn": "123-45-6789"}}
    redact(original, ["$.customer.ssn"])
    assert original["customer"]["ssn"] == "123-45-6789"


def test_absent_path_is_a_no_op_not_an_error():
    assert redact({"a": 1}, ["$.customer.ssn"]) == {"a": 1}


@pytest.mark.parametrize(
    "path",
    ["customer.ssn", "$", "$..ssn", "$.customer[?(@.x)]", "$.customer.*"],
)
def test_unsupported_expressions_are_rejected_loudly(path):
    """A redaction rule that silently matches nothing is indistinguishable from one that
    worked — the worst possible failure mode for this particular code."""
    with pytest.raises(RedactionPathError):
        validate_paths([path])


def test_every_redaction_path_in_the_shipped_manifest_is_supported(registry):
    for tool in registry.tools:
        validate_paths(tool.redaction)


def test_shipped_manifest_redacts_pii_on_the_tools_that_return_it(registry):
    """Set membership, so a tool losing its redaction rule fails by name."""
    expected = {
        "get_flagged_transaction": {"$.customer.ssn", "$.customer.dateOfBirth"},
        "list_flagged_transactions": {"$[*].customer.ssn", "$[*].customer.dateOfBirth"},
        "list_login_audits": {"$[*].ipAddress"},
        "get_account_application": {"$.formData.ssn", "$.formData.dateOfBirth"},
    }
    for tool_id, paths in expected.items():
        assert set(registry.get(tool_id).redaction) == paths
