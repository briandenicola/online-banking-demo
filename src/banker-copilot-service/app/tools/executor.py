"""Read-tool execution over HTTP.

Three rules, all of them load-bearing:

1. **Tools call REST, never Cosmos or Redis** (epic §3.1). This service holds no domain
   container name and no domain Cosmos role assignment, so the rule is enforced by what is
   absent from its configuration, not by discipline here.
2. **The banker's JWT is forwarded verbatim.** The agent can see nothing the banker could not.
3. **Redaction happens here**, before the result enters model context or a persisted frame.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
import jsonschema
import structlog

from app.tools.manifest import READ_METHODS, ReadTool
from app.tools.redaction import redact
from app.tools.registry import ToolRegistry

logger = structlog.get_logger("banker-copilot-service")


class ToolInvocationError(RuntimeError):
    """A tool call that could not be made or could not be trusted."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ToolResult:
    tool_id: str
    status_code: int
    data: Any
    duration_ms: int

    def summary(self) -> str:
        if isinstance(self.data, list):
            return f"{len(self.data)} record(s)"
        if isinstance(self.data, dict):
            keys = sorted(self.data.keys())[:4]
            return f"object with {', '.join(keys)}" if keys else "empty object"
        return str(self.data)[:120]


def validate_arguments(tool: ReadTool, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        jsonschema.validate(instance=arguments, schema=tool.parameters)
    except jsonschema.ValidationError as exc:
        raise ToolInvocationError(
            "invalid_arguments", f"{tool.tool_id}: {exc.message}"
        ) from exc
    return arguments


# Characters that end a path segment or the path itself. Rejected outright rather than encoded,
# so that a value which was never meant to be a single segment fails loudly instead of being
# quietly mangled into one.
_SEGMENT_BREAKERS = ("/", "\\", "?", "#")


def _confine_to_one_segment(tool: ReadTool, name: str, value: Any) -> str:
    """Second line of defence behind the loader's pattern requirement.

    The loader already refuses a manifest whose path parameters are not provably confined, so in a
    correct manifest this never fires. It exists because the loader runs once at startup while
    invocation runs continuously on model-controlled input, and because a future manifest edit
    should not be the only thing standing between a prompt injection and an undeclared endpoint.
    """
    raw = str(value)
    if not raw:
        raise ToolInvocationError(
            "invalid_arguments",
            f"{tool.tool_id}: path parameter {name!r} is empty; an empty segment resolves a "
            "different endpoint than the one this tool declares",
        )
    if any(breaker in raw for breaker in _SEGMENT_BREAKERS) or raw.strip(".") == "":
        raise ToolInvocationError(
            "invalid_arguments",
            f"{tool.tool_id}: path parameter {name!r} would leave the declared path "
            f"{tool.target.path!r}. The declared path is this tool's capability scope.",
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in raw):
        raise ToolInvocationError(
            "invalid_arguments",
            f"{tool.tool_id}: path parameter {name!r} contains control characters",
        )
    # safe="" so that reserved characters cannot re-introduce structure after validation.
    return quote(raw, safe="")


def build_request(tool: ReadTool, registry: ToolRegistry, arguments: dict[str, Any]):
    """Split validated arguments into path substitutions and query parameters.

    Path substitutions are confined to a single segment and percent-encoded; query parameters are
    encoded by httpx and cannot alter the path.
    """
    path = tool.target.path
    query: dict[str, Any] = {}

    for name, value in arguments.items():
        placeholder = "{" + name + "}"
        if placeholder in path:
            path = path.replace(placeholder, _confine_to_one_segment(tool, name, value))
        else:
            query[name] = value

    return f"{registry.base_url(tool.target.service)}{path}", query


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, client: httpx.AsyncClient) -> None:
        self._registry = registry
        self._client = client

    async def invoke(
        self, tool_id: str, arguments: dict[str, Any], bearer_token: str
    ) -> ToolResult:
        tool = self._registry.get(tool_id)
        if tool is None:
            raise ToolInvocationError(
                "unknown_tool",
                f"{tool_id!r} is not a registered tool. The manifest is the complete set of "
                "affordances; anything absent from it cannot be named, let alone called.",
            )

        # F2-8: the loader enforces read-only once, at startup; this enforces it on every call.
        # Defence in depth matters precisely here, because the thing that varies between the two
        # is model-controlled input. A registry mutated in-process, a hand-built ReadTool, or a
        # future loader regression all get stopped at the last gate before the network.
        if tool.target.method not in READ_METHODS:
            raise ToolInvocationError(
                "write_tool_refused",
                f"{tool_id}: declares method {tool.target.method!r}, which is not a read method "
                f"({sorted(READ_METHODS)}). This service registers no write tools; the only "
                "write affordance is propose_action, which cannot execute anything.",
            )

        validate_arguments(tool, arguments)
        url, query = build_request(tool, self._registry, arguments)

        started = time.monotonic()
        try:
            response = await self._client.request(
                tool.target.method,
                url,
                params=query or None,
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "Accept": "application/json",
                },
                timeout=tool.target.timeout_ms / 1000,
            )
        except httpx.TimeoutException as exc:
            raise ToolInvocationError(
                "upstream_timeout", f"{tool_id}: upstream did not respond in time"
            ) from exc
        except httpx.HTTPError as exc:
            raise ToolInvocationError("upstream_error", f"{tool_id}: {exc}") from exc

        duration_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 400:
            raise ToolInvocationError(
                "upstream_status",
                f"{tool_id}: upstream returned {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        return ToolResult(
            tool_id=tool_id,
            status_code=response.status_code,
            data=redact(payload, tool.redaction),
            duration_ms=duration_ms,
        )
