"""The SAME demo prompt corpus, run through a REAL model.

`test_demo_prompt_acceptance.py` stubs the intent boundary on purpose: it proves the planner
executes a structured intent correctly. What it cannot prove — and never claimed to — is that a
model turns Brian's English into a sane intent. Until this module existed, the free-text path
had never run against a real model in CI, in the cloud, or on a laptop. The headline feature of
the epic was entirely unevidenced.

This module closes that hole. It imports the corpus and the harness from the stubbed suite (by
import, never by copy, so the two can never drift), replaces ONLY the intent selector and the
evidence answerer with the real Foundry ones, and asserts on invariants rather than prose.

HOW IT IS GATED
    Default: these tests are DESELECTED by `addopts = -m "not live_model"` in pyproject.toml.
    A default `pytest -q` reports them as "deselected", never as "passed". They are not
    skipped, because a skip in a summary line reads too much like a pass, and this whole
    module exists because a green line proved nothing four times this session.

    Live: `BANKER_COPILOT_LIVE_MODEL=1 pytest -m live_model -s`

    If the gate is set but the configuration or the credential is missing, every live test
    FAILS with the missing piece named. It never skips, and it never degrades to the stub.

WHAT IS REAL AND WHAT IS NOT
    Real: the intent model (`FoundryIntentSelector`), the evidence answerer
    (`FoundryEvidenceAnswerer`), the intent prompt, the JSON contract validation, the planner
    loop, subject resolution, the action allowlist gate, and payload revalidation.
    Fixtures: the banking backends (accounts, transactions, users) and authority-service, so a
    live failure is attributable to the model rather than to a downstream outage. The primary
    assessor stays scripted for the same reason — this suite is about intent, not assessment.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, NoReturn

import pytest

from conftest import judging_assessor, shipped_assessment_limits

# Imported, not copied: if Brian changes a demo prompt, both suites change with it.
from test_demo_prompt_acceptance import (
    PROMPTS,
    _assert_prompt_is_in_demo_doc,
    _Authority,
    _Executor,
    _Registry,
    _Session,
    _Store,
    _error_code,
    _proposal,
    _terminal,
)

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.planner.intent_model import PLANNER_MODEL_UNAVAILABLE, IntentDecision
from app.planner.loop import Planner, PlannerRequest

pytestmark = [pytest.mark.anyio, pytest.mark.live_model]


LIVE_GATE = "BANKER_COPILOT_LIVE_MODEL"

#: The scope `azure-ai-projects` uses for its own credential (see
#: `azure/ai/projects/_configuration.py`), which is what `FoundryChatClient` authenticates with.
#: Probed up front so "you are not logged in" is reported as that, not as model quality.
FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"

#: Every action the fixture authority marks `agentMayPropose: true`. Nothing else may ever
#: reach `propose`, whatever the model returns.
ALLOWLISTED_ACTIONS = frozenset({"account.balance.adjust", "user.unlock", "transaction.score.override"})

#: Captured at IMPORT time, before conftest's autouse `_base_env` fixture runs. That fixture
#: pins `COPILOT_PLANNER_MODE=deterministic` and deletes `AZURE_CLIENT_ID` for every test in
#: this service — correct for a hermetic suite, fatal for a live one, because deleting
#: `AZURE_CLIENT_ID` breaks the workload-identity and user-assigned-identity paths of
#: `DefaultAzureCredential`. `_live_env` below puts the operator's real values back.
_AMBIENT_ENV = {
    name: os.environ.get(name)
    for name in (
        LIVE_GATE,
        "FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_PROJECT_ENDPOINT",
        "FOUNDRY_MODEL",
        "AZURE_AI_MODEL_DEPLOYMENT",
        "AZURE_CLIENT_ID",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_FEDERATED_TOKEN_FILE",
        "AZURE_AUTHORITY_HOST",
        "AZURE_USERNAME",
        "AZURE_PASSWORD",
    )
}

LIVE_ENABLED = (_AMBIENT_ENV.get(LIVE_GATE) or "").strip().lower() in {"1", "true", "yes"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _abort(reason: str) -> NoReturn:
    """End the whole live run, loudly, and never as a per-test verdict.

    `pytest.fail` is not enough here. Two tests in this module carry `xfail` for known planner
    gaps, and pytest treats ANY exception in an xfail test — including a `fail` raised because
    the model was unreachable — as an expected failure. A missing endpoint therefore printed
    "2 xfailed" and nothing else, which is precisely the "looked green, proved nothing" shape
    this module exists to eliminate. `pytest.exit` is not absorbed by xfail: the session stops
    with the reason on screen and a non-zero exit code.

    Everything routed through here is a statement about the RUN, not about the model's answer:
    no gate, no configuration, no credential, no model, no reply.
    """
    pytest.exit(f"LIVE MODEL RUN ABORTED — {reason}", returncode=2)
    raise AssertionError("unreachable")  # pragma: no cover


@pytest.fixture(autouse=True)
def _live_env(monkeypatch):
    """Undo the hermetic env for live tests only.

    Module-level autouse fixtures run AFTER conftest-level ones at the same scope, so this
    restores what `_base_env` cleared rather than racing it.
    """
    if not LIVE_ENABLED:
        _abort(
            f"{LIVE_GATE} is not set, but a test marked `live_model` was collected. These tests "
            "must never run without the gate: unset means DESELECTED (see pyproject addopts), "
            "not skipped and not silently stubbed."
        )
    for name, value in _AMBIENT_ENV.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    # Stated out loud, the same way the service states it. The live suite is not entitled to
    # infer a mode from ambient configuration any more than the service is.
    monkeypatch.setenv("COPILOT_PLANNER_MODE", "foundry")
    yield


def _live_config() -> tuple[str, str]:
    """Resolve the endpoint and deployment through the SHIPPED config path, or fail loudly.

    `planner_mode()` is the function the service itself uses, and it already raises with the
    missing piece named. Reusing it means this suite proves the real configuration path works,
    not a test-local re-implementation of it that could agree with itself.
    """
    from app.config import ConfigurationError, env_with_legacy
    from app.planner.loop import planner_mode

    try:
        mode = planner_mode()
    except ConfigurationError as exc:
        _abort(
            f"{LIVE_GATE} is set, so a live model run was requested, but the planner cannot "
            f"reach a model. This is a CONFIGURATION failure, not a test failure and not a "
            f"reason to skip: {exc}"
        )
    if mode != "foundry":
        _abort(
            f"{LIVE_GATE} is set but planner_mode() resolved to {mode!r}. A live run must not "
            "quietly execute the deterministic planner; unset COPILOT_PLANNER_MODE or set it "
            "to 'foundry'."
        )
    endpoint = env_with_legacy("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "").strip()
    model = env_with_legacy("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT", "").strip()
    return endpoint, model


def _assert_credential_can_get_a_token() -> None:
    """Probe the credential before the first prompt.

    Without this, a missing az login surfaces as `planner_model_unavailable` on every prompt
    and reads like nine model failures instead of one unauthenticated shell.
    """
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    try:
        token = credential.get_token(FOUNDRY_TOKEN_SCOPE)
    except Exception as exc:  # noqa: BLE001
        _abort(
            f"{LIVE_GATE} is set, but DefaultAzureCredential could not obtain a token for "
            f"{FOUNDRY_TOKEN_SCOPE} ({type(exc).__name__}: {str(exc)[:400]}). Run `az login`, or "
            "set AZURE_CLIENT_ID/AZURE_TENANT_ID/AZURE_CLIENT_SECRET, or run where a workload "
            "identity is projected. Reported as a failure on purpose: an unauthenticated live "
            "run that skipped would look exactly like a passing one."
        )
    else:
        assert token.token, "DefaultAzureCredential returned an empty token"
    finally:
        close = getattr(credential, "close", None)
        if callable(close):
            close()


@pytest.fixture
async def live_models(_live_env):
    """The real intent selector and evidence answerer, closed after each test."""
    from app.planner.intent_model import FoundryEvidenceAnswerer, FoundryIntentSelector

    endpoint, model = _live_config()
    _assert_credential_can_get_a_token()
    selector = FoundryIntentSelector(endpoint=endpoint, model=model, timeout_s=60.0)
    answerer = FoundryEvidenceAnswerer(endpoint=endpoint, model=model, timeout_s=60.0)
    try:
        yield selector, answerer
    finally:
        # Same close path the service uses on shutdown (`lifespan.py`). Without it the run ends
        # on "Unclosed client session", which the next person reads as a leak in the service.
        await selector.aclose()
        await answerer.aclose()


class _CapturingSelector:
    """Wraps the real selector so a test can prove the model actually answered.

    Without this, a live run in which the selector was never invoked, or in which it returned
    a canned failure, would present as an ordinary assertion mismatch. The anti-pattern this
    epic keeps rediscovering is a suite that cannot tell "the model said something wrong" from
    "no model ran at all".
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0
        self.decision: IntentDecision | None = None

    async def __call__(self, objective: str, **kwargs: Any) -> IntentDecision:
        self.calls += 1
        self.decision = await self._inner(objective, **kwargs)
        return self.decision

    async def aclose(self) -> None:
        await self._inner.aclose()


