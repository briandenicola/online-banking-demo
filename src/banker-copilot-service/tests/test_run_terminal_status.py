"""The run's terminal status must describe what the run actually achieved.

`run_6f19b2eb4ec54a20` refused a non-canonical `amount`, emitted
``run.error {code: payload_not_canonicalizable, recoverable: false}``, produced no approval —
and then emitted ``step.completed`` for the step that had just failed and
``run.done status: "completed"``. Failure wearing the costume of success, on the one field a
harness, a dashboard or a demo narration trusts first.

The tool-failure path reported ``failed`` correctly, so this was never "runs always say
completed": one terminal path was reasoned about in isolation. These tests hold every terminal
path at once, so the next one added cannot quietly inherit success.

**Every assertion here is downstream of the real terminal path.** Each test drives the actual
``Planner.run`` against a real ``RunStream`` and reads the ``run.done`` frame the planner
emitted. Nothing asserts on a status a fixture handed it — that failure mode (a guard that
holds nothing, because the call site it guards was never exercised) has bitten this repo, and
this file, before.
"""

from __future__ import annotations

from typing import Any

import pytest

from conftest import judging_assessor, shipped_assessment_limits

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.intent_model import EvidenceAnswer, IntentDecision
from app.planner.loop import Planner, PlannerRequest
from app.tools.executor import ToolInvocationError
from app.tools.propose import ProposeRejected

from tests.conftest import make_token

#: The fakes never inspect it; it exists only to satisfy the request shape.
_FAKE_TOKEN = "opaque-test-value"

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ------------------------------------------------------------------- fakes ----


class _FakeResult:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.duration_ms = 1

    def summary(self) -> str:
        return "ok"


class _FakeTool:
    def __init__(self, tool_id: str, params: tuple[str, ...], scope: str = "risk.read") -> None:
        self.tool_id = tool_id
        self.capability_scope = scope
        self.parameters = {
            "type": "object",
            "properties": {p: {"type": "string"} for p in params},
            "required": list(params),
            "additionalProperties": False,
        }


class _FakeRegistry:
    def __init__(self, tool_ids: tuple[str, ...]) -> None:
        self._tools = {t: _FakeTool(t, ("transactionId",)) for t in tool_ids}
        if "get_user" in tool_ids:
            self._tools["get_user"] = _FakeTool("get_user", ("userId",), "identity.read")
        if "lookup_customer" in tool_ids:
            self._tools["lookup_customer"] = _FakeTool("lookup_customer", ("username",), "customer-directory.read")
        if "get_account" in tool_ids:
            self._tools["get_account"] = _FakeTool("get_account", ("accountId",), "accounts.read")
        if "list_customer_accounts" in tool_ids:
            self._tools["list_customer_accounts"] = _FakeTool("list_customer_accounts", ("userId",), "accounts.read")

    @property
    def tool_ids(self):
        return frozenset(self._tools)

    def get(self, tool_id: str):
        return self._tools.get(tool_id)


