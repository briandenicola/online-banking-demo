"""The authority catalogue is a fetch, and a fetch can fail.

Brian's reading of the cloud refusal was that an empty catalogue could surface to a
banker as `objective_unmappable` — "the bank cannot do that" — rather than as an error.
On the free-text path it cannot: `_run_intent_step` already refuses loudly when the
catalogue is unavailable. But one floor down, on the pinned-action path, the same
failure was doing something worse than mislabelling: `_required_evidence` swallowed it
and returned an EMPTY required-evidence list, which plans a run with no reads at all and
walks straight to a propose.

That is the fail-OPEN direction. The free-text path fails closed; this one did not. Both
are the same shape Brian keeps finding: a failure that renders as a confident answer.
"""

from __future__ import annotations

import asyncio

from typing import Any

import httpx
import pytest

import app.tools.propose as propose_module

from conftest import judging_assessor, shipped_assessment_limits

from app.events.bus import InMemoryTraceSink, RunStreamRegistry
from app.config import ConfigurationError, MODEL_TIMEOUT_ENV, model_timeout_s
from app.planner.loop import Planner, PlannerRequest
from app.tools.propose import AuthorityClient

from test_demo_prompt_acceptance import (
    _Authority,
    _Executor,
    _Registry,
    _Session,
    _Store,
    _answerer_requiring_evidence,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _BrokenCatalogue(_Authority):
    """Authority reachable for `propose`, unreachable for the catalogue.

    This asymmetry is the realistic one: a catalogue GET that 500s or times out does not
    stop the propose POST from being attempted, which is exactly why the fail-open path
    was reachable at all.
    """

    async def policy_catalogue(self, bearer_token: str) -> dict[str, Any]:
        return {"actions": [], "available": False, "reason": "http_status"}


async def _run(request: PlannerRequest, authority: _Authority) -> list[dict[str, Any]]:
    planner = Planner(
        registry=_Registry(),
        executor=_Executor(),
        authority=authority,
        max_iterations=20,
        assessment_limits=shipped_assessment_limits(),
        assessor=judging_assessor(),
        intent_selector=None,
        answerer=_answerer_requiring_evidence,
        store=_Store(),
    )
    runs = RunStreamRegistry(InMemoryTraceSink(), replay_window=500)
    stream = runs.create("run_cat", "sess_cat")
    await planner.run(request, stream)
    return runs.sink._frames["run_cat"]  # type: ignore[attr-defined]


def _pinned_request() -> PlannerRequest:
    """A structured run: the banker already chose the action in the UI."""
    return PlannerRequest(
        session=_Session(),
        run_id="run_cat",
        objective="Post a balance adjustment",
        action_id="account.balance.adjust",
        payload={
            "accountId": "acct_casey_checking",
            "amount": "35.00",
            "direction": "credit",
            "reason": "Goodwill refund of an overdraft fee",
        },
        facts={},
        bearer_token="token",
    )


def _codes(frames: list[dict[str, Any]]) -> list[str]:
    """Every refusal code anywhere in the stream, however it is nested.

    Read off the frames the browser actually receives rather than off the planner's
    internals, because the question is what a banker is told.
    """
    codes: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"code", "reasonCode", "error"} and isinstance(item, str):
                    codes.append(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(frames)
    return codes


async def test_a_pinned_run_does_not_propose_when_the_catalogue_is_unavailable() -> None:
    """The fail-open one. No catalogue means no known requiredEvidence, so no propose.

    Proposing here would hand authority a proposal built on evidence nobody checked was
    required. Authority would reject it — this is not a hole in the money path — but the
    banker would be shown an evidence complaint for what is really an outage, and the
    planner would have asserted a completeness it could not know.
    """
    authority = _BrokenCatalogue()
    frames = await _run(_pinned_request(), authority)

    assert authority.propose_calls == [], (
        "the planner proposed with an unavailable catalogue; "
        f"it could not have known what evidence was required: {authority.propose_calls}"
    )


async def test_an_unavailable_catalogue_refuses_with_its_own_code() -> None:
    """A skip must be loud. An outage must not read as a policy judgement."""
    frames = await _run(_pinned_request(), _BrokenCatalogue())
    codes = _codes(frames)

    assert "authority_catalogue_unavailable" in codes, codes
    assert "objective_unmappable" not in codes, (
        "an outage rendered as 'the bank cannot do that'"
    )


async def test_the_free_text_refusal_does_not_blame_authority_for_an_outage() -> None:
    """`proposal_refused_by_authority` means authority looked and said no.

    Nothing was ever proposed here, so nothing was refused. The UI copy for that code
    reads "Evidence was gathered and a proposal was constructed, but authority rejected
    it" — three statements, all false on this path.
    """
    request = PlannerRequest(
        session=_Session(),
        run_id="run_cat",
        objective="Refund a $35 overdraft fee for casey",
        action_id=None,
        payload={},
        facts={},
        bearer_token="token",
    )
    frames = await _run(request, _BrokenCatalogue())
    codes = _codes(frames)

    assert "authority_catalogue_unavailable" in codes, codes
    assert "proposal_refused_by_authority" not in codes, (
        "blamed authority for refusing a proposal that was never made"
    )


class _Response:
    def __init__(self, status_code: int, payload: Any = None, *, unparseable: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self._unparseable = unparseable
        self.text = "not json"

    def json(self) -> Any:
        if self._unparseable:
            raise ValueError("no json")
        return self._payload


def _client_returning(result: Any) -> AuthorityClient:
    class _Http:
        async def get(self, *args: Any, **kwargs: Any) -> Any:
            if isinstance(result, Exception):
                raise result
            return result

    client = AuthorityClient(base_url="http://authority", client=_Http(), timeout_ms=5000)  # type: ignore[arg-type]
    return client


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (_Response(503), "http_status"),
        (httpx.ConnectError("refused"), "transport_error"),
        (_Response(200, unparseable=True), "unparseable_response"),
    ],
)
async def test_each_catalogue_failure_mode_is_named_and_logged(
    result: Any, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three different failures collapsed into one silent return with no log line.

    Brian could prove the endpoint returns 13 actions NOW; he could not prove what it
    returned on the failing run, because nothing recorded it. That is the actual reason
    this was undiagnosable, and it is fixed by naming the mode, not by guessing.
    """
    # The logger is swapped rather than captured. structlog is configured process-wide with
    # `cache_logger_on_first_use=True`, so whether `capture_logs` or `caplog` sees anything
    # depends on whether some earlier test module already called `configure_logging()` —
    # both of those assertions passed alone and failed in the full run. A test whose result
    # depends on file collection order proves nothing in either direction.
    logged: list[tuple[str, dict[str, Any]]] = []

    class _Recorder:
        def warning(self, event: str, **kwargs: Any) -> None:
            logged.append((event, kwargs))

    monkeypatch.setattr(propose_module, "logger", _Recorder())
    catalogue = await _client_returning(result).policy_catalogue("s3cret-bearer")

    assert catalogue["available"] is False
    assert catalogue["reason"] == reason
    assert [fields for _, fields in logged if fields.get("reason") == reason], (
        f"a catalogue failure left no trace at all: {logged!r}"
    )
    # The fetch is authenticated, so a log line about it is a place a bearer token can
    # leak. It carries the mode and the status, never the credential.
    assert "s3cret-bearer" not in repr(logged)


# ── The model timeout, which was four literals ──────────────────────────────────────────


def test_every_model_timeout_comes_from_one_place(monkeypatch: pytest.MonkeyPatch) -> None:
    """Four copies of a constant is three chances to diverge.

    `timeout_s: float = 30.0` was written out in `supervisor_model.py`, `primary_model.py`
    and twice in `intent_model.py`. Nothing held them equal and nothing could change them
    in a running cluster. This asserts the reading, not the value: a future deployment
    that raises the ceiling must raise it for all four phases at once.
    """
    from app.planner.intent_model import FoundryEvidenceAnswerer, FoundryIntentSelector
    from app.planner.primary_model import FoundryPrimaryAssessor
    from app.planner.supervisor_model import FoundryDecider

    monkeypatch.setenv(MODEL_TIMEOUT_ENV, "12.5")
    built = [
        FoundryIntentSelector(endpoint="e", model="m"),
        FoundryEvidenceAnswerer(endpoint="e", model="m"),
        FoundryPrimaryAssessor(endpoint="e", model="m"),
        FoundryDecider(endpoint="e", model="m"),
    ]

    assert [agent.timeout_s for agent in built] == [12.5] * 4


@pytest.mark.parametrize("raw", ["not-a-number", "0", "-5"])
def test_an_unusable_timeout_is_a_startup_error_not_a_silent_default(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo'd ceiling must not keep timing out at the old number in silence.

    The failure this guards against is a config file that says the budget was raised while
    the service goes on expiring at the default — which is indistinguishable, from the
    outside, from the raise not having worked.
    """
    monkeypatch.setenv(MODEL_TIMEOUT_ENV, raw)

    with pytest.raises(ConfigurationError):
        model_timeout_s()


async def test_a_model_call_reports_what_it_cost() -> None:
    """Latency was unmeasured, which is why "what is the right timeout" had no answer.

    Two of three cloud runs died on our own 30s budget. The only evidence that produced was
    that 30s was too short — never how much too short, and never for which of the four
    phases.
    """
    import app.planner.model_call as model_call_module

    observed: list[tuple[str, dict[str, Any]]] = []

    class _Recorder:
        def info(self, event: str, **kwargs: Any) -> None:
            observed.append((event, kwargs))

        def warning(self, event: str, **kwargs: Any) -> None:
            observed.append((event, kwargs))

    original = model_call_module.logger
    model_call_module.logger = _Recorder()  # type: ignore[assignment]
    try:

        async def quick() -> str:
            return "done"

        assert await model_call_module.await_model(
            quick, timeout_s=5, phase="intent", model="m"
        ) == "done"
    finally:
        model_call_module.logger = original  # type: ignore[assignment]

    assert observed, "a model call left no latency record"
    _, fields = observed[-1]
    assert fields["phase"] == "intent"
    assert isinstance(fields["elapsed_ms"], int)


async def test_a_transient_model_failure_is_retried_once_inside_the_same_budget() -> None:
    """One cut endpoint call currently ends a whole run in a refusal.

    Measured, not assumed: a live run failed with `ChatClientException` wrapping
    `APITimeoutError('Request timed out.')` at 18.6s elapsed, INSIDE a 60s budget of ours.
    So that class of failure is the SDK's own request timeout rather than our ceiling, and
    raising our number would not have saved it. A second attempt would have.
    """
    from agent_framework.exceptions import ChatClientException

    from app.planner.model_call import await_model

    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ChatClientException("Request timed out.")
        return "second time lucky"

    assert await await_model(flaky, timeout_s=5, phase="intent", model="m") == "second time lucky"
    assert attempts == 2


@pytest.mark.parametrize(
    "exception_name",
    [
        "ChatClientInvalidAuthException",
        "ChatClientInvalidRequestException",
        "ChatClientContentFilterException",
    ],
)
async def test_a_verdict_about_the_request_is_not_retried(exception_name: str) -> None:
    """These will fail identically the second time.

    Retrying them buys nothing and spends the budget the honest retry needs — and a
    doubled content-filter call is a second copy of customer text sent to the model.
    """
    import agent_framework.exceptions as framework_exceptions

    from app.planner.model_call import await_model

    failure = getattr(framework_exceptions, exception_name)
    attempts = 0

    async def always_refused() -> str:
        nonlocal attempts
        attempts += 1
        raise failure("no")

    with pytest.raises(failure):
        await await_model(always_refused, timeout_s=5, phase="intent", model="m")
    assert attempts == 1


async def test_the_retry_does_not_extend_the_stated_budget() -> None:
    """"did not answer within Ns" has to stay literally true.

    The retry sits inside the single `wait_for`, so two slow attempts cannot add up to more
    than the ceiling. A retry that reset the clock would turn the banker-facing sentence
    back into the kind of number that is not the number.
    """
    import time as _time

    from agent_framework.exceptions import ChatClientException

    from app.planner.model_call import await_model

    async def slow_and_flaky() -> str:
        await asyncio.sleep(0.4)
        raise ChatClientException("Request timed out.")

    started = _time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await await_model(slow_and_flaky, timeout_s=0.5, phase="intent", model="m")
    elapsed = _time.monotonic() - started

    assert elapsed < 1.0, f"the retry pushed the call past its own ceiling: {elapsed:.2f}s"