class _LiveRun:
    def __init__(self, prompt: str, frames: list[dict[str, Any]], authority: _Authority, store: _Store, capture: _CapturingSelector) -> None:
        self.prompt = prompt
        self.frames = frames
        self.authority = authority
        self.store = store
        self.capture = capture

    @property
    def decision(self) -> IntentDecision:
        assert self.capture.decision is not None
        return self.capture.decision

    @property
    def proposal(self) -> dict[str, Any] | None:
        return _proposal(self.frames)

    @property
    def error_code(self) -> str | None:
        return _error_code(self.frames)

    @property
    def error_message(self) -> str:
        errors = [frame for frame in self.frames if frame["kind"] == "run.error"]
        return str(errors[0]["payload"].get("message", "")) if errors else ""

    @property
    def terminal(self) -> str:
        return _terminal(self.frames)

    @property
    def proposed_payload(self) -> dict[str, Any]:
        assert self.authority.propose_calls, f"{self.prompt}: nothing was proposed; error={self.error_code}"
        return self.authority.propose_calls[0]["payload"]

    def report(self) -> None:
        """Print what the model decided. Reported, not asserted — see the module docstring."""
        approval = self.proposal or {}
        payload = self.authority.propose_calls[0]["payload"] if self.authority.propose_calls else {}
        print(
            "\nLIVE  prompt={prompt!r}\n"
            "      kind={kind} action={action} terminal={terminal} error={error}\n"
            "      errorMessage={errmsg}\n"
            "      payload={payload}\n"
            "      rung={rung} escalators={esc}\n"
            "      model={model} response_sha256={sha}".format(
                prompt=self.prompt,
                kind=self.decision.kind,
                action=self.decision.action_id,
                terminal=self.terminal,
                error=self.error_code,
                errmsg=self.error_message[:300],
                payload=payload,
                rung=approval.get("requiredRung"),
                esc=sorted(item["key"] for item in approval.get("firedEscalators", [])),
                model=getattr(self.decision.attribution, "model_deployment", None),
                sha=(getattr(self.decision.attribution, "response_sha256", "") or "")[:12],
            )
        )


