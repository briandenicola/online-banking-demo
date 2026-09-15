from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.events.envelope import CopilotEventEnvelope, EnvelopeError, utc_now_iso
from app.tools.manifest import ManifestError, parse_manifest
from app.tools.standing_approval import StandingReadApprovalLedger


EXPECTED_SENSITIVE_TRUE = frozenset(
    {
        "list_flagged_transactions",
        "get_flagged_transaction",
        "get_scored_transaction",
        "list_account_transactions",
        "list_login_audits",
        "list_account_applications",
        "get_account_application",
    }
)

EXPECTED_SENSITIVE_FALSE = frozenset(
    {
        "get_transaction",
        "get_account",
        "list_customer_accounts",
        "get_account_by_number",
        "get_transfer",
        "get_user",
        "lookup_customer",
        "get_application_audit",
    }
)


def _manifest(**tool_overrides):
    tool = {
        "toolId": "get_sensitive",
        "displayName": "Sensitive",
        "description": "Sensitive read",
        "target": {"service": "account-service", "method": "GET", "path": "/x/{id}", "timeoutMs": 1000},
        "parameters": {"type": "object", "properties": {"id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"}}, "required": ["id"], "additionalProperties": False},
        "capabilityScope": "accounts.read",
        "redaction": [],
        **tool_overrides,
    }
    return {"apiVersion": "copilot-tools/v1", "metadata": {"manifestId": "test"}, "tools": [tool]}


def test_shipped_manifest_sensitive_classification_split_is_intentional(manifest_path):
    from app.tools.manifest import load_manifest

    manifest = load_manifest(str(manifest_path))
    classifications = {tool.tool_id: tool.sensitive for tool in manifest.tools}

    assert set(classifications) == EXPECTED_SENSITIVE_TRUE | EXPECTED_SENSITIVE_FALSE
    assert any(classifications.values())
    assert not all(classifications.values())
    assert {tool_id for tool_id, sensitive in classifications.items() if sensitive} == EXPECTED_SENSITIVE_TRUE
    assert {tool_id for tool_id, sensitive in classifications.items() if not sensitive} == EXPECTED_SENSITIVE_FALSE


def test_sensitive_classification_is_mandatory():
    with pytest.raises(ManifestError, match="must declare 'sensitive' explicitly"):
        parse_manifest(_manifest())


def test_sensitive_classification_must_be_boolean():
    with pytest.raises(ManifestError, match="sensitive.*boolean"):
        parse_manifest(_manifest(sensitive="yes"))


def test_unknown_sensitive_classification_key_fails_closed():
    with pytest.raises(ManifestError, match="unknown key"):
        parse_manifest(_manifest(sensitiv="yes"))


@pytest.mark.parametrize("payload", [None, [], 1])
def test_sensitive_read_envelope_rejects_non_object_payload(payload):
    with pytest.raises(EnvelopeError):
        CopilotEventEnvelope(
            id="evt_sensitive", seq=1, run_id="run", kind="sensitive_read_recorded",
            ts=utc_now_iso(), payload=payload,  # type: ignore[arg-type]
        )


def test_sensitive_read_envelope_is_closed_and_non_pii():
    envelope = CopilotEventEnvelope(
        id="evt_sensitive", seq=1, run_id="run", session_id="sess", kind="sensitive_read_recorded",
        ts=utc_now_iso(), payload={"toolId": "get_sensitive", "scope": "session", "context": {"argumentKeys": ["id"]}},
    )
    assert "secret" not in str(envelope.to_wire())
    with pytest.raises(EnvelopeError):
        CopilotEventEnvelope(
            id="evt_sensitive", seq=1, run_id="run", kind="sensitive_read_recorded", ts=utc_now_iso(),
            payload={"toolId": "get_sensitive", "scope": "session", "context": {"argumentKeys": ["id"], "id": "secret"}},
        )


def test_standing_approval_is_first_per_tool_per_session():
    async def scenario():
        ledger = StandingReadApprovalLedger()
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        s1 = type("Session", (), {"id": "s1", "expires_at": expiry})()
        s2 = type("Session", (), {"id": "s2", "expires_at": expiry})()
        return (
            await ledger.record_first(s1, "get_sensitive"),
            await ledger.record_first(s1, "get_sensitive"),
            await ledger.record_first(s1, "get_other"),
            await ledger.record_first(s2, "get_sensitive"),
        )
    assert asyncio.run(scenario()) == (True, False, True, True)