class _Executor:
    """Returns evidence, or raises the way the real executor does on a 403."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def invoke(self, tool_id: str, arguments: dict[str, Any], bearer: str) -> _FakeResult:
        if self.fail:
            raise ToolInvocationError("upstream_forbidden", "account-service returned 403")
        if tool_id == "get_user":
            return _FakeResult({"id": arguments["userId"], "username": "casey", "firstName": "Casey", "lastName": "Retail"})
        if tool_id == "lookup_customer":
            return _FakeResult({"query": arguments["username"], "count": 1, "matches": [{"id": "usr_casey", "username": "casey", "displayName": "Casey Retail"}]})
        if tool_id == "get_account":
            return _FakeResult({"id": arguments["accountId"], "accountId": arguments["accountId"], "userId": "usr_casey", "accountType": "Checking"})
        if tool_id == "list_customer_accounts":
            # Every account these tests name belongs to the resolved customer. Ownership is
            # not what they are about — they pin that an identifier-shaped hint is LOOKED UP
            # rather than used — so the fixture grants ownership and leaves that point intact.
            # The cross-customer case has its own suite in test_account_ownership_binding.py.
            return _FakeResult({
                "userId": arguments["userId"],
                "count": 3,
                "accounts": [
                    {"id": acct, "accountId": acct, "userId": arguments["userId"], "accountNumber": number, "accountType": "Checking"}
                    for acct, number in (("acc_1", "1001"), ("acc_checking_casey", "1002"), ("acct_casey_checking", "1003"))
                ],
            })
        return _FakeResult({"transactionId": "tx_1", "amount": "245.00"})


class _Outcome:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body

    @property
    def admitted(self) -> bool:
        return self.status_code in (200, 201)


ADMITTED_BODY = {
    "id": "apr_1",
    "status": "pending",
    "requiredRung": "L1",
    "policyVersion": "pv1:abcd",
    "agentAssessment": {"summary": "reviewed", "recommendation": "proceed"},
}


class _Authority:
    """Stands in for authority-service. ``propose_behaviour`` picks which path is exercised."""

    def __init__(self, propose_behaviour: str = "admit", evidence: tuple[str, ...] = ()) -> None:
        self.propose_behaviour = propose_behaviour
        self.evidence = list(evidence)
        self.propose_calls = 0
        self.last_body = None

    async def policy_catalogue(self, bearer_token: str):
        return {
            "actions": [
                {
                    "id": "account.balance.adjust",
                    "displayName": "Post a balance adjustment",
                    "baseRung": "L1",
                    "agentMayPropose": True,
                    "requiredEvidence": self.evidence,
                    "hashFields": ["accountId", "amount", "direction", "reason"],
                    "moneyFields": ["amount"],
                }
            ]
        }

    async def propose(self, body, *, bearer_token, session_id, agent_id, correlation_id):
        self.propose_calls += 1
        self.last_body = body
        if self.propose_behaviour == "unrecoverable":
            # Exactly what run_6f19b2eb4ec54a20 hit: refused inside this service, before
            # anything left it, because `amount` was a JSON number with a fractional part.
            raise ProposeRejected(
                "payload_not_canonicalizable",
                "Money field 'amount' is a JSON number with a fractional part.",
            )
        if self.propose_behaviour == "recoverable":
            return _Outcome(422, {"error": "evidence_incomplete", "message": "missing evidence"})
        return _Outcome(201, dict(ADMITTED_BODY))


class _Store:
    async def save_artifact(self, artifact):
        return None


class _Session:
    id = "sess_1"
    context: dict[str, Any] = {}
    actor_id = "usr_banker_44"
    actor_username = "banker@example.com"
    capabilities = ("risk.read", "identity.read", "customer-directory.read", "accounts.read")


async def _drive(
    *,
    authority: _Authority,
    executor: _Executor,
    evidence_tools: tuple[str, ...] = (),
    action_id: str | None = "account.balance.adjust",
    intent_selector=None,
    answerer=None,
    objective: str = "Propose account.balance.adjust for human signature",
) -> list[dict[str, Any]]:
    """Run the REAL planner and return the frames it actually emitted."""
    registry = _FakeRegistry(evidence_tools)
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    planner = Planner(
        registry=registry,
        executor=executor,
        authority=authority,
        max_iterations=12,
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
        intent_selector=intent_selector,
        answerer=answerer,
        store=_Store(),
    )
    request = PlannerRequest(
        session=_Session(),
        run_id="run_under_test",
        objective=objective,
        action_id=action_id,
        payload={"amount": "245.00", "accountId": "acc_1"},
        facts={"transactionId": "tx_1"},
        bearer_token=_FAKE_TOKEN,
    )
    stream = runs.create("run_under_test", "sess_1")
    await planner.run(request, stream)
    return runs.sink._frames["run_under_test"]  # type: ignore[attr-defined]


def _terminal(frames: list[dict[str, Any]]) -> str:
    done = [f for f in frames if f["kind"] == "run.done"]
    assert len(done) == 1, "a run emits exactly one terminal frame"
    return done[0]["payload"]["status"]


def _kinds(frames: list[dict[str, Any]]) -> list[str]:
    return [f["kind"] for f in frames]


# --------------------------------------------------------- one per path ----


async def test_tool_failure_reports_failed():
    """The path that was already correct. Held so the fix cannot regress it."""
    frames = await _drive(
        authority=_Authority("admit", evidence=("get_flagged_transaction",)),
        executor=_Executor(fail=True),
        evidence_tools=("get_flagged_transaction",),
    )

    assert "tool.failed" in _kinds(frames)
    assert "step.failed" in _kinds(frames)
    assert "approval.required" not in _kinds(frames)
    assert _terminal(frames) == "failed"


async def test_unrecoverable_propose_failure_reports_failed():
    """The defect. A refused proposal produced no approval, so the run did not succeed."""
    authority = _Authority("unrecoverable")
    frames = await _drive(authority=authority, executor=_Executor())

    assert authority.propose_calls == 1, "the propose path must actually have been taken"

    errors = [f for f in frames if f["kind"] == "run.error"]
    assert [e["payload"]["code"] for e in errors] == ["payload_not_canonicalizable"]
    assert errors[0]["payload"]["recoverable"] is False

    assert "approval.required" not in _kinds(frames)
    assert _terminal(frames) == "failed"


async def test_unrecoverable_propose_failure_does_not_complete_its_step():
    """The step exists to produce an approval. It produced none, so it did not complete.

    This is the specific frame the live trace got wrong: seq 16 was
    ``step.completed {stepId: step_4}`` for the step whose failure was recorded at seq 15.
    """
    frames = await _drive(authority=_Authority("unrecoverable"), executor=_Executor())

    propose_step = next(
        s["id"]
        for s in next(f for f in frames if f["kind"] == "plan.proposed")["payload"]["steps"]
        if s["kind"] == "propose"
    )
    completed = [f for f in frames if f["kind"] == "step.completed"]
    failed = [f for f in frames if f["kind"] == "step.failed"]

    assert propose_step not in [f["payload"]["stepId"] for f in completed]
    assert [f["payload"]["stepId"] for f in failed] == [propose_step]
    assert failed[0]["payload"]["error"] == "payload_not_canonicalizable"
    # `willRetry` describes what the planner will actually do, not what the error permits.
    assert failed[0]["payload"]["willRetry"] is False


async def test_recoverable_refusal_still_fails_the_run_but_keeps_the_flag():
    """A recoverable error nobody recovered from is still a run with no proposal in it.

    The status turns on what was ACHIEVED, not on how forgiving the error was — reading it
    off `recoverable` would rebuild the same bug one field over. The distinction survives
    where it is actionable: on the `run.error` frame.
    """
    frames = await _drive(authority=_Authority("recoverable"), executor=_Executor())

    error = next(f for f in frames if f["kind"] == "run.error")
    assert error["payload"]["recoverable"] is True, "the 422 distinction must not be erased"
    assert "approval.required" not in _kinds(frames)
    assert _terminal(frames) == "failed"


async def test_successful_propose_reports_completed():
    """The fix must not turn every run into a failure — success is still reachable."""
    frames = await _drive(
        authority=_Authority("admit", evidence=("get_flagged_transaction",)),
        executor=_Executor(),
        evidence_tools=("get_flagged_transaction",),
    )

    assert "approval.required" in _kinds(frames)
    assert "step.failed" not in _kinds(frames)
    assert _terminal(frames) == "completed"


async def test_evidence_only_run_completes_without_an_approval():
    """A read-only free-text intent gathers evidence and answers without an approval."""

    async def selector(*_args, **_kwargs):
        return IntentDecision(
            kind="read",
            read_plan=({"toolId": "get_flagged_transaction", "arguments": {"transactionId": "tx_1"}},),
            answer_goal="Explain the flagged transaction.",
        )

    async def answerer(*_args, **_kwargs):
        return EvidenceAnswer(
            answer="The wire was flagged because its amount is unusual.",
            key_points=({"label": "large flagged wire", "citedEvidenceIds": ["get_flagged_transaction"]},),
            cited_evidence_ids=("get_flagged_transaction",),
        )

    frames = await _drive(
        authority=_Authority("admit", evidence=("get_flagged_transaction",)),
        executor=_Executor(),
        evidence_tools=("get_flagged_transaction",),
        action_id=None,
        intent_selector=selector,
        answerer=answerer,
        objective="Why was tx_1 flagged?",
    )

    assert "approval.required" not in _kinds(frames)
    assert "tool.started" in _kinds(frames)
    assert "artifact.created" in _kinds(frames)
    assert _terminal(frames) == "completed"


async def test_free_text_without_intent_model_fails_loudly_not_empty_success():
    frames = await _drive(
        authority=_Authority("admit"),
        executor=_Executor(),
        action_id=None,
    )

    error = next(f for f in frames if f["kind"] == "run.error")
    assert error["payload"]["code"] == "planner_model_unavailable"
    assert "approval.required" not in _kinds(frames)
    assert _terminal(frames) == "failed"


async def test_free_text_propose_path_selects_action_validates_payload_and_proposes():
    async def selector(*_args, **_kwargs):
        return IntentDecision(
            kind="propose",
            action_id="account.balance.adjust",
            payload_draft={
                "accountId": "acc_1",
                "amount": "35",
                "direction": "credit",
                "reason": "Goodwill overdraft fee refund.",
                "ignoredByServer": "not forwarded",
            },
        )

    authority = _Authority("admit", evidence=("get_flagged_transaction",))
    frames = await _drive(
        authority=authority,
        executor=_Executor(),
        evidence_tools=("get_flagged_transaction", "get_account", "list_customer_accounts"),
        action_id=None,
        intent_selector=selector,
        answerer=None,
        objective="Refund $35 on acc_1.",
    )

    assert authority.propose_calls == 1
    assert authority.last_body["payload"] == {
        "accountId": "acc_1",
        "amount": "35.00",
        "direction": "credit",
        "reason": "Goodwill overdraft fee refund.",
    }
    assert "approval.required" in _kinds(frames)
    assert _terminal(frames) == "completed"


async def test_free_text_identifier_shaped_customer_hint_is_resolved_not_passed_through():
    class RecordingExecutor(_Executor):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def invoke(self, tool_id: str, arguments: dict[str, Any], bearer: str) -> _FakeResult:
            self.calls.append((tool_id, dict(arguments)))
            return await super().invoke(tool_id, arguments, bearer)

    async def selector(*_args, **_kwargs):
        return IntentDecision(
            kind="propose",
            action_id="account.balance.adjust",
            subject_hints={"userId": "9f6a6d1e-1111-4444-aaaa-555555555555"},
            payload_draft={
                "accountId": "acc_1",
                "amount": "35",
                "direction": "credit",
                "reason": "Goodwill overdraft fee refund.",
            },
        )

    executor = RecordingExecutor()
    authority = _Authority("admit")
    frames = await _drive(
        authority=authority,
        executor=executor,
        evidence_tools=("get_user", "get_account", "list_customer_accounts"),
        action_id=None,
        intent_selector=selector,
    )

    assert ("get_user", {"userId": "9f6a6d1e-1111-4444-aaaa-555555555555"}) in executor.calls
    assert authority.last_body["payload"]["accountId"] == "acc_1"
    artifacts = [f["payload"]["content"] for f in frames if f["kind"] == "artifact.created"]
    assert any("resolved_subject" in artifact for artifact in artifacts)
    assert _terminal(frames) == "completed"


async def test_free_text_guid_subject_hint_is_looked_up_before_payload_use():
    guid = "9f6a6d1e-1111-4444-aaaa-555555555555"

    class RecordingExecutor(_Executor):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def invoke(self, tool_id: str, arguments: dict[str, Any], bearer: str) -> _FakeResult:
            self.calls.append((tool_id, dict(arguments)))
            if tool_id == "get_user":
                return _FakeResult({"id": "usr_verified", "username": "verified"})
            return await super().invoke(tool_id, arguments, bearer)

    async def selector(*_args, **_kwargs):
        return IntentDecision(
            kind="propose",
            action_id="account.balance.adjust",
            subject_hints={"userId": guid},
            payload_draft={
                "userId": guid,
                "accountId": "acc_1",
                "amount": "35",
                "direction": "credit",
                "reason": "Goodwill overdraft fee refund.",
            },
        )

    executor = RecordingExecutor()
    authority = _Authority("admit")
    frames = await _drive(
        authority=authority,
        executor=executor,
        evidence_tools=("get_user", "get_account", "list_customer_accounts"),
        action_id=None,
        intent_selector=selector,
    )

    assert ("get_user", {"userId": guid}) in executor.calls
    assert authority.propose_calls == 1
    artifacts = [f["payload"]["content"] for f in frames if f["kind"] == "artifact.created"]
    resolved = next(a["resolved_subject"] for a in artifacts if "resolved_subject" in a)
    assert resolved["matched"]["userId"] == "usr_verified"
    assert _terminal(frames) == "completed"


@pytest.mark.parametrize(
    "executor_error",
    [
        ToolInvocationError("upstream_not_found", "user-service returned 404"),
        ToolInvocationError("upstream_forbidden", "user-service returned 403"),
    ],
)
async def test_free_text_guid_subject_hint_refuses_when_lookup_cannot_verify_identity(executor_error):
    guid = "9f6a6d1e-1111-4444-aaaa-555555555555"

    class DenyingExecutor(_Executor):
        async def invoke(self, tool_id: str, arguments: dict[str, Any], bearer: str) -> _FakeResult:
            if tool_id == "get_user":
                raise executor_error
            return await super().invoke(tool_id, arguments, bearer)

    async def selector(*_args, **_kwargs):
        return IntentDecision(
            kind="propose",
            action_id="account.balance.adjust",
            subject_hints={"userId": guid},
            payload_draft={
                "userId": guid,
                "accountId": "acc_1",
                "amount": "35",
                "direction": "credit",
                "reason": "Goodwill overdraft fee refund.",
            },
        )

    authority = _Authority("admit")
    frames = await _drive(
        authority=authority,
        executor=DenyingExecutor(),
        evidence_tools=("get_user", "get_account", "list_customer_accounts"),
        action_id=None,
        intent_selector=selector,
    )

    assert authority.propose_calls == 0
    assert "approval.required" not in _kinds(frames)
    error = next(f for f in frames if f["kind"] == "run.error")
    assert error["payload"]["code"] == "subject_not_found"
    assert error["payload"]["message"] == "The referenced customer could not be resolved for this banker."
    assert "403" not in error["payload"]["message"]
    assert "404" not in error["payload"]["message"]
    assert "forbidden" not in error["payload"]["message"].lower()
    assert "not found" not in error["payload"]["message"].lower()
    assert guid not in error["payload"]["message"]
    assert _terminal(frames) == "failed"


async def test_free_text_known_l3_action_is_refused_before_propose():
    async def selector(*_args, **_kwargs):
        return IntentDecision(kind="propose", action_id="user.delete", payload_draft={"userId": "usr_1"})

    class _AuthorityWithForbidden(_Authority):
        async def policy_catalogue(self, bearer_token: str):
            body = await super().policy_catalogue(bearer_token)
            body["actions"].append(
                {
                    "id": "user.delete",
                    "displayName": "Delete a user",
                    "baseRung": "L3",
                    "agentMayPropose": False,
                    "requiredEvidence": [],
                    "hashFields": ["userId"],
                    "moneyFields": [],
                }
            )
            return body

    authority = _AuthorityWithForbidden("admit")
    frames = await _drive(
        authority=authority,
        executor=_Executor(),
        action_id=None,
        intent_selector=selector,
    )

    assert authority.propose_calls == 0
    error = next(f for f in frames if f["kind"] == "run.error")
    assert error["payload"]["code"] == "forbidden_action"
    assert "approval.required" not in _kinds(frames)
    assert _terminal(frames) == "failed"


async def test_free_text_unfillable_payload_is_refused_before_propose():
    async def selector(*_args, **_kwargs):
        return IntentDecision(
            kind="propose",
            action_id="account.balance.adjust",
            payload_draft={"accountId": "acc_1", "amount": "35.00", "direction": "credit"},
        )

    authority = _Authority("admit")
    frames = await _drive(
        authority=authority,
        executor=_Executor(),
        evidence_tools=("get_account",),
        action_id=None,
        intent_selector=selector,
    )

    assert authority.propose_calls == 0
    error = next(f for f in frames if f["kind"] == "run.error")
    assert error["payload"]["code"] == "payload_unfillable"
    assert "reason" in error["payload"]["message"]
    assert _terminal(frames) == "failed"


async def test_free_text_noncanonical_money_is_refused_before_propose():
    async def selector(*_args, **_kwargs):
        return IntentDecision(
            kind="propose",
            action_id="account.balance.adjust",
            payload_draft={
                "accountId": "acc_1",
                "amount": 35.125,
                "direction": "credit",
                "reason": "Goodwill refund.",
            },
        )

    authority = _Authority("admit")
    frames = await _drive(
        authority=authority,
        executor=_Executor(),
        evidence_tools=("get_account",),
        action_id=None,
        intent_selector=selector,
    )

    assert authority.propose_calls == 0
    error = next(f for f in frames if f["kind"] == "run.error")
    assert error["payload"]["code"] == "payload_invalid"
    assert _terminal(frames) == "failed"


async def test_planner_exception_reports_failed():
    """An unhandled error is not a completed run either."""

    class _Exploding(_Authority):
        async def policy_catalogue(self, bearer_token: str):
            raise RuntimeError("authority-service unreachable")

    frames = await _drive(authority=_Exploding("admit"), executor=_Executor())

    assert next(f for f in frames if f["kind"] == "run.error")["payload"]["code"] == "planner_error"
    assert _terminal(frames) == "failed"


async def test_evidence_only_run_that_raises_reports_failed():
    """Holds `_RunOutcome.aborted` directly — nothing else does.

    Tamper-testing found this gap. `test_tool_failure_reports_failed` and
    `test_planner_exception_reports_failed` both pass even with the abort flag removed,
    because those runs also expect a proposal they never reach, so the "expected an approval,
    produced none" clause carries them. The flag itself was unheld by anything.

    The reachable path is a run with no `action_id` — nothing expects an approval, so that
    clause cannot help — that then blows up mid-plan. Here the artifact store fails, so the
    banker's evidence bundle was never persisted. Without the flag the run reports
    `completed` having saved nothing: the same lie in a quieter corner.
    """

    class _BrokenStore:
        async def save_artifact(self, artifact):
            raise RuntimeError("cosmos write rejected")

    registry = _FakeRegistry(())
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    planner = Planner(
        registry=registry,
        executor=_Executor(),
        authority=_Authority("admit"),
        max_iterations=12,
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
        store=_BrokenStore(),
    )
    request = PlannerRequest(
        session=_Session(),
        run_id="run_z",
        objective="Gather the evidence bundle for acc_11",
        action_id=None,
        payload={},
        facts={},
        bearer_token=_FAKE_TOKEN,
    )
    stream = runs.create("run_z", "sess_1")
    await planner.run(request, stream)
    frames = runs.sink._frames["run_z"]  # type: ignore[attr-defined]

    assert "artifact.created" not in _kinds(frames), "nothing was persisted"
    assert _terminal(frames) == "failed"


# ------------------------------------------- the second reporting surface ----


async def test_persisted_run_status_mirrors_the_trace_verdict():
    """`GET /runs/{id}` must not hold a second, independent opinion of how the run went.

    The route used to hardcode `completed` in a `finally`, so the REST status said
    `completed` even for a run whose trace said `failed` — and even for a planner that
    raised before emitting any terminal frame at all.
    """
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    stream = runs.create("run_x", "sess_1")

    assert stream.terminal_status is None, "nothing achieved until the planner says so"

    await stream.emit("run.done", {"status": "failed", "finalSeq": 1})
    assert stream.terminal_status == "failed"


async def test_terminal_status_is_taken_from_the_real_planner_frame():
    """Ties the stream's recorded verdict to the planner that produced it."""
    registry = _FakeRegistry(())
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    planner = Planner(
        registry=registry,
        executor=_Executor(),
        authority=_Authority("unrecoverable"),
        max_iterations=12,
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
        store=_Store(),
    )
    request = PlannerRequest(
        session=_Session(),
        run_id="run_y",
        objective="Propose account.balance.adjust for human signature",
        action_id="account.balance.adjust",
        payload={"amount": 245.00},
        facts={},
        bearer_token=_FAKE_TOKEN,
    )
    stream = runs.create("run_y", "sess_1")
    await planner.run(request, stream)

    # This is the value `start_run`'s `finally` block now writes to `run.status`.
    assert stream.terminal_status == "failed"