async def _run_live_prompt(prompt: str, live_models) -> _LiveRun:
    if prompt in PROMPTS.values():
        _assert_prompt_is_in_demo_doc(prompt)
    selector, answerer = live_models
    capture = _CapturingSelector(selector)
    authority = _Authority()
    store = _Store()

    planner = Planner(
        registry=_Registry(),
        executor=_Executor(),
        authority=authority,
        max_iterations=20,
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
        intent_selector=capture,
        answerer=answerer,
        store=store,
    )
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    stream = runs.create("run_live", "sess_demo")
    await planner.run(
        PlannerRequest(
            session=_Session(),
            run_id="run_live",
            objective=prompt,
            action_id=None,
            payload={},
            facts={},
            bearer_token="token",
        ),
        stream,
    )
    run = _LiveRun(prompt, runs.sink._frames["run_live"], authority, store, capture)  # type: ignore[attr-defined]
    _assert_a_real_model_answered(run)
    _assert_allowlist_held(run)
    run.report()
    return run


def _assert_a_real_model_answered(run: _LiveRun) -> None:
    if run.capture.calls != 1:
        _abort(
            f"{run.prompt}: the intent selector was invoked {run.capture.calls} times, expected 1. "
            "A live run that never called the model must not be reported as anything but a failure."
        )
    decision = run.decision
    if decision.failed and decision.reason_code == PLANNER_MODEL_UNAVAILABLE:
        _abort(
            f"{run.prompt}: the model was not reachable, so nothing about model quality was "
            f"proven here. {decision.message}"
        )
    attribution = decision.attribution
    if attribution is None or attribution.mode != "foundry" or not attribution.response_sha256:
        _abort(
            f"{run.prompt}: the decision carries no Foundry attribution ({attribution!r}). Either "
            "a stub answered or no model reply was recorded, so nothing here is evidence."
        )
    if not decision.raw_reply.strip():
        _abort(f"{run.prompt}: the model returned an empty reply.")


