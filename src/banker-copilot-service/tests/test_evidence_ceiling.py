"""The evidence ceiling, and the two claims the two-stage measurement rests on (§P5).

This file exists to make two specific things unable to quietly stop being true:

1. **The assessor's prompt is byte-identical at every budget.** Not "similar" — identical. If
   stage 2's prompt invited requesting evidence and stage 1's did not, stage 1 would measure an
   assessment the product never makes, and the staged deploy would be attributing a delta to the
   wrong change. It is asserted here on the actual bytes, because a claim like this stops being
   true silently and a comment cannot notice.

2. **Budget 0 is the loop running zero iterations, not the loop switched off.** There is no
   `if ceiling_enabled:` anywhere. At budget 0 the model is asked, the reply is parsed, the
   requests are recorded and the additions function is CALLED and returns empty. That is checked
   by observing the functions actually run, not by reading the source.

The second one is the direct descendant of a real incident on this service: unwiring
``project(...)`` left all 285 tests green with the entire fix inert. A staging argument that can
be made inert without a test going red is not an argument.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from conftest import judging_assessor, scripted_assessor, shipped_assessment_limits

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.evidence_ceiling import (
    ALREADY_GATHERED,
    BUDGET_EXHAUSTED,
    DISCRETIONARY_QUARANTINE,
    ITERATIONS_EXHAUSTED,
    QUARANTINED,
    UNBINDABLE,
    UNKNOWN_TOOL,
    additional_evidence,
)
from app.planner.limits import AssessmentLimits, AssessmentLimitsError, parse_assessment_limits
from app.planner.loop import Planner, PlannerRequest, _plan_steps, adverse_proposal_mode
from app.planner.primary_model import build_prompt

STAGE_TWO = AssessmentLimits(per_run_additional_tool_budget=3, max_assessment_iterations=2)


# ---------------------------------------------------------------- the harness for a run ----


@dataclass
class _FakeResult:
    data: Any
    duration_ms: int = 1

    def summary(self) -> str:
        return "ok"


class _FakeTool:
    def __init__(self, tool_id: str, params: tuple[str, ...]) -> None:
        self.tool_id = tool_id
        self.parameters = {
            "properties": {p: {"type": "string"} for p in params},
            "required": list(params),
        }


class _FakeRegistry:
    def __init__(self, tools: dict[str, _FakeTool]) -> None:
        self._tools = tools

    @property
    def tool_ids(self):
        return frozenset(self._tools)

    def get(self, tool_id: str):
        return self._tools.get(tool_id)


class _Executor:
    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._failing = failing

    async def invoke(self, tool_id: str, arguments: dict[str, Any], bearer: str) -> _FakeResult:
        self.calls.append((tool_id, dict(arguments)))
        if tool_id in self._failing:
            from app.tools.executor import ToolInvocationError

            raise ToolInvocationError(code="upstream_forbidden", message="403")
        return _FakeResult(data={"tool": tool_id})


class _Outcome:
    def __init__(self, assessment: dict) -> None:
        self.status_code = 201
        self.body = {
            "id": "apr_1",
            "status": "pending",
            "requiredRung": "L1",
            "agentAssessment": assessment,
        }

    @property
    def admitted(self) -> bool:
        return True


class _Authority:
    def __init__(self, required: tuple[str, ...]) -> None:
        self._required = list(required)
        self.proposed: list[dict] = []

    async def policy_catalogue(self, bearer_token: str):
        return {"actions": [{"id": "transaction.hold.place", "requiredEvidence": self._required}]}

    async def propose(self, body, *, bearer_token, session_id, agent_id, correlation_id):
        self.proposed.append(body)
        return _Outcome(body["agentAssessment"])


class _Store:
    async def save_artifact(self, artifact):
        return None


@dataclass
class _Session:
    id: str = "sess_1"
    context: dict[str, Any] = None  # type: ignore[assignment]
    actor_id: str = "usr_banker_1"
    actor_username: str = "banker@example.com"


def _registry() -> _FakeRegistry:
    return _FakeRegistry(
        {
            "get_flagged_transaction": _FakeTool("get_flagged_transaction", ("transactionId",)),
            "list_account_transactions": _FakeTool("list_account_transactions", ("accountId",)),
            "get_customer_profile": _FakeTool("get_customer_profile", ("customerId",)),
            # Registered, and its one parameter can never be bound from the banker's inputs.
            "get_branch_roster": _FakeTool("get_branch_roster", ("branchId",)),
            "list_login_audits": _FakeTool("list_login_audits", ("transactionId",)),
        }
    )


async def _run(assessor, limits, *, required=("get_flagged_transaction",), failing=()):
    registry = _registry()
    executor = _Executor(failing=failing)
    authority = _Authority(required)
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    planner = Planner(
        registry=registry,
        executor=executor,
        authority=authority,
        max_iterations=12,
        assessment_limits=limits,
        assessor=assessor,
        store=_Store(),
    )
    request = PlannerRequest(
        session=_Session(context={"transactionId": "tx_1"}),
        run_id="run_1",
        objective="Place a hold on the flagged wire.",
        action_id="transaction.hold.place",
        payload={"accountId": "acc_1", "customerId": "cus_1"},
        facts={},
        bearer_token="******",
    )
    stream = runs.create("run_1", "sess_1")
    await planner.run(request, stream)
    frames = runs.sink._frames.get("run_1", [])  # type: ignore[attr-defined]
    return frames, authority, executor


def _assessment(authority: _Authority) -> dict:
    return authority.proposed[-1]["agentAssessment"]


# ------------------------------------------------ §P5.1 the byte-identical prompt claim ----


@pytest.mark.asyncio
async def test_the_assessors_prompt_is_byte_identical_at_budget_0_and_budget_3():
    """§P5.1, condition 1. The whole two-stage measurement rests on this one equality.

    The prompt is what makes stage 1 a measurement of the shipping product rather than of a
    configuration nobody runs. Whether a request is HONOURED is the budget's business; whether it
    may be MADE is not, and the prompt must not know which stage it is in.
    """
    stage_one_prompts: list[str] = []
    stage_two_prompts: list[str] = []

    await _run(judging_assessor(seen=stage_one_prompts), shipped_assessment_limits())
    await _run(judging_assessor(seen=stage_two_prompts), STAGE_TWO)

    assert stage_one_prompts, "the assessor was never called — the loop is inert"
    assert stage_one_prompts[0] == stage_two_prompts[0]


def test_the_prompt_never_mentions_the_budget_in_any_form():
    """A weaker but earlier guard than the equality above: even a prompt that interpolated the
    budget identically by accident would be a prompt that COULD differ. It must not be able to."""
    prompt = build_prompt("objective", "transaction.hold.place", {}, {})
    lowered = prompt.casefold()
    for forbidden in ("budget", "at most", "you may request up to", "remaining"):
        assert forbidden not in lowered, f"the assessor's prompt leaks the ceiling: {forbidden!r}"


def test_the_request_channel_is_offered_unconditionally():
    """The primary may always ASK. If stage 2's prompt invited requests and stage 1's did not,
    stage 1 would measure an assessment the product never makes."""
    prompt = build_prompt("objective", "transaction.hold.place", {}, {})
    assert "requestedEvidence" in prompt


def test_no_module_in_the_planner_branches_on_the_budget_being_zero():
    """§P5.1's structural claim, checked against the source rather than trusted.

    The ruling is explicit: *there is no `if ceiling_enabled:`*. A branch would mean stage 1
    exercises a code path stage 2 does not, which is this feature's signature defect.
    """
    import ast
    import pathlib

    planner_dir = pathlib.Path(__file__).resolve().parents[1] / "app" / "planner"
    offenders: list[str] = []
    for path in sorted(planner_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            source = ast.unparse(node.test)
            mentions_budget = "budget" in source or "ceiling" in source.casefold()
            if mentions_budget and path.name != "evidence_ceiling.py":
                offenders.append(f"{path.name}: if {source}")
    assert offenders == [], (
        "a planner module branches on the budget. The budget is a NUMBER that bounds a loop, "
        f"never a switch that selects a code path: {offenders}"
    )


# ------------------------------------------- §P5.1 the budget-0 path is fully traversed ----


@pytest.mark.asyncio
async def test_at_budget_zero_the_model_is_still_asked_and_its_request_is_still_recorded():
    """The stage-1 measurement in one test: the primary asked, was refused, and the refusal is a
    positive stated fact on the record. It is the ONLY place the ceiling's demand is visible at
    budget 0, and it is the evidence for whether 3 is the right cap in stage 2."""
    prompts: list[str] = []
    frames, authority, executor = await _run(
        judging_assessor(requested=("list_account_transactions",), seen=prompts),
        shipped_assessment_limits(),
    )

    assert shipped_assessment_limits().per_run_additional_tool_budget == 0, (
        "the SHIPPED config must go out at budget 0 — stage 2 is a deliberate act by Brian after "
        "Livingston measures stage 1, not a value that drifts in on a commit"
    )
    assert len(prompts) == 1, "the assessor must run at budget 0 exactly as it does at budget 3"

    assessment = _assessment(authority)
    assert assessment["refusedEvidenceRequests"] == [
        {"toolId": "list_account_transactions", "reason": BUDGET_EXHAUSTED}
    ]
    assert assessment["discretionaryEvidenceToolIds"] == []
    # And nothing extra was actually read.
    assert [tool for tool, _ in executor.calls] == ["get_flagged_transaction"]


@pytest.mark.asyncio
async def test_at_budget_three_the_same_request_is_granted_gathered_and_recorded():
    """The other half of the equality: same prompt, same parser, same additions call — a
    different NUMBER, and therefore a different outcome. Nothing else differs."""
    frames, authority, executor = await _run(
        judging_assessor(requested=("list_account_transactions",)), STAGE_TWO
    )

    assessment = _assessment(authority)
    assert assessment["discretionaryEvidenceToolIds"] == ["list_account_transactions"]
    assert assessment["refusedEvidenceRequests"] == []
    assert ("list_account_transactions", {"accountId": "acc_1"}) in executor.calls
    # The record keeps the control and the choice apart. "The copilot reviewed the account" must
    # not mean something different run to run while reading identically.
    assert assessment["requiredEvidenceToolIds"] == ["get_flagged_transaction"]
    assert assessment["evidenceToolIds"] == [
        "get_flagged_transaction",
        "list_account_transactions",
    ]


@pytest.mark.asyncio
async def test_the_discretionary_read_is_a_titled_plan_step_announced_as_a_revision():
    """§P5.5/§P5.2: inserted as ORDINARY tool steps so they inherit the existing iteration cap,
    and titled distinctly so a control and a choice never read identically in the trace."""
    frames, _authority, _executor = await _run(
        judging_assessor(requested=("list_account_transactions",)), STAGE_TWO
    )

    revised = [f for f in frames if f["kind"] == "plan.revised"]
    assert len(revised) == 1
    payload = revised[0]["payload"]
    assert payload["removedStepIds"] == []
    assert len(payload["addedStepIds"]) == 2  # the read, and the re-assess pass

    titles = {f["payload"]["title"] for f in frames if f["kind"] == "step.started"}
    assert "Additional check (agent's choice): list_account_transactions" in titles
    assert "Gather evidence: get_flagged_transaction" in titles
    assert "Re-assess with the additional evidence" in titles


# --------------------------------------------------- §P5.2 the floor, and the signature ----


def test_required_evidence_is_gathered_before_the_model_is_ever_consulted():
    """§P5.2 invariant 1, and it is held by ORDERING rather than by a check.

    If the model is never asked until the required set is in hand, then a model failure, a
    timeout or a garbage reply CANNOT reduce evidence below policy. There is nothing to validate
    because there is no sequence in which it happens.
    """
    steps = _plan_steps(["get_flagged_transaction", "get_customer_profile"], "transaction.hold.place")
    kinds = [s["kind"] for s in steps]
    assert kinds.index("assess") > max(i for i, k in enumerate(kinds) if k == "tool")
    assert kinds.index("assess") < kinds.index("propose")


@pytest.mark.asyncio
async def test_a_dead_assessor_cannot_lower_the_evidence_floor():
    """The invariant above, exercised rather than reasoned about: the model returns garbage, no
    assessment is formed — and every required read still happened, and the proposal still went."""
    frames, authority, executor = await _run(
        scripted_assessor("I am afraid I cannot help with that."),
        shipped_assessment_limits(),
        required=("get_flagged_transaction", "get_customer_profile"),
    )

    assert [tool for tool, _ in executor.calls] == [
        "get_flagged_transaction",
        "get_customer_profile",
    ]
    assessment = _assessment(authority)
    assert assessment["failure"] == "primary_assessment_invalid"
    assert "recommendation" not in assessment
    assert assessment["requiredEvidenceToolIds"] == [
        "get_flagged_transaction",
        "get_customer_profile",
    ]
    # No `run.error`, and the run completed: a failed assessment is not a failed run (§P4.1).
    assert [f for f in frames if f["kind"] == "run.error"] == []
    assert next(f for f in frames if f["kind"] == "run.done")["payload"]["status"] == "completed"


def test_additional_evidence_returns_additions_and_has_no_way_to_say_instead_of():
    """§P5.2 invariant 2. The SIGNATURE is the control, the same move as
    `build_supervisor_input(intent)`: there is no return value that can express "instead of",
    reorder, or drop. A future edit that wants one has to change this signature."""
    import inspect

    signature = inspect.signature(additional_evidence)
    # Everything after the requested ids is keyword-only, so nothing can be swapped in
    # positionally by an edit that looks harmless at the call site.
    assert [
        name for name, p in signature.parameters.items() if p.kind is p.KEYWORD_ONLY
    ] == ["gathered", "known_tool_ids", "bindable_tool_ids", "budget", "quarantined"]

    granted, refused = additional_evidence(
        ["list_account_transactions"],
        gathered=["get_flagged_transaction"],
        known_tool_ids=["get_flagged_transaction", "list_account_transactions"],
        bindable_tool_ids=["get_flagged_transaction", "list_account_transactions"],
        budget=3,
    )
    assert granted == ("list_account_transactions",)
    assert "get_flagged_transaction" not in granted
    assert refused == ()


# ------------------------------------------------------ §P5.3 the candidate set and args ----


@pytest.mark.parametrize(
    "requested,reason",
    [
        ("does_not_exist", UNKNOWN_TOOL),
        ("list_login_audits", QUARANTINED),
        ("get_branch_roster", UNBINDABLE),
        ("get_flagged_transaction", ALREADY_GATHERED),
    ],
)
@pytest.mark.asyncio
async def test_every_refused_request_is_recorded_by_name(requested, reason):
    """A refusal is a positive stated fact with a NAMED reason (§P5.5). Without the name, "did
    not look" and "was not allowed to look" read identically in the record."""
    # A RAW reply rather than the polite helper: this one asks for the tool unconditionally,
    # including when it already has it, because "the model asked for something already in hand"
    # is one of the cases being classified here.
    reply = json.dumps(
        {
            "verdict": "hold",
            "confidence": 0.5,
            "rationale": "One more read would settle the counterparty question.",
            "keyFactors": [{"label": "counterparty unresolved", "citedEvidenceIds": []}],
            "requestedEvidence": [requested],
        }
    )
    _frames, authority, _executor = await _run(scripted_assessor(reply), STAGE_TWO)
    assert _assessment(authority)["refusedEvidenceRequests"] == [
        {"toolId": requested, "reason": reason}
    ]