def test_standing_approval_expires_with_session():
    async def scenario():
        ledger = StandingReadApprovalLedger()
        expired = type("Session", (), {"id": "s1", "expires_at": "2000-01-01T00:00:00Z"})()
        live = type("Session", (), {
            "id": "s1",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        })()
        return await ledger.record_first(expired, "get_sensitive"), await ledger.record_first(live, "get_sensitive")
    assert asyncio.run(scenario()) == (False, True)


def _fake_session(session_id: str, minutes_to_expiry: int = 5):
    return type("Session", (), {
        "id": session_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=minutes_to_expiry)).isoformat(),
    })()


def test_standing_approval_ledger_is_bounded_by_max_sessions():
    async def scenario():
        ledger = StandingReadApprovalLedger(max_sessions=2)
        # s1 expires soonest, s2 next, s3 latest: adding s3 while full should evict s1.
        s1, s2, s3 = _fake_session("s1", 1), _fake_session("s2", 2), _fake_session("s3", 3)
        await ledger.record_first(s1, "get_sensitive")
        await ledger.record_first(s2, "get_sensitive")
        await ledger.record_first(s3, "get_sensitive")
        assert len(ledger._expires_at) == 2
        assert "s1" not in ledger._expires_at
        assert "s2" in ledger._expires_at and "s3" in ledger._expires_at
        # s1 was evicted, so recording it again is treated as a fresh session (first == True).
        return await ledger.record_first(s1, "get_sensitive")
    assert asyncio.run(scenario()) is True


def test_standing_approval_rejects_non_positive_capacity():
    with pytest.raises(ValueError, match="max_sessions"):
        StandingReadApprovalLedger(max_sessions=0)


def test_standing_approval_evicted_session_can_be_recorded_again():
    async def scenario():
        ledger = StandingReadApprovalLedger(max_sessions=1)
        s1, s2 = _fake_session("s1"), _fake_session("s2")
        first_s1 = await ledger.record_first(s1, "get_sensitive")
        # s2 forces eviction of s1 since capacity is 1.
        first_s2 = await ledger.record_first(s2, "get_sensitive")
        # s1 is gone from the ledger, so its "first" recording succeeds again.
        second_s1 = await ledger.record_first(s1, "get_sensitive")
        return first_s1, first_s2, second_s1
    assert asyncio.run(scenario()) == (True, True, True)


@pytest.mark.asyncio
async def test_planner_records_sensitive_once_and_non_sensitive_never():
    from types import SimpleNamespace

    from app.events.bus import InMemoryTraceSink, RunStreamRegistry
    from app.planner.limits import AssessmentLimits
    from app.planner.loop import Planner, PlannerRequest
    from app.tools.executor import ToolResult

    class Registry:
        def __init__(self):
            self.tools = {
                "get_sensitive": SimpleNamespace(sensitive=True),
                "get_public": SimpleNamespace(sensitive=False),
            }
        def get(self, tool_id):
            return self.tools.get(tool_id)

    class Executor:
        async def invoke(self, tool_id, arguments, token):
            return ToolResult(tool_id, 200, {"ok": True}, 1)

    class Authority:
        def __getattr__(self, name):
            raise AssertionError("standing approval must not call authority-service")

    class Session:
        id = "session-1"
        actor_id = "banker"
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        actor_username = "banker"

    planner = Planner(
        Registry(), Executor(), Authority(), 10, AssessmentLimits(0, 1),
        assessor=lambda *a: None,
    )
    sink = InMemoryTraceSink()
    stream = RunStreamRegistry(sink, 100).create("run-1", "session-1")
    request = PlannerRequest(Session(), "run-1", "read", None, {}, {}, "token")
    from app.planner.agent_mode import AgentMode

    for tool_id in ("get_sensitive", "get_sensitive", "get_public"):
        ok = await planner._run_tool_step(
            request, stream, {"id": tool_id, "toolId": tool_id, "arguments": {"accountId": "acct-secret"}},
            {}, {}, AgentMode()
        )
        assert ok

    frames = await sink.read_run("run-1")
    records = [frame for frame in frames if frame["kind"] == "sensitive_read_recorded"]
    assert len(records) == 1
    assert records[0]["payload"] == {
        "toolId": "get_sensitive", "scope": "session", "context": {"argumentKeys": ["accountId"]}
    }
    assert "acct-secret" not in str(records[0])