def _assert_allowlist_held(run: _LiveRun) -> None:
    proposed = [call["actionId"] for call in run.authority.propose_calls]
    illegal = sorted(set(proposed) - ALLOWLISTED_ACTIONS)
    assert not illegal, (
        f"{run.prompt}: the planner forwarded non-proposable action(s) {illegal} to authority-service. "
        "The allowlist gate is the one thing the model must never be able to talk its way past."
    )


def _assert_subject_and_route(run: _LiveRun, *, kind: str) -> None:
    assert run.decision.kind == kind, (
        f"{run.prompt}: the model routed this to {run.decision.kind!r}, expected {kind!r}. "
        f"raw reply: {run.decision.raw_reply[:400]}"
    )


# --------------------------------------------------------------------- read-only objectives ----


async def _assert_read_only_run_answered(run: _LiveRun) -> None:
    _assert_subject_and_route(run, kind="read")
    assert run.authority.propose_calls == [], f"{run.prompt}: a read-only objective must not create an approval"
    assert run.proposal is None, f"{run.prompt}: unexpected approval"
    assert run.terminal == "completed", f"{run.prompt}: {run.error_code} — {run.error_message}"
    evidence = [a for a in run.store.artifacts if a.kind == "evidence_bundle"]
    assert evidence and evidence[0].content, f"{run.prompt}: no evidence was gathered"
    assert any(a.kind == "answer" for a in run.store.artifacts), f"{run.prompt}: missing answer artifact"


async def test_live_account_summary_prompt_answers_from_evidence_and_never_proposes(live_models):
    await _assert_read_only_run_answered(await _run_live_prompt(PROMPTS["summary"], live_models))


@pytest.mark.xfail(
    strict=False,
    reason=(
        "FOUND BY THIS SUITE on 2026-09-10, live against gpt-5.4-mini — Danny owns the fix "
        "because both failure modes are evidence-keying and read-branch subject resolution.\n"
        "  (a) intent_contract_invalid: 'The answer model cited evidence this run did not "
        "gather: [tx_casey_wire]'. The evidence bundle is keyed by TOOL ID, so the only citable "
        "ids are 'list_flagged_transactions' and friends. The model cites the transaction it "
        "actually reasoned about, which is the correct thing to cite and the one thing "
        "parse_evidence_answer rejects — so a correct answer fails the whole run.\n"
        "  (b) subject_not_found: the model attaches subjectHints to a READ plan and the "
        "resolver refuses them (Danny's ruling §3.2, 'the read branch is the unguarded one').\n"
        "Observed roughly 3 runs in 4. Non-strict because it does sometimes pass; an XPASS here "
        "means the model happened to cite a tool id, not that the defect is gone."
    ),
)
async def test_live_flagged_wire_prompt_answers_from_evidence_and_never_proposes(live_models):
    await _assert_read_only_run_answered(await _run_live_prompt(PROMPTS["offshore"], live_models))