def test_the_r5_quarantine_is_named_and_not_derived_from_the_projections():
    """§P5.3. `list_login_audits` is filtered upstream by RECENCY, not by user, so no projection
    can honestly assert whose logins are listed — Gate B refused it a projection for that reason.
    A discretionary door into it would put an unfiltered global audit list into one customer's
    approval record by another route.

    It is a NAMED set rather than "tools without a projection", because §P5.4(3) rules that an
    unprojected tool stays gatherable. Deriving it would silently quarantine tools the ruling
    says are fine, and would silently release this one the day someone gave it a projection.
    """
    assert "list_login_audits" in DISCRETIONARY_QUARANTINE


@pytest.mark.asyncio
async def test_the_model_never_supplies_arguments_they_are_bound_from_the_bankers_inputs():
    """§P5.3, and the sharpest risk in the whole feature.

    It is not which tool the model names — it is the arguments. A model that could choose
    arguments could read ANOTHER CUSTOMER'S account and file it in this customer's approval
    record: a data-boundary breach dressed as evidence gathering. So the reply below names a tool
    AND tries to smuggle an account id, and the read that happens uses the banker's own input.
    """
    reply = json.dumps(
        {
            "verdict": "hold",
            "confidence": 0.7,
            "rationale": "The counterparty pattern is unresolved on the evidence gathered.",
            "keyFactors": [{"label": "pattern unresolved", "citedEvidenceIds": []}],
            "unverified": ["the counterparty's other accounts"],
            "requestedEvidence": [
                {"toolId": "list_account_transactions", "accountId": "acc_SOMEONE_ELSE"},
                "list_account_transactions",
            ],
        }
    )
    _frames, _authority, executor = await _run(scripted_assessor(reply), STAGE_TWO)

    reads = dict(executor.calls)
    assert reads["list_account_transactions"] == {"accountId": "acc_1"}
    for _tool, args in executor.calls:
        assert "acc_SOMEONE_ELSE" not in json.dumps(args)


