"""Shared plumbing for the two model calls this service makes — and nothing else.

Both agents read a JSON object out of a model reply, and both must be attributable after the
fact. Those two facts are stated HERE, once, because the alternative is two copies that drift:
the repo's standing rule is that a thing stated twice is a thing wrong once.

What is deliberately NOT here: anything that shapes the QUESTION. The primary's instructions
and the supervisor's instructions live in their own modules and are never shared, because the
independence of the second opinion rests on the two agents being asked *different questions*
(ruling §P1.2c). A shared prompt builder is the refactor that would quietly undo it, so this
module offers no home for one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)


def extract_json(text: str) -> dict[str, Any] | None:
    """Pull the JSON object out of a model reply, tolerating a code fence around it.

    Deliberately narrow: it finds the outermost braces and parses once. It does not repair
    malformed JSON, because a reply we cannot read is a reply we must not act on — and
    "repairing" it would mean guessing a verdict on a banking action.
    """
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def as_chat_messages(prompt: str) -> list[Any]:
    """Turn a prompt string into the message sequence the Agent Framework chat clients want.

    Every model call in this service used to pass the prompt string straight to
    ``get_response``. The signature is ``Sequence[Message]``, and a ``str`` IS a sequence — of
    single characters — so the client walked the prompt letter by letter and died on
    ``'str' object has no attribute 'role'`` before a single request left the process. Nothing
    caught it, because every test in the suite stubs the transport: the string was never handed
    to a real client anywhere, in CI or in the cloud.

    ``normalize_messages`` is the framework's own public converter (``str`` -> one user
    message) and is present in every pinned version this repo uses, so this is the framework's
    answer rather than ours. It is stated once, here, for all four call sites.
    """
    from agent_framework import normalize_messages

    return normalize_messages(prompt)


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Attribution:
    """Who said this, on which exact bytes (ruling §P7.1).

    The record cannot be *reproducible* — identical bytes produce split verdicts — so its job
    is to be **attributable and re-checkable**: a reader must be able to say which model, in
    which mode, on which exact prompt, said this, even though re-running it would not reproduce
    it. A record that implies reproducibility it does not have is the same lie in a new costume.

    ``mode`` distinguishes a judgement from a script, which is the exact confusion
    ``planner_mode`` and ``supervisor_mode`` were written to prevent. ``model_deployment`` is
    here so a reader can see for themselves that both assessments came from the same base model
    (§P1.2e) — that residual correlation is disclosed, never papered over.

    The raw reply text is NOT carried here and never lands on the approval: it belongs in the
    event stream, joined by ``sessionId``/``correlationId`` (§P7.1).
    """

    mode: str
    model_deployment: str = ""
    prompt_sha256: str = ""
    response_sha256: str = ""

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"mode": self.mode}
        # Absent rather than empty-string: a blank model id reads as "some model", and this
        # field exists precisely so a reader can tell which one.
        if self.model_deployment:
            wire["modelDeployment"] = self.model_deployment
        if self.prompt_sha256:
            wire["promptSha256"] = self.prompt_sha256
        if self.response_sha256:
            wire["responseSha256"] = self.response_sha256
        return wire


async def await_model(
    make_call: Callable[[], Awaitable[Any]],
    *,
    timeout_s: float,
    phase: str,
    model: str,
    attempts: int = 2,
) -> Any:
    """Await a model round trip under `timeout_s`, recording what it cost either way.

    Four call sites each had their own `asyncio.wait_for(..., timeout=30.0)` literal and
    between them recorded NOTHING about how long a call actually took. So when two of three
    cloud runs failed with `planner_model_unavailable`, the only available evidence was
    that our own budget had expired — not what real latency looks like, and therefore no
    basis for choosing a better number than the one that was already failing.

    `phase` names the caller — `intent`, `answer`, `primary`, `supervisor` — because a run
    makes several of these calls and the per-run wall clock is their SUM. A log that says
    only "the model was slow" cannot tell you which of four budgets to raise.

    `make_call` is a FACTORY rather than an awaitable because a retry needs a fresh one.
    The retry sits INSIDE the single `wait_for`, so the total is still bounded by
    `timeout_s` and the banker-facing "did not answer within Ns" stays literally true — a
    retry that extended the budget would quietly turn that sentence back into a lie.

    Only a transient failure is retried. `ChatClientInvalidAuthException`,
    `ChatClientInvalidRequestException` and `ChatClientContentFilterException` are verdicts
    about the request itself and will fail identically the second time; retrying them buys
    nothing and spends the budget that the honest retry needs.

    Exceptions propagate unchanged. Each caller still owns its own failure vocabulary: a
    timed-out intent selector and a timed-out supervisor are different events to a banker,
    and swallowing one here would move that decision away from the code that knows it.
    """
    started = time.monotonic()

    async def _attempted() -> Any:
        for attempt in range(1, attempts + 1):
            try:
                return await make_call()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - re-raised below unless retryable
                if attempt >= attempts or not _is_transient(exc):
                    raise
                logger.warning(
                    "Model call failed, retrying once inside the same budget",
                    phase=phase,
                    model=model,
                    error=type(exc).__name__,
                    attempt=attempt,
                    elapsed_ms=_elapsed_ms(started),
                )
        raise AssertionError("unreachable")  # pragma: no cover

    try:
        response = await asyncio.wait_for(_attempted(), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning(
            "Model call exceeded its budget",
            phase=phase,
            model=model,
            timeout_s=timeout_s,
            elapsed_ms=_elapsed_ms(started),
        )
        raise
    except Exception as exc:  # noqa: BLE001 - re-raised; the caller owns the vocabulary
        logger.warning(
            "Model call failed",
            phase=phase,
            model=model,
            error=type(exc).__name__,
            elapsed_ms=_elapsed_ms(started),
        )
        raise
    logger.info(
        "Model call completed",
        phase=phase,
        model=model,
        timeout_s=timeout_s,
        elapsed_ms=_elapsed_ms(started),
    )
    return response


def _is_transient(exc: BaseException) -> bool:
    """Is this worth a second attempt inside the same budget?

    Measured, not assumed. A live run failed with `ChatClientException` wrapping
    `APITimeoutError('Request timed out.')` at 18.6s elapsed — inside a 60s budget of ours.
    That is the SDK's own request timeout, not the endpoint being down and not our ceiling,
    which is why raising our number would not have helped that run at all. A single
    transient cut of that kind currently ends the whole run in a refusal, which on stage is
    indistinguishable from the feature not working.
    """
    try:
        from agent_framework.exceptions import (
            ChatClientContentFilterException,
            ChatClientException,
            ChatClientInvalidAuthException,
            ChatClientInvalidRequestException,
        )
    except ImportError:  # pragma: no cover - the framework is a hard dependency in the app
        return False

    if isinstance(
        exc,
        (
            ChatClientInvalidAuthException,
            ChatClientInvalidRequestException,
            ChatClientContentFilterException,
        ),
    ):
        return False
    return isinstance(exc, ChatClientException)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


__all__ = ["as_chat_messages", "await_model", "extract_json", "sha256_text", "Attribution"]