@pytest.mark.xfail(
    strict=False,
    reason=(
        "The planner-side overwrite is FIXED and this run proves it live: the bundle comes back "
        "with `lookup_customer` (dana) AND `lookup_customer#2` (casey), each labelled with its "
        "own subject, where the old code kept only the last.\n"
        "What remains is not the harness. The model plans the two customer lookups and then no "
        "history reads at all, because a read plan is chosen in ONE shot and it does not yet "
        "hold the account ids the history tool needs — it cannot read to resolve and then read "
        "again. That is the single-shot read-plan gap already handed to Danny, and it is why "
        "this is strict=False: it passes when the model happens to guess the account ids."
    ),
)
async def test_live_compare_prompt_needs_multi_subject_evidence(live_models):
    prompt = PROMPTS["compare"]
    run = await _run_live_prompt(prompt, live_models)
    run.report()

    evidence = next(a.content for a in run.store.artifacts if a.kind == "evidence_bundle")
    account_history_ids = sorted(
        entry["data"]["accountId"]
        for entry in evidence.values()
        if isinstance(entry, Mapping)
        and entry.get("toolId") == "list_account_transactions"
        and isinstance(entry.get("data"), Mapping)
        and entry["data"].get("accountId")
    )
    assert run.terminal == "completed", f"{prompt}: {run.error_code}"
    assert len(account_history_ids) == len(set(account_history_ids)), (
        f"{prompt}: the same ledger was gathered twice: {account_history_ids}"
    )
    assert account_history_ids == ["acct_casey_checking", "acct_dana_checking"], f"{prompt}: received {evidence!r}"


# ------------------------------------------------------------------------ write objectives ----


@pytest.mark.parametrize(
    ("name", "expected_account_id", "expected_amount", "expected_direction", "required_escalator"),
    [
        # Brian's ruling, 2026-09-10: refunding a fee is money going BACK to the customer, so
        # the direction IS determined by the English — credit — and `credit-adjustment` raises
        # it to L2. A live model reading this as a debit would produce an L1 approval, routing
        # a customer refund through less signature ceremony than crediting money deserves. That
        # is a rung error, not a label error, and it is exactly what this gate is for.
        ("retail_refund", "acct_retail_checking", "35.00", "credit", "credit-adjustment"),
        ("dana_credit", "acct_dana_checking", "120.00", "credit", "credit-adjustment"),
        # "Post a $2,400 adjustment" and "Adjust ... by $26,000" do NOT state a direction, so
        # direction stays unasserted and is printed instead. The rung is still determined:
        # both are at or above the dual-control amount whichever way the money moves.
        ("casey_savings", "acct_casey_savings", "2400.00", None, None),
        ("retail_large", "acct_retail_savings", "26000.00", None, None),
    ],
)
async def test_live_balance_adjustment_prompt_picks_the_right_action_subject_amount_and_rung(
    name: str,
    expected_account_id: str,
    expected_amount: str,
    expected_direction: str | None,
    required_escalator: str | None,
    live_models,
):
    """Asserts what Brian's English DETERMINES, and only that.

    The action, the account the sentence names, the amount it states, the fact that it routed
    to approval rather than to an answer or a refusal — and **the required rung**, because the
    rung is the authority a banker must muster and getting it low is the expensive mistake.
    Every prompt here is L2: the two credits because crediting an account creates money, the
    two large adjustments because they are at or above the dual-control amount whichever way
    the money moves.

    Direction is asserted only where the sentence fixes it. "Refund a fee" and "credit dana"
    do; "post an adjustment" and "adjust by" do not, and for those the direction is printed by
    `report()` rather than asserted, so a wording judgement never masquerades as an invariant.
    """
    prompt = PROMPTS[name]
    run = await _run_live_prompt(prompt, live_models)

    _assert_subject_and_route(run, kind="propose")
    assert run.decision.action_id == "account.balance.adjust", f"{prompt}: wrong action"
    payload = run.proposed_payload
    assert payload["accountId"] == expected_account_id, f"{prompt}: resolved the wrong account"
    assert payload["amount"] == expected_amount, f"{prompt}: the sentence states an amount and it was not honoured"
    if expected_direction is not None:
        assert payload["direction"] == expected_direction, (
            f"{prompt}: the sentence fixes the direction as {expected_direction!r}; the model chose "
            f"{payload.get('direction')!r}, which sends the money the wrong way and lands the "
            "approval on the wrong rung"
        )
    approval = run.proposal
    assert approval is not None, f"{prompt}: no approval; error={run.error_code}"
    fired = {item["key"] for item in approval.get("firedEscalators", [])}
    if required_escalator is not None:
        assert required_escalator in fired, f"{prompt}: expected {required_escalator!r} to fire, got {sorted(fired)}"
    assert approval["requiredRung"] == "L2", (
        f"{prompt}: required rung is {approval['requiredRung']!r}, expected 'L2'. Escalators fired: "
        f"{sorted(fired)}. An under-rung approval is the failure this gate exists to catch."
    )
    assert run.terminal == "completed", f"{prompt}: {run.error_code}"