@pytest.mark.asyncio
async def test_a_discretionary_read_that_is_refused_upstream_does_not_fail_the_run():
    """§P5.3: a 403 on a discretionary read is recorded as a refused read, spends its budget, and
    does not fail the run. Recording it is what distinguishes "did not look" from "was not
    allowed to look"; spending the budget bounds a model that would otherwise enumerate the 403s
    to map the session's authority surface."""
    frames, authority, _executor = await _run(
        judging_assessor(requested=("list_account_transactions",)),
        STAGE_TWO,
        failing=("list_account_transactions",),
    )

    assert next(f for f in frames if f["kind"] == "run.done")["payload"]["status"] == "completed"
    assert _assessment(authority)["refusedEvidenceRequests"] == [
        {"toolId": "list_account_transactions", "reason": "read_refused_403"}
    ]


@pytest.mark.asyncio
async def test_a_required_read_that_fails_still_aborts_the_run():
    """The other side of the line above, stated so nobody widens the discretionary leniency by
    accident: a REQUIRED read that fails aborts the plan exactly as it did before the ceiling."""
    frames, _authority, _executor = await _run(
        judging_assessor(), STAGE_TWO, failing=("get_flagged_transaction",)
    )
    assert next(f for f in frames if f["kind"] == "run.done")["payload"]["status"] == "failed"


