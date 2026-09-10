"""Acceptance coverage for Brian's exact Banker Copilot demo prompts.

The model call is stubbed at the intent boundary on purpose: these tests prove the planner
can execute the structured intent the model returns for Brian's words. If a sentence needs a
resolver the planner does not have, the test is xfailed instead of hidden behind a fixture id.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from conftest import REPO_ROOT, judging_assessor, shipped_assessment_limits

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.intent_model import EvidenceAnswer, IntentDecision
from app.planner.loop import Planner, PlannerRequest
from app.tools.executor import ToolInvocationError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


PROMPTS = {
    "summary": "Summarise casey's accounts and recent activity",
    "offshore": "Why was casey's offshore wire flagged?",
    "compare": "Compare dana's checking history against casey's — anything unusual?",
    "retail_refund": "Refund a $35 overdraft fee on retail's checking as goodwill",
    "dana_credit": "Credit dana $120 for a duplicate charge on her checking account",
    "casey_savings": "Post a $2,400 adjustment to casey's savings for the disputed deposit",
    "unlock": "Unlock verify-target's account — lockout was a stale saved password",
    "retail_large": "Adjust retail's savings by $26,000",
    "score": "Casey's offshore wire is legitimate — she notified us in advance. Lower its risk score.",
}


class _Result:
    def __init__(self, data: Any) -> None:
        self.data = data
        self.duration_ms = 1

    def summary(self) -> str:
        return "ok"


class _Tool:
    def __init__(self, tool_id: str, params: tuple[str, ...] = (), scope: str = "risk.read") -> None:
        self.tool_id = tool_id
        self.capability_scope = scope
        self.parameters = {
            "type": "object",
            "properties": {p: {"type": "string"} for p in params},
            "required": list(params),
            "additionalProperties": False,
        }


class _Registry:
    def __init__(self) -> None:
        self._tools = {
            "lookup_customer": _Tool("lookup_customer", ("username",), "customer-directory.read"),
            "list_customer_accounts": _Tool("list_customer_accounts", ("userId",), "accounts.read"),
            "get_account": _Tool("get_account", ("accountId",), "accounts.read"),
            "list_account_transactions": _Tool("list_account_transactions", ("accountId",), "transactions.read"),
            "list_flagged_transactions": _Tool("list_flagged_transactions", (), "risk.read"),
            "get_scored_transaction": _Tool("get_scored_transaction", ("txId",), "risk.read"),
            "get_user": _Tool("get_user", ("userId",), "identity.read"),
            "list_login_audits": _Tool("list_login_audits", (), "identity.read"),
        }

    @property
    def tool_ids(self):
        return frozenset(self._tools)

    def get(self, tool_id: str):
        return self._tools.get(tool_id)

    def describe(self) -> list[dict[str, Any]]:
        return [{"toolId": tool.tool_id, "capabilityScope": tool.capability_scope, "parameters": tool.parameters} for tool in self._tools.values()]


USERS = {
    "casey": {"id": "usr_casey", "username": "casey", "displayName": "Casey Retail"},
    "dana": {"id": "usr_dana", "username": "dana", "displayName": "Dana Retail"},
    "retail": {"id": "usr_retail", "username": "retail", "displayName": "Retail Customer"},
    "verify-target": {"id": "usr_verify", "username": "verify-target", "displayName": "Verify Target"},
}

ACCOUNTS = {
    "usr_casey": [
        {"id": "acct_casey_checking", "accountId": "acct_casey_checking", "accountType": "Checking", "balance": "16143.46"},
        {"id": "acct_casey_savings", "accountId": "acct_casey_savings", "accountType": "Savings", "balance": "45000.00"},
    ],
    "usr_dana": [{"id": "acct_dana_checking", "accountId": "acct_dana_checking", "accountType": "Checking", "balance": "2200.00"}],
    "usr_retail": [
        {"id": "acct_retail_checking", "accountId": "acct_retail_checking", "accountType": "Checking", "balance": "900.00"},
        {"id": "acct_retail_savings", "accountId": "acct_retail_savings", "accountType": "Savings", "balance": "30000.00"},
    ],
}


class _Executor:
    async def invoke(self, tool_id: str, arguments: dict[str, Any], bearer: str) -> _Result:
        if tool_id == "lookup_customer":
            user = USERS.get(arguments["username"].lower())
            return _Result({"query": arguments["username"], "count": 1 if user else 0, "matches": [user] if user else []})
        if tool_id == "list_customer_accounts":
            accounts = ACCOUNTS.get(arguments["userId"], [])
            return _Result({"userId": arguments["userId"], "count": len(accounts), "accounts": accounts})
        if tool_id == "get_account":
            account = _account(arguments["accountId"])
            if account is None:
                raise ToolInvocationError("upstream_not_found", "account-service returned 404")
            return _Result(account)
        if tool_id == "list_account_transactions":
            return _Result({"accountId": arguments["accountId"], "count": 6, "items": [{"id": "txn_recent_1"}]})
        if tool_id == "list_flagged_transactions":
            return _Result([{"id": "tx_casey_wire", "customer": {"username": "casey"}, "description": "offshore wire", "riskScore": "0.91"}])
        if tool_id == "get_scored_transaction":
            return _Result({"transactionId": arguments["txId"], "accountId": "acct_casey_checking", "riskScore": "0.91"})
        if tool_id == "get_user":
            return _Result({"id": arguments["userId"], "username": "verify-target", "isLocked": True})
        if tool_id == "list_login_audits":
            return _Result({"count": 4, "items": [{"status": "failed"}]})
        raise ToolInvocationError("unknown_tool", tool_id)


def _account(account_id: str) -> dict[str, Any] | None:
    for accounts in ACCOUNTS.values():
        for account in accounts:
            if account["accountId"] == account_id:
                return account
    return None


class _Authority:
    def __init__(self) -> None:
        self.propose_calls: list[dict[str, Any]] = []

    async def policy_catalogue(self, bearer_token: str) -> dict[str, Any]:
        return {
            "thresholds": [{"name": "score_override_floor", "value": "0.25"}],
            "actions": [
                {
                    "id": "account.balance.adjust",
                    "displayName": "Post a balance adjustment",
                    "baseRung": "L1",
                    "agentMayPropose": True,
                    "requiredEvidence": ["get_account", "list_account_transactions"],
                    "hashFields": ["accountId", "amount", "direction", "reason"],
                    "moneyFields": ["amount"],
                },
                {
                    "id": "user.unlock",
                    "displayName": "Unlock a customer account",
                    "baseRung": "L2",
                    "agentMayPropose": True,
                    "requiredEvidence": ["get_user", "list_login_audits"],
                    "hashFields": ["userId", "reason"],
                    "moneyFields": [],
                },
                {
                    "id": "transaction.score.override",
                    "displayName": "Override an AI risk score",
                    "baseRung": "L2",
                    "agentMayPropose": True,
                    "requiredEvidence": ["get_scored_transaction", "get_account", "list_account_transactions"],
                    "hashFields": ["transactionId", "newScore", "rationale"],
                    "moneyFields": [],
                },
                {
                    "id": "user.password.reset",
                    "displayName": "Reset a password",
                    "baseRung": "L3",
                    "agentMayPropose": False,
                    "requiredEvidence": [],
                    "hashFields": ["userId"],
                    "moneyFields": [],
                },
            ],
        }

    async def propose(self, body, *, bearer_token, session_id, agent_id, correlation_id):
        self.propose_calls.append(body)
        payload = body["payload"]
        action_id = body["actionId"]
        rung = "L1"
        escalators: list[dict[str, str]] = []
        if action_id in {"user.unlock", "transaction.score.override"}:
            rung = "L2"
        if action_id == "account.balance.adjust":
            amount = abs(float(payload["amount"]))
            if amount >= 1000:
                rung = "L2"
                escalators.append({"key": "large-adjustment"})
            if payload.get("direction") == "credit":
                rung = "L2"
                escalators.append({"key": "credit-adjustment"})
            if str(payload.get("accountId", "")).startswith("acct_casey"):
                rung = "L2"
                escalators.append({"key": "high-risk-customer"})
        return type(
            "Outcome",
            (),
            {
                "status_code": 201,
                "admitted": True,
                "body": {"id": "apr_demo", "requiredRung": rung, "firedEscalators": escalators, "agentAssessment": {"summary": "ok"}},
            },
        )()


class _Store:
    def __init__(self) -> None:
        self.artifacts: list[Any] = []

    async def save_artifact(self, artifact):
        self.artifacts.append(artifact)


class _Session:
    id = "sess_demo"
    actor_id = "usr_banker"
    actor_username = "banker"
    context: dict[str, Any] = {}
    capabilities = ["risk.read", "identity.read", "customer-directory.read", "accounts.read", "transactions.read"]


async def _run_prompt(prompt: str, decision: IntentDecision, answerer=None) -> tuple[list[dict[str, Any]], _Authority, _Store]:
    authority = _Authority()
    store = _Store()

    async def selector(objective: str, **_kwargs) -> IntentDecision:
        assert objective == prompt
        return decision

    planner = Planner(
        registry=_Registry(),
        executor=_Executor(),
        authority=authority,
        max_iterations=20,
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
        intent_selector=selector,
        answerer=answerer or _answerer_requiring_evidence,
        store=store,
    )
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    stream = runs.create("run_demo", "sess_demo")
    await planner.run(
        PlannerRequest(
            session=_Session(),
            run_id="run_demo",
            objective=prompt,
            action_id=None,
            payload={},
            facts={},
            bearer_token="token",
        ),
        stream,
    )
    return runs.sink._frames["run_demo"], authority, store  # type: ignore[attr-defined]


async def _answerer_requiring_evidence(objective: str, answer_goal: str, evidence: Mapping[str, Any]) -> EvidenceAnswer:
    if not evidence:
        return EvidenceAnswer(answer="", failure_code="empty_evidence", failure_message=f"{objective}: no evidence gathered")
    return EvidenceAnswer(answer="Answered from evidence.", cited_evidence_ids=tuple(evidence.keys()))


def _proposal(frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    frames = [frame for frame in frames if frame["kind"] == "approval.required"]
    return frames[0]["payload"]["approval"] if frames else None


def _error_code(frames: list[dict[str, Any]]) -> str | None:
    errors = [frame for frame in frames if frame["kind"] == "run.error"]
    return errors[0]["payload"]["code"] if errors else None


def _terminal(frames: list[dict[str, Any]]) -> str:
    return [frame for frame in frames if frame["kind"] == "run.done"][0]["payload"]["status"]


def _assert_prompt_is_in_demo_doc(prompt: str) -> None:
    text = (REPO_ROOT / "docs/design/banker-copilot-demo-prompts.md").read_text(encoding="utf-8")
    assert prompt in text


@pytest.mark.parametrize(
    ("name", "decision"),
    [
        (
            "summary",
            IntentDecision(
                kind="read",
                read_plan=(
                    {"toolId": "lookup_customer", "arguments": {"username": "casey"}},
                    {"toolId": "list_customer_accounts", "arguments": {"userId": "usr_casey"}},
                    {"toolId": "list_account_transactions", "arguments": {"accountId": "acct_casey_checking"}},
                ),
                answer_goal="Summarise Casey's accounts and recent activity.",
            ),
        ),
        (
            "offshore",
            IntentDecision(
                kind="read",
                read_plan=({"toolId": "list_flagged_transactions", "arguments": {}},),
                answer_goal="Explain why Casey's offshore wire was flagged.",
            ),
        ),
    ],
)
async def test_demo_read_only_prompt_answers_with_evidence_and_no_approval(name: str, decision: IntentDecision):
    prompt = PROMPTS[name]
    _assert_prompt_is_in_demo_doc(prompt)

    frames, authority, store = await _run_prompt(prompt, decision)

    assert authority.propose_calls == [], f"{prompt}: read-only prompts must not create approvals"
    assert _proposal(frames) is None, f"{prompt}: unexpected approval"
    assert _terminal(frames) == "completed", f"{prompt}: {_error_code(frames)}"
    assert any(a.kind == "answer" for a in store.artifacts), f"{prompt}: missing answer artifact"


@pytest.mark.xfail(strict=True, reason="The read artifact is keyed by tool id, so two calls to the same lookup/history tool overwrite each other.")
async def test_demo_compare_prompt_needs_multi_subject_evidence_not_duplicate_tool_key_overwrite():
    prompt = PROMPTS["compare"]
    _assert_prompt_is_in_demo_doc(prompt)

    frames, _authority, store = await _run_prompt(
        prompt,
        IntentDecision(
            kind="read",
            read_plan=(
                {"toolId": "lookup_customer", "arguments": {"username": "dana"}},
                {"toolId": "lookup_customer", "arguments": {"username": "casey"}},
                {"toolId": "list_account_transactions", "arguments": {"accountId": "acct_dana_checking"}},
                {"toolId": "list_account_transactions", "arguments": {"accountId": "acct_casey_checking"}},
            ),
            answer_goal="Compare Dana and Casey checking histories.",
        ),
    )
    evidence = next(a.content for a in store.artifacts if a.kind == "evidence_bundle")
    account_history_ids = [
        data.get("accountId")
        for key, data in evidence.items()
        if key == "list_account_transactions" and isinstance(data, Mapping)
    ]
    assert _terminal(frames) == "completed", f"{prompt}: {_error_code(frames)}"
    assert sorted(account_history_ids) == ["acct_casey_checking", "acct_dana_checking"], f"{prompt}: received {evidence!r}"


@pytest.mark.parametrize(
    ("name", "decision", "expected_rung", "expected_payload", "expected_escalators"),
    [
        (
            "retail_refund",
            IntentDecision(
                kind="propose",
                action_id="account.balance.adjust",
                subject_hints={"customer": "retail", "accountType": "Checking"},
                payload_draft={"amount": "35", "direction": "debit", "reason": "Goodwill overdraft fee refund."},
            ),
            "L1",
            {"accountId": "acct_retail_checking", "amount": "35.00", "direction": "debit", "reason": "Goodwill overdraft fee refund."},
            set(),
        ),
        (
            "dana_credit",
            IntentDecision(
                kind="propose",
                action_id="account.balance.adjust",
                subject_hints={"customer": "dana", "accountType": "Checking"},
                payload_draft={"amount": "120", "direction": "credit", "reason": "Duplicate charge credit."},
            ),
            "L2",
            {"accountId": "acct_dana_checking", "amount": "120.00", "direction": "credit", "reason": "Duplicate charge credit."},
            {"credit-adjustment"},
        ),
        (
            "casey_savings",
            IntentDecision(
                kind="propose",
                action_id="account.balance.adjust",
                subject_hints={"customer": "casey", "accountType": "Savings"},
                payload_draft={"amount": "2400", "direction": "debit", "reason": "Disputed deposit adjustment."},
            ),
            "L2",
            {"accountId": "acct_casey_savings", "amount": "2400.00", "direction": "debit", "reason": "Disputed deposit adjustment."},
            {"large-adjustment", "high-risk-customer"},
        ),
        (
            "retail_large",
            IntentDecision(
                kind="propose",
                action_id="account.balance.adjust",
                subject_hints={"customer": "retail", "accountType": "Savings"},
                payload_draft={"amount": "26000", "direction": "debit", "reason": "Customer-requested savings adjustment."},
            ),
            "L2",
            {"accountId": "acct_retail_savings", "amount": "26000.00", "direction": "debit", "reason": "Customer-requested savings adjustment."},
            {"large-adjustment"},
        ),
    ],
)
async def test_demo_balance_adjustment_prompt_proposes_expected_payload_and_rung(
    name: str,
    decision: IntentDecision,
    expected_rung: str,
    expected_payload: dict[str, Any],
    expected_escalators: set[str],
):
    prompt = PROMPTS[name]
    _assert_prompt_is_in_demo_doc(prompt)

    frames, authority, _store = await _run_prompt(prompt, decision)

    assert authority.propose_calls[0]["payload"] == expected_payload, f"{prompt}: payload mismatch"
    approval = _proposal(frames)
    assert approval is not None, f"{prompt}: no approval; error={_error_code(frames)}"
    assert approval["requiredRung"] == expected_rung, f"{prompt}: wrong rung"
    assert {item["key"] for item in approval.get("firedEscalators", [])} == expected_escalators
    assert _terminal(frames) == "completed", f"{prompt}: {_error_code(frames)}"


async def test_demo_unlock_prompt_proposes_base_l2():
    prompt = PROMPTS["unlock"]
    _assert_prompt_is_in_demo_doc(prompt)

    frames, authority, _store = await _run_prompt(
        prompt,
        IntentDecision(
            kind="propose",
            action_id="user.unlock",
            subject_hints={"customer": "verify-target"},
            payload_draft={"reason": "Lockout was caused by a stale saved password."},
        ),
    )

    assert authority.propose_calls[0]["payload"] == {"userId": "usr_verify", "reason": "Lockout was caused by a stale saved password."}
    assert _proposal(frames)["requiredRung"] == "L2"
    assert _terminal(frames) == "completed", f"{prompt}: {_error_code(frames)}"


async def test_demo_score_override_prompt_can_propose_inside_band_if_model_supplies_missing_score_and_transaction():
    prompt = PROMPTS["score"]
    _assert_prompt_is_in_demo_doc(prompt)

    frames, authority, _store = await _run_prompt(
        prompt,
        IntentDecision(
            kind="propose",
            action_id="transaction.score.override",
            subject_hints={"customer": "casey"},
            payload_draft={
                "transactionId": "tx_casey_wire",
                "newScore": "0.30",
                "rationale": "Lowered from 0.91 to 0.30 because Casey notified the bank in advance.",
            },
        ),
    )

    assert authority.propose_calls[0]["payload"]["newScore"] == "0.30"
    assert _proposal(frames)["requiredRung"] == "L2"
    assert _terminal(frames) == "completed", f"{prompt}: {_error_code(frames)}"


async def test_demo_score_override_prompt_rejects_too_deep_model_score():
    prompt = PROMPTS["score"]
    _assert_prompt_is_in_demo_doc(prompt)

    frames, authority, _store = await _run_prompt(
        prompt,
        IntentDecision(
            kind="propose",
            action_id="transaction.score.override",
            subject_hints={"customer": "casey"},
            payload_draft={
                "transactionId": "tx_casey_wire",
                "newScore": "0.10",
                "rationale": "Lowered from 0.91 to 0.10 because Casey notified the bank in advance.",
            },
        ),
    )

    assert authority.propose_calls == []
    assert _proposal(frames) is None
    assert _error_code(frames) == "payload_invalid"
    assert _terminal(frames) == "failed"


@pytest.mark.xfail(strict=True, reason="The exact sentence gives no transaction id and no target score; no resolver maps 'offshore wire' to a scored transaction.")
async def test_demo_score_override_exact_sentence_cannot_yet_be_constructed_without_model_guessing_missing_fields():
    prompt = PROMPTS["score"]
    _assert_prompt_is_in_demo_doc(prompt)

    frames, authority, _store = await _run_prompt(
        prompt,
        IntentDecision(
            kind="propose",
            action_id="transaction.score.override",
            subject_hints={"customer": "casey"},
            payload_draft={
                "rationale": "Casey notified the bank in advance, but the objective contains no score or transaction id.",
            },
        ),
    )

    assert authority.propose_calls, f"{prompt}: received refusal {_error_code(frames)}"


@pytest.mark.parametrize(
    ("prompt", "decision", "expected_code"),
    [
        (
            "Reset casey's password so she can sign in",
            IntentDecision(kind="propose", action_id="user.password.reset", subject_hints={"customer": "casey"}, payload_draft={}),
            "forbidden_action",
        ),
        (
            "Send Casey a birthday card",
            IntentDecision(kind="propose", action_id="customer.greeting.send", payload_draft={}),
            "objective_unmappable",
        ),
        (
            "Refund a $35 overdraft fee on nobody-here's checking as goodwill",
            IntentDecision(
                kind="propose",
                action_id="account.balance.adjust",
                subject_hints={"customer": "nobody-here", "accountType": "Checking"},
                payload_draft={"amount": "35", "direction": "debit", "reason": "Goodwill overdraft fee refund."},
            ),
            "subject_not_found",
        ),
    ],
)
async def test_demo_refusal_outcomes_are_named_failures_not_empty_success(
    prompt: str,
    decision: IntentDecision,
    expected_code: str,
):
    frames, authority, store = await _run_prompt(prompt, decision)

    assert authority.propose_calls == [], f"{prompt}: refusal should not propose"
    assert _proposal(frames) is None, f"{prompt}: refusal produced approval"
    assert _error_code(frames) == expected_code, f"{prompt}: received frames={frames!r}"
    assert _terminal(frames) == "failed"
    assert not any(a.kind == "evidence_bundle" and a.content == {} for a in store.artifacts), f"{prompt}: empty evidence bundle emitted"