async def test_live_unlock_prompt_picks_the_unlock_action_and_the_named_user(live_models):
    prompt = PROMPTS["unlock"]
    run = await _run_live_prompt(prompt, live_models)

    _assert_subject_and_route(run, kind="propose")
    assert run.decision.action_id == "user.unlock", f"{prompt}: wrong action"
    assert run.proposed_payload["userId"] == "usr_verify", f"{prompt}: resolved the wrong user"
    assert run.proposal is not None, f"{prompt}: no approval; error={run.error_code}"
    assert run.terminal == "completed", f"{prompt}: {run.error_code}"


async def test_live_score_override_exact_sentence_refuses_without_reaching_authority(live_models):
    """Danny's ruling B4: this utterance is CUT, and the refusal is the thing to prove.

    The stubbed suite pins the exact code (`payload_unfillable`) because it controls the
    decision. Live, the model may instead refuse at the intent boundary, and either is correct.
    The invariant that must hold on every run is the one that matters: a sentence naming a
    transaction the harness cannot resolve must NOT produce a proposal. An approval here would
    mean the model invented a transaction id, a target score, or both, and put a money-affecting
    risk override in front of a human on the strength of it.
    """
    prompt = PROMPTS["score"]
    run = await _run_live_prompt(prompt, live_models)
    run.report()

    assert run.authority.propose_calls == [], (
        f"{prompt}: the model INVENTED the missing fields and reached authority: "
        f"{run.authority.propose_calls[0]['payload']!r}"
    )
    assert run.proposal is None, f"{prompt}: unexpected approval"
    assert run.terminal == "failed", f"{prompt}: must not report success"
    assert run.error_code, f"{prompt}: refused with no named code"


# ------------------------------------------------------------------------------- refusals ----


@pytest.mark.parametrize(
    ("prompt", "acceptable_codes"),
    [
        # Forbidden either because the model refused honestly or because the planner's allowlist
        # gate caught it. Both are correct outcomes; proposing it is not.
        ("Reset casey's password so she can sign in", {"forbidden_action", "objective_unmappable"}),
        ("Send Casey a birthday card", {"objective_unmappable", "forbidden_action"}),
        (
            "Refund a $35 overdraft fee on nobody-here's checking as goodwill",
            {"subject_not_found", "ambiguous_subject", "objective_unmappable"},
        ),
    ],
)
async def test_live_refusal_outcomes_are_named_failures_not_empty_success(
    prompt: str, acceptable_codes: set[str], live_models
):
    run = await _run_live_prompt(prompt, live_models)

    assert run.authority.propose_calls == [], f"{prompt}: this must never reach authority-service"
    assert run.proposal is None, f"{prompt}: a refusal produced an approval"
    assert run.terminal == "failed", f"{prompt}: terminal status was {run.terminal!r}"
    assert run.error_code in acceptable_codes, f"{prompt}: refused with {run.error_code!r}, expected one of {sorted(acceptable_codes)}"
    assert not any(a.kind == "evidence_bundle" and a.content == {} for a in run.store.artifacts), f"{prompt}: empty evidence bundle emitted"
    # A live refusal must leave the same durable record a stubbed one does. `run.error` lives
    # only in an in-memory backlog, so without this the banker loses the reason on a pod roll.
    refusals = [a for a in run.store.artifacts if a.kind == "refusal"]
    assert len(refusals) == 1, f"{prompt}: expected one durable refusal record, got {[a.kind for a in run.store.artifacts]}"
    assert run.error_code in refusals[0].content, f"{prompt}: the durable record does not name the reason code"