# ------------------------------------------------------------------ §P5.6 non-convergence ----


@pytest.mark.asyncio
async def test_the_budget_is_per_run_not_per_iteration():
    """§P5.2: two passes cannot spend the budget each."""
    limits = AssessmentLimits(per_run_additional_tool_budget=1, max_assessment_iterations=2)
    _frames, authority, _executor = await _run(
        judging_assessor(requested=("list_account_transactions", "get_customer_profile")), limits
    )
    assessment = _assessment(authority)
    assert assessment["discretionaryEvidenceToolIds"] == ["list_account_transactions"]
    assert {r["reason"] for r in assessment["refusedEvidenceRequests"]} == {BUDGET_EXHAUSTED}


@pytest.mark.asyncio
async def test_hitting_the_iteration_cap_still_proposes_and_records_that_it_did_not_converge():
    """§P5.6. An agent that gathered what it could, stayed unsatisfied and then DECLINED to
    propose has disposed rather than proposed — invisibly, and on grounds the ladder never
    granted it. So it proposes, with its own adverse assessment attached, and the run is not a
    failure. `converged: false` is a POSITIVE recorded fact: without it, "hit the cap while still
    unsatisfied" and "was satisfied on the first pass" read identically.
    """
    frames, authority, _executor = await _run(
        judging_assessor(
            verdict="hold",
            requested=("list_account_transactions",),
            then_requested=("get_customer_profile",),
        ),
        STAGE_TWO,
    )

    assessment = _assessment(authority)
    assert assessment["assessmentIterations"] == 2
    assert assessment["converged"] is False
    assert assessment["recommendation"] == "hold"
    # It asked again on the last permitted pass, and that refusal is named for what it is —
    # calling it `budget_exhausted` would report unspent budget as spent.
    assert [r["reason"] for r in assessment["refusedEvidenceRequests"]] == [ITERATIONS_EXHAUSTED]
    assert assessment["discretionaryEvidenceToolIds"] == ["list_account_transactions"]
    assert next(f for f in frames if f["kind"] == "run.done")["payload"]["status"] == "completed"
    assert [f for f in frames if f["kind"] == "run.error"] == []


