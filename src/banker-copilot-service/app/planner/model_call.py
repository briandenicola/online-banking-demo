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

import hashlib
import json
from dataclasses import dataclass
from typing import Any


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


__all__ = ["extract_json", "sha256_text", "Attribution"]