def test_rest_run_status_reports_failed_for_a_refused_proposal():
    """End-to-end through the ROUTE, not the stream.

    The two tests above assert on `RunStream.terminal_status`; on their own they would stay
    green if somebody reverted `start_run`'s `finally` block back to a hardcoded "completed",
    because nothing would hold that call site. This test goes through the real HTTP path —
    start a run whose proposal authority-service refuses with a 422, then read the run back
    the way a harness or dashboard does — so the assertion is downstream of the route.
    """
    import importlib

    import httpx
    from fastapi.testclient import TestClient

    import app.main as main_module

    importlib.reload(main_module)

    with TestClient(main_module.app) as client:

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/authority/policy":
                return httpx.Response(
                    200,
                    json={
                        "policyVersion": "pv1:abcd",
                        "actions": [
                            {
                                "id": "transaction.flag.review",
                                "baseRung": "L1",
                                "agentMayPropose": True,
                                "requiredEvidence": [],
                            }
                        ],
                    },
                )
            if path == "/api/authority/approvals":
                # The refusal. No approval is created, so the run achieved nothing.
                return httpx.Response(
                    422,
                    json={"error": "evidence_incomplete", "message": "missing evidence"},
                )
            return httpx.Response(404, json={"error": "not_found"})

        client.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        from app.planner.loop import Planner
        from app.tools.executor import ToolExecutor
        from app.tools.propose import AuthorityClient

        registry = client.app.state.registry
        client.app.state.executor = ToolExecutor(registry, client.app.state.http)
        client.app.state.authority = AuthorityClient(
            "http://authority-service:8080", client.app.state.http, 8000
        )
        client.app.state.planner = Planner(
            registry=registry,
            executor=client.app.state.executor,
            authority=client.app.state.authority,
            max_iterations=12,
            assessment_limits=shipped_assessment_limits(),
            assessor=judging_assessor(),
        )

        headers = {"Authorization": "Bearer " + make_token(effective_roles=["banker"])}
        session = client.post(
            "/api/copilot/sessions",
            json={"objective": "Adjust the balance on acc_11", "context": {"accountId": "acc_11"}},
            headers=headers,
        ).json()
        started = client.post(
            f"/api/copilot/sessions/{session['sessionId']}/runs",
            json={
                "actionId": "transaction.flag.review",
                "payload": {"transactionId": "tx_1", "decision": "cleared"},
                "facts": {},
            },
            headers=headers,
        ).json()

        trace = client.get(
            f"/api/copilot/runs/{started['runId']}/trace", headers=headers
        ).json()["frames"]
        assert [f["kind"] for f in trace][-1] == "run.done"
        assert trace[-1]["payload"]["status"] == "failed"

        # The field a harness polls must agree with the trace it summarises.
        run = client.get(f"/api/copilot/runs/{started['runId']}", headers=headers).json()
        assert run["status"] == "failed"
