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


async def _run_prompt(
    prompt: str,
    decision: IntentDecision,
    answerer=None,
    request: PlannerRequest | None = None,
) -> tuple[list[dict[str, Any]], _Authority, _Store]:
    """Run one prompt. Pass ``request`` to inspect the facts map the run leaves behind.

    ``facts`` is not decoration — it binds later tool arguments and it travels to authority on
    the proposal body — so a test that cannot see it cannot prove what the run carried.
    """
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
        request
        or PlannerRequest(
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


def _blank_request(prompt: str) -> PlannerRequest:
    return PlannerRequest(
        session=_Session(),
        run_id="run_demo",
        objective=prompt,
        action_id=None,
        payload={},
        facts={},
        bearer_token="token",
    )


def _flatten(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [s for v in value.values() for s in _flatten(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _flatten(v)]
    return [str(value)]


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


_COMPARE_READ_PLAN = IntentDecision(
    kind="read",
    read_plan=(
        {"toolId": "lookup_customer", "arguments": {"username": "dana"}},
        {"toolId": "lookup_customer", "arguments": {"username": "casey"}},
        {"toolId": "list_account_transactions", "arguments": {"accountId": "acct_dana_checking"}},
        {"toolId": "list_account_transactions", "arguments": {"accountId": "acct_casey_checking"}},
    ),
    answer_goal="Compare Dana and Casey checking histories.",
)


async def test_demo_compare_prompt_keeps_both_subjects_and_says_which_is_which():
    """Danny's ruling A5/A6: two invocations of one tool must both survive, self-describing.

    The bundle key disambiguates; the entry explains. Two histories side by side with no
    subject labels is a worse artifact than one history, because the banker cannot tell whose
    is whose and has no way to find out.
    """
    prompt = PROMPTS["compare"]
    _assert_prompt_is_in_demo_doc(prompt)

    frames, authority, store = await _run_prompt(prompt, _COMPARE_READ_PLAN)

    assert _terminal(frames) == "completed", f"{prompt}: {_error_code(frames)}"
    assert authority.propose_calls == [], f"{prompt}: a comparison must not create an approval"

    evidence = next(a.content for a in store.artifacts if a.kind == "evidence_bundle")
    histories = {
        key: entry for key, entry in evidence.items()
        if isinstance(entry, Mapping) and entry.get("toolId") == "list_account_transactions"
    }
    assert len(histories) == 2, f"{prompt}: one ledger overwrote the other: {sorted(evidence)}"
    assert sorted(e["data"]["accountId"] for e in histories.values()) == [
        "acct_casey_checking",
        "acct_dana_checking",
    ], f"{prompt}: received {evidence!r}"

    # Bare-first, ordinal-suffix-on-collision. Every single-invocation run in this file keeps
    # its existing key, so no trace, citation or artifact moves for a run that exists today.
    assert "list_account_transactions" in histories
    assert "list_account_transactions#2" in histories
    assert "list_account_transactions#1" not in evidence

    for key, entry in histories.items():
        assert entry["arguments"], f"{key}: entry does not say what it was called with"
        assert entry["subject"] == {"accountId": entry["data"]["accountId"]}, (
            f"{key}: entry does not say whose evidence it is"
        )


async def test_demo_compare_prompt_leaves_no_cross_subject_value_in_the_facts_map():
    """Danny §A3, the half of the bug nobody was looking at.

    `facts` is not decoration: it binds tool arguments the plan did not supply, and it is sent
    to authority on the proposal body. It merged FIRST-writer-wins, so on a two-customer run
    the first customer's identifiers occupied the keys and the second customer's were dropped
    on the floor — a path to an approval that names one customer and carries another's ids.
    """
    prompt = PROMPTS["compare"]
    request = _blank_request(prompt)

    frames, _authority, _store = await _run_prompt(prompt, _COMPARE_READ_PLAN, request=request)

    assert _terminal(frames) == "completed", f"{prompt}: {_error_code(frames)}"
    carried = _flatten(request.facts)
    for identifier in ("dana", "casey", "usr_dana", "usr_casey", "acct_dana_checking", "acct_casey_checking"):
        assert identifier not in carried, (
            f"{prompt}: facts carried {identifier!r} out of a two-subject run: {request.facts!r}"
        )


# ------------------------------------------------------- the boundary the keys must not cross ----
#
# Danny's ruling §A2. Inside the planner the evidence accumulator may key per invocation. The
# map that LEAVES this service — the `evidence` object on the authority proposal, and the
# `gathered` set the evidence ceiling matches `already_gathered` against — stays keyed by policy
# evidence id, which is the bare tool id, carrying the tool's raw result. A suffixed key on the
# wire is `evidence_incomplete` at authority (fails closed, loudly, on every propose run); a
# suffixed key in `gathered` silently grants re-reads of tools already held (fails OPEN, quietly).


async def test_a_read_plan_may_omit_ids_the_banker_never_said_and_the_server_fills_them():
    """The defect the live gate caught in the cloud on `Summarise casey's accounts`.

    The banker typed "casey". `list_customer_accounts` requires `userId`, an internal id that
    does not exist until the directory lookup runs — and the model is asked for its arguments
    BEFORE that lookup. So the model had exactly two moves: omit the id and fail the contract,
    or put the username in the id field. We asked it an impossible question.

    Ids are resolved server-side and injected into the read step. The model supplies the words
    the banker used; the planner supplies the identifier.
    """
    prompt = PROMPTS["summary"]
    _assert_prompt_is_in_demo_doc(prompt)

    frames, _authority, _store = await _run_prompt(
        prompt,
        IntentDecision(
            kind="read",
            read_plan=({"toolId": "list_customer_accounts", "arguments": {}},),
            answer_goal="Summarise casey's accounts and recent activity.",
            subject_hints={"customer": "casey"},
        ),
    )

    assert _terminal(frames) == "completed", f"{prompt}: {_error_code(frames)}"
    calls = [f["payload"] for f in frames if f["kind"] == "tool.started"]
    assert [c["args"] for c in calls] == [{"userId": "usr_casey"}], f"{prompt}: called with {calls!r}"


async def test_a_username_smuggled_into_an_id_field_is_replaced_by_the_resolved_id():
    """Danny §3.1: hints are strings to MATCH, never identifiers to USE.

    This was the quieter half of the same defect and the more dangerous one. A model that put
    "casey" in `userId` passed schema validation — the manifest pattern happily accepts a
    username — and the harness then called the account service with it verbatim. The run
    reported `completed`. Nothing anywhere said an identifier had been taken from the model.
    """
    prompt = PROMPTS["summary"]

    frames, _authority, _store = await _run_prompt(
        prompt,
        IntentDecision(
            kind="read",
            read_plan=({"toolId": "list_customer_accounts", "arguments": {"userId": "casey"}},),
            answer_goal="Summarise casey's accounts and recent activity.",
            subject_hints={"customer": "casey"},
        ),
    )

    calls = [f["payload"]["args"] for f in frames if f["kind"] == "tool.started"]
    assert calls == [{"userId": "usr_casey"}], f"{prompt}: the model's own id was used: {calls!r}"


async def test_a_read_plan_with_no_hint_to_resolve_is_left_exactly_as_the_model_planned_it():
    """The injection must not become a silent rewriter of arguments nobody resolved."""
    prompt = PROMPTS["compare"]

    frames, _authority, _store = await _run_prompt(prompt, _COMPARE_READ_PLAN)

    calls = [f["payload"]["args"] for f in frames if f["kind"] == "tool.started"]
    assert calls == [
        {"username": "dana"},
        {"username": "casey"},
        {"accountId": "acct_dana_checking"},
        {"accountId": "acct_casey_checking"},
    ], f"{prompt}: arguments were rewritten: {calls!r}"


@pytest.mark.parametrize(
    ("name", "decision", "required_tool"),
    [
        (
            "retail_refund",
            IntentDecision(
                kind="propose",
                action_id="account.balance.adjust",
                subject_hints={"customer": "retail", "accountType": "Checking"},
                payload_draft={"amount": "35", "direction": "credit", "reason": "Goodwill overdraft fee refund."},
            ),
            "get_account",
        ),
        (
            "unlock",
            IntentDecision(
                kind="propose",
                action_id="user.unlock",
                subject_hints={"customer": "verify-target"},
                payload_draft={"reason": "Lockout caused by a stale saved password."},
            ),
            "get_user",
        ),
    ],
)
async def test_authority_sees_bare_tool_ids_carrying_raw_tool_results(
    name: str, decision: IntentDecision, required_tool: str
):
    _frames, authority, _store = await _run_prompt(PROMPTS[name], decision)

    assert authority.propose_calls, f"{name}: no proposal was made"
    evidence = authority.propose_calls[0]["evidence"]
    assert all("#" not in key for key in evidence), f"{name}: per-invocation key reached authority: {sorted(evidence)}"
    # Raw result, not the self-describing bundle entry the CARD gets. A wrapped value would pass
    # `EvidenceComplete`'s key lookup and then fail its requiredFields check on every run.
    assert "data" not in evidence[required_tool], f"{name}: authority received a wrapped entry"


async def test_a_propose_run_binds_later_reads_from_the_payloads_subject_not_a_tools():
    """Why the facts guard is scoped to multi-subject READ plans and not switched on everywhere.

    `_bind_arguments` layers facts OVER the payload, so a fact could in principle steer a later
    read at a different subject. On a propose path it cannot: facts are seeded from the payload
    before any tool runs, and the merge is first-writer-wins, so a tool result can ADD keys but
    can never displace the subject the human is being asked to sign for. This pins that, because
    if either half of it changed the default would quietly become unsafe.
    """
    prompt = PROMPTS["retail_refund"]
    request = _blank_request(prompt)

    _frames, authority, _store = await _run_prompt(
        prompt,
        IntentDecision(
            kind="propose",
            action_id="account.balance.adjust",
            subject_hints={"customer": "retail", "accountType": "Checking"},
            payload_draft={"amount": "35", "direction": "credit", "reason": "Goodwill overdraft fee refund."},
        ),
        request=request,
    )

    payload = authority.propose_calls[0]["payload"]
    assert request.facts["accountId"] == payload["accountId"]
    assert request.facts["amount"] == payload["amount"]


def test_the_rejected_argument_log_states_the_shape_and_never_the_values():
    """The refusal named the tool and not the offending shape, which made the cloud failure
    undiagnosable from logs. The diagnostic must not become a disclosure channel: an argument
    value on a read tool is a customer identifier, or the words a banker typed about one."""
    from app.planner.loop import _argument_shape

    shape = _argument_shape({"userId": "usr_casey", "limit": 5, "flags": ["a"], "note": None, "deep": {"x": 1}})

    assert shape == {"userId": "string", "limit": "number", "flags": "array", "note": "null", "deep": "object"}
    assert "usr_casey" not in str(shape)


def test_evidence_keys_are_bare_first_then_the_next_ordinal():
    from app.planner.loop import _evidence_key

    evidence: dict[str, Any] = {}
    for expected in ("t", "t#2", "t#3"):
        key = _evidence_key(evidence, "t")
        assert key == expected
        evidence[key] = {}


def test_authority_projection_carries_the_first_invocation_of_a_repeated_tool():
    from app.planner.loop import _evidence_for_authority

    evidence = {"t": {"n": 1}, "t#2": {"n": 2}, "resolved_subject": {"basis": "lookup"}}
    meta = {"t": {"toolId": "t"}, "t#2": {"toolId": "t"}}

    assert _evidence_for_authority(evidence, meta) == {"t": {"n": 1}, "resolved_subject": {"basis": "lookup"}}


def test_a_single_subject_read_plan_still_merges_facts():
    """The guard must not be a blanket switch-off — most runs depend on this merge."""
    from app.planner.loop import _read_plan_spans_two_subjects

    assert not _read_plan_spans_two_subjects(
        [
            {"toolId": "lookup_customer", "arguments": {"username": "casey"}},
            {"toolId": "list_account_transactions", "arguments": {"accountId": "acct_casey_checking"}},
        ]
    )
    assert _read_plan_spans_two_subjects(
        [
            {"toolId": "lookup_customer", "arguments": {"username": "dana"}},
            {"toolId": "lookup_customer", "arguments": {"username": "casey"}},
        ]
    )
    assert _read_plan_spans_two_subjects(
        [
            {"toolId": "get_account", "arguments": {"accountId": "acct_dana_checking"}},
            {"toolId": "list_account_transactions", "arguments": {"accountId": "acct_casey_checking"}},
        ]
    )


@pytest.mark.parametrize(
    ("name", "decision", "expected_rung", "expected_payload", "expected_escalators"),
    [
        (
            # Brian's ruling, 2026-09-10: refunding a fee is money going BACK to the customer,
            # so it is a credit, and `credit-adjustment` in config/authority-policy.yaml raises
            # any credit to L2 because crediting an account creates money. This case was mapped
            # as a debit against an L1 heading in the demo doc; the heading was the error. The
            # rung is the point of the case: an L1 refund would route a customer refund through
            # less signature ceremony than crediting money deserves.
            "retail_refund",
            IntentDecision(
                kind="propose",
                action_id="account.balance.adjust",
                subject_hints={"customer": "retail", "accountType": "Checking"},
                payload_draft={"amount": "35", "direction": "credit", "reason": "Goodwill overdraft fee refund."},
            ),
            "L2",
            {"accountId": "acct_retail_checking", "amount": "35.00", "direction": "credit", "reason": "Goodwill overdraft fee refund."},
            {"credit-adjustment"},
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


async def test_demo_score_override_exact_sentence_refuses_payload_unfillable():
    """Danny's ruling B4: the utterance is CUT from the bar, and the refusal is the test.

    The sentence gives no transaction id, and the only list tool in the risk plane returns
    `FlaggedTransaction`, which carries neither a `userId` nor a `description` — so nothing the
    harness can reach can be matched on "offshore wire" at all. Resolving it would mean a new
    subject-scoped read capability in the risk plane, and a model choosing which transaction a
    money-affecting action applies to, which §1.4 forbids outright.

    Half of the old xfail's reason was also stale: the missing *target score* was solved and
    shipped — the two tests above propose `0.30` in band and refuse `0.10` below the floor.

    So the behaviour today is already correct and only the assertion was wrong. The prompt stays
    in the demo doc, marked as a refusal case, and this test pins the honest triple: terminal
    `failed`, a NAMED code, and no authority call. A refusal that reached authority, or one that
    reported success with an empty bundle, would both fail here.
    """
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

    assert _terminal(frames) == "failed", f"{prompt}: must not report success"
    assert _error_code(frames) == "payload_unfillable", f"{prompt}: got {_error_code(frames)}"
    assert authority.propose_calls == [], f"{prompt}: an unfillable payload must never reach authority"


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
                payload_draft={"amount": "35", "direction": "credit", "reason": "Goodwill overdraft fee refund."},
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

    # The refusal must OUTLIVE the process. `run.error` is a stream frame and the replay backlog
    # is in memory, so before this artifact existed a banker who came back after a pod roll saw
    # a run that had failed with no stated reason — the system declined and then forgot why.
    refusals = [a for a in store.artifacts if a.kind == "refusal"]
    assert len(refusals) == 1, f"{prompt}: expected exactly one durable refusal record, got {[a.kind for a in store.artifacts]}"
    assert expected_code in refusals[0].content, f"{prompt}: the durable record does not name the reason code"
    assert refusals[0].content.splitlines()[0].strip(), f"{prompt}: the durable record has no banker-readable explanation"


@pytest.mark.parametrize(
    ("prompt", "decision"),
    [
        (
            "Reset casey's password so she can sign in",
            IntentDecision(kind="propose", action_id="user.password.reset", subject_hints={"customer": "casey"}, payload_draft={}),
        ),
    ],
)
async def test_demo_refusal_record_is_persisted_before_it_is_streamed(prompt: str, decision: IntentDecision):
    """Same rule the evidence bundle follows: what the banker can see, the banker can retrieve.

    An artifact announced on the stream but not yet stored is a pane that renders empty after a
    reload, and nothing distinguishes that from "there were no artifacts".
    """
    frames, _authority, store = await _run_prompt(prompt, decision)

    assert [a.kind for a in store.artifacts] == ["refusal"]
    kinds = [frame["kind"] for frame in frames]
    assert kinds.index("artifact.created") < kinds.index("run.error"), (
        "the refusal record must be emitted before the error frame that references it"
    )
    created = [f for f in frames if f["kind"] == "artifact.created"][0]["payload"]
    assert created["kind"] == "refusal"
    assert created["title"] == "Why this was declined"
    # A string body renders as prose in the canvas; a mapping renders as a JSON block in front
    # of the person the refusal is meant to explain itself to.
    assert isinstance(created["content"], str)


async def test_step_titles_shown_to_a_banker_are_not_developer_vocabulary():
    """Titles are server-authored and reach the banker unchanged.

    The client deliberately does not remap them — presentation knowledge of backend vocabulary
    in the client is exactly what was rejected for evidence labels — so the words are fixed
    here, at the only place they are written.
    """
    frames, _authority, _store = await _run_prompt(
        PROMPTS["retail_refund"],
        IntentDecision(
            kind="propose",
            action_id="account.balance.adjust",
            subject_hints={"customer": "retail", "accountType": "Checking"},
            payload_draft={"amount": "35", "direction": "credit", "reason": "Goodwill overdraft fee refund."},
        ),
    )

    titles = [
        step["title"]
        for frame in frames
        if frame["kind"] in {"plan.created", "plan.revised"}
        for step in frame["payload"].get("steps", [])
    ]
    assert "Identify the customer and account" in titles, titles
    assert "Check the action is permitted and complete" in titles, titles
    assert "Resolve references" not in titles
    assert "Validate proposed action and payload" not in titles


async def test_a_credit_adjustment_gathers_both_required_reads_before_proposing():
    """`requiredEvidence: [get_account, list_account_transactions]` is a precondition, not a label.

    Brian asked whether the plan actually performs both reads for the refund prompt. It does,
    and this pins it offline so the answer cannot quietly change: a proposal that reaches
    authority without the evidence the policy demands is a proposal built on proof nobody
    gathered. The catalogue fetch that supplies this list is the one that used to fail silently
    to an empty list — see `test_authority_catalogue_availability.py` — which is exactly how a
    run could have arrived here with neither read performed and nothing saying so.
    """
    prompt = PROMPTS["retail_refund"]

    _frames, authority, _store = await _run_prompt(
        prompt,
        IntentDecision(
            kind="propose",
            action_id="account.balance.adjust",
            subject_hints={"customer": "retail", "accountType": "Checking"},
            payload_draft={"amount": "35", "direction": "credit", "reason": "Goodwill overdraft fee refund."},
        ),
    )

    assert authority.propose_calls, f"{prompt}: no proposal was made"
    gathered = set(authority.propose_calls[0]["evidence"])
    assert {"get_account", "list_account_transactions"} <= gathered, (
        f"{prompt}: proposed on {sorted(gathered)}, missing a read the policy requires"
    )