@pytest.mark.asyncio
async def test_converged_is_true_only_when_the_primary_formed_a_position_and_asked_for_nothing():
    _frames, authority, _executor = await _run(judging_assessor(), shipped_assessment_limits())
    assessment = _assessment(authority)
    assert assessment["converged"] is True
    assert assessment["assessmentIterations"] == 1


@pytest.mark.asyncio
async def test_a_failed_assessment_never_reads_as_converged():
    """`converged` means "stopped because it was satisfied". A dead assessor is not satisfied,
    and letting its silence read as satisfaction is this feature's whole defect in miniature."""
    _frames, authority, _executor = await _run(
        scripted_assessor("not json"), shipped_assessment_limits()
    )
    assert _assessment(authority)["converged"] is False


# ------------------------------------------------------------------- §P9.9 anti-inertness ----


@pytest.mark.asyncio
async def test_the_assessors_verdict_REACHES_THE_PROPOSAL_body():
    """§P9 item 9, and it is the test the ruling asked for by name.

    A tamper matrix on this service once found that unwiring ``project(...)`` left 285 tests green
    with the entire fix inert. The equivalent hole here is an assessor that is never called from
    the propose path. So this asserts DOWNSTREAM of the wiring, on a value that only the model
    path can produce: a distinctive verdict and rationale, in the body sent to authority-service.
    """
    reply = json.dumps(
        {
            "verdict": "decline",
            "confidence": 0.61,
            "rationale": "A distinctive rationale that only the assessor could have produced.",
            "keyFactors": [
                {"label": "counterparty unknown", "citedEvidenceIds": ["get_flagged_transaction"]}
            ],
        }
    )
    _frames, authority, _executor = await _run(
        scripted_assessor(reply), shipped_assessment_limits()
    )

    assessment = _assessment(authority)
    assert assessment["recommendation"] == "decline"
    assert assessment["rationale"] == (
        "A distinctive rationale that only the assessor could have produced."
    )
    assert assessment["citedEvidenceIds"] == ["get_flagged_transaction"]
    # Attribution rides with it, so a verdict on screen can be traced to the call that made it.
    assert assessment["promptSha256"].startswith("sha256:")
    assert assessment["responseSha256"].startswith("sha256:")
    # And the objective is NOT the assessment. This is the exact regression being closed.
    assert assessment.get("summary") is None
    assert assessment["rationale"] != "Place a hold on the flagged wire."


# ---------------------------------------------------------------- §P5.7 the closed leak ----


@pytest.mark.asyncio
async def test_the_supervisors_read_list_comes_from_the_policy_not_from_what_the_primary_gathered():
    """§P5.7, and the ceiling must not merge without this.

    ``FanOutEngine`` used to derive the supervisor's reads from ``sorted(primary_evidence.keys())``.
    That was correct only by coincidence, while the two sets happened to be equal. The moment
    discretionary evidence landed in that dict, the supervisor's INDEPENDENT draw would silently
    have widened to follow the primary's choices — blindness defeated by a data-flow change in a
    module that never mentions the supervisor.

    So this drives the real planner at budget 3, has the primary gather something extra, and
    asserts the supervisor's draw did not move.
    """
    seen: dict[str, Any] = {}

    class _Fanout:
        async def run_second_opinion(
            self, request, stream, approval, *, required_evidence_tool_ids, depth=1, parent_step_id=""
        ):
            seen["tool_ids"] = tuple(required_evidence_tool_ids)
            return None

    registry = _registry()
    executor = _Executor()
    authority = _Authority(("get_flagged_transaction",))
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)

    class _L2Authority(_Authority):
        async def propose(self, body, *, bearer_token, session_id, agent_id, correlation_id):
            outcome = await super().propose(
                body,
                bearer_token=bearer_token,
                session_id=session_id,
                agent_id=agent_id,
                correlation_id=correlation_id,
            )
            outcome.body["requiredRung"] = "L2"
            return outcome

    authority = _L2Authority(("get_flagged_transaction",))
    planner = Planner(
        registry=registry,
        executor=executor,
        authority=authority,
        max_iterations=12,
        assessment_limits=STAGE_TWO,
        assessor=judging_assessor(requested=("list_account_transactions",)),
        store=_Store(),
        fanout=_Fanout(),
    )
    request = PlannerRequest(
        session=_Session(context={"transactionId": "tx_1"}),
        run_id="run_1",
        objective="Place a hold on the flagged wire.",
        action_id="transaction.hold.place",
        payload={"accountId": "acc_1", "customerId": "cus_1"},
        facts={},
        bearer_token="******",
    )
    await planner.run(request, runs.create("run_1", "sess_1"))

    # The primary really did gather more — otherwise this test would pass by having nothing to
    # leak, which is the "absent by coincidence" failure it exists to rule out.
    assert _assessment(authority)["discretionaryEvidenceToolIds"] == ["list_account_transactions"]
    assert seen["tool_ids"] == ("get_flagged_transaction",)


def test_the_fanout_signature_has_no_parameter_the_primarys_evidence_could_travel_through():
    """The structural half of the fix. Filtering inside the engine would have been a promise;
    removing the parameter is a fact. A future edit that wants the primary's evidence back has to
    change this signature, and that change is what this assertion catches."""
    import inspect

    from app.planner.fanout import FanOutEngine

    parameters = inspect.signature(FanOutEngine.run_second_opinion).parameters
    assert "primary_evidence" not in parameters
    assert "evidence" not in parameters
    assert parameters["required_evidence_tool_ids"].kind is inspect.Parameter.KEYWORD_ONLY


# ------------------------------------------------------------------ §P5.2 the limits file ----


def test_the_bounds_live_in_the_shipped_config_and_not_in_code():
    limits = shipped_assessment_limits()
    assert limits.max_assessment_iterations == 2
    assert limits.per_run_additional_tool_budget == 0


def test_a_missing_bound_aborts_rather_than_defaulting():
    """No literal in code, and no fallback — a threshold stated twice is a threshold wrong once."""
    with pytest.raises(AssessmentLimitsError):
        parse_assessment_limits({"apiVersion": "harness-limits/v1", "assessment": {}})
    with pytest.raises(AssessmentLimitsError):
        parse_assessment_limits({"apiVersion": "harness-limits/v1"})
    with pytest.raises(AssessmentLimitsError):
        parse_assessment_limits(
            {
                "apiVersion": "harness-limits/v1",
                "assessment": {"perRunAdditionalToolBudget": -1, "maxAssessmentIterations": 2},
            }
        )


def test_zero_is_a_legal_budget_but_not_a_legal_iteration_count():
    """Zero budget is stage 1. Zero iterations would mean the primary is never asked at all —
    the no-assessment state this whole feature exists to end, and indistinguishable on the card
    from a model that failed."""
    limits = parse_assessment_limits(
        {
            "apiVersion": "harness-limits/v1",
            "assessment": {"perRunAdditionalToolBudget": 0, "maxAssessmentIterations": 1},
        }
    )
    assert limits.per_run_additional_tool_budget == 0

    with pytest.raises(AssessmentLimitsError):
        parse_assessment_limits(
            {
                "apiVersion": "harness-limits/v1",
                "assessment": {"perRunAdditionalToolBudget": 0, "maxAssessmentIterations": 0},
            }
        )


# --------------------------------------------------------------- §P6 the adverse seam ----


def test_the_adverse_proposal_seam_defaults_to_propose(monkeypatch):
    monkeypatch.delenv("COPILOT_ADVERSE_PROPOSAL", raising=False)
    assert adverse_proposal_mode() == "propose"


def test_the_adverse_proposal_seam_is_declared_never_inferred(monkeypatch):
    from app.config import ConfigurationError

    monkeypatch.setenv("COPILOT_ADVERSE_PROPOSAL", "maybe")
    with pytest.raises(ConfigurationError):
        adverse_proposal_mode()


@pytest.mark.asyncio
async def test_an_adverse_primary_still_proposes_under_the_default(monkeypatch):
    """§P6. An agent that declines to propose has DISPOSED — it exercises a veto the ladder never
    granted it, invisibly, and the banker still needs to act, so the work relocates to the admin
    tabs, which leave no audit record. An adverse proposal on the governed path is strictly
    better than a silent refusal that routes around it."""
    monkeypatch.setenv("COPILOT_ADVERSE_PROPOSAL", "propose")
    frames, authority, _executor = await _run(
        judging_assessor(verdict="decline"), shipped_assessment_limits()
    )
    assert authority.proposed, "the adverse assessment suppressed the proposal"
    assert _assessment(authority)["recommendation"] == "decline"
    assert next(f for f in frames if f["kind"] == "run.done")["payload"]["status"] == "completed"


@pytest.mark.asyncio
async def test_withholding_ends_the_run_failed_with_primary_declined(monkeypatch):
    """Stated explicitly so flipping the seam cannot quietly reintroduce the
    completed-on-no-approval lie through a new door: no approval was admitted, so the derived
    status is `failed`, and the reason is named."""
    monkeypatch.setenv("COPILOT_ADVERSE_PROPOSAL", "withhold")
    frames, authority, _executor = await _run(
        judging_assessor(verdict="decline"), shipped_assessment_limits()
    )
    assert authority.proposed == []
    assert next(f for f in frames if f["kind"] == "run.done")["payload"]["status"] == "failed"
    assert next(f for f in frames if f["kind"] == "run.error")["payload"]["code"] == "primary_declined"
