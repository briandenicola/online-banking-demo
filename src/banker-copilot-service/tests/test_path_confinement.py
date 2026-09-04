"""F2-7 and F2-5/F2-8: the declared path is the capability scope.

A read tool that can be steered outside its declared path has a scope that is advisory rather than
enforced. Tool arguments are model-controlled and tool output re-enters model context, so an
unconstrained path parameter is reachable by prompt injection — the same structural failure the
epic's write-tool prohibition exists to prevent, one layer down.
"""

from __future__ import annotations

import copy
import dataclasses

import pytest

from app.tools.executor import ToolExecutor, ToolInvocationError, build_request
from app.tools.manifest import ManifestError, ReadTool, ToolTarget, parse_manifest
from app.tools.registry import ToolRegistry

_ANCHORED = "^[A-Za-z0-9_-]{1,64}$"


def _manifest_document(pattern: str | None = _ANCHORED) -> dict:
    parameter: dict = {"type": "string", "description": "a transaction id"}
    if pattern is not None:
        parameter["pattern"] = pattern
    return {
        "apiVersion": "copilot-tools/v1",
        "metadata": {"manifestId": "test-manifest"},
        "tools": [
            {
                "toolId": "get_transaction",
                "displayName": "Get transaction",
                "description": "Read one transaction.",
                "target": {
                    "service": "transaction-service",
                    "method": "GET",
                    "path": "/api/transactions/{txId}",
                    "timeoutMs": 1000,
                },
                "parameters": {
                    "type": "object",
                    "properties": {"txId": parameter},
                    "required": ["txId"],
                    "additionalProperties": False,
                },
                "capabilityScope": "transactions.read",
                "redaction": [],
            }
        ],
    }


# ------------------------------------------------ the loader refuses the vocabulary ----


def test_a_path_parameter_without_a_pattern_is_refused_at_load():
    """Fail closed. The manifest must be unable to EXPRESS an unconstrained path parameter,
    for the same reason it is unable to express a write tool."""
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(_manifest_document(pattern=None))

    assert "pattern" in str(excinfo.value)
    assert "txId" in str(excinfo.value)


@pytest.mark.parametrize(
    "pattern",
    [
        "[A-Za-z0-9_-]+",  # unanchored: 'pattern' is a search, so this matches '../../admin'
        "^.*$",  # anchored but permits anything
        ".+",
        "^[A-Za-z0-9_/-]+$",  # anchored but admits a separator
        "^[A-Za-z0-9._-]*$",  # admits '..' and the empty string
    ],
)
def test_a_pattern_that_admits_an_escape_is_refused_at_load(pattern):
    """Each of these looks plausible on inspection. The loader does not read the pattern; it
    proves the pattern refuses a corpus of values that leave the declared path."""
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(_manifest_document(pattern=pattern))

    assert "leave the declared path" in str(excinfo.value)


def test_an_anchored_single_segment_pattern_is_accepted():
    manifest = parse_manifest(_manifest_document())
    assert manifest.tools[0].target.path_params == frozenset({"txId"})


def test_a_path_parameter_declared_as_a_non_string_is_refused():
    document = _manifest_document()
    document["tools"][0]["parameters"]["properties"]["txId"]["type"] = "integer"
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(document)
    assert "type: string" in str(excinfo.value)


def test_every_shipping_path_parameter_is_confined(manifest_path):
    """Set membership, not a count: names the offending parameter rather than reporting a
    number that a rename would keep satisfying."""
    from app.tools.manifest import load_manifest

    shipping_manifest = load_manifest(str(manifest_path))
    unconfined = {
        f"{tool.tool_id}.{name}"
        for tool in shipping_manifest.tools
        for name in tool.target.path_params
        if not str(
            ((tool.parameters.get("properties") or {}).get(name) or {}).get("pattern", "")
        ).strip()
    }
    assert unconfined == set()


# ---------------------------------------------- substitution cannot leave the path ----


def _tool() -> ReadTool:
    return parse_manifest(_manifest_document()).tools[0]


def _registry(tool: ReadTool) -> ToolRegistry:
    manifest = parse_manifest(_manifest_document())
    manifest = dataclasses.replace(manifest, tools=(tool,))
    return ToolRegistry(manifest=manifest, service_urls={"transaction-service": "http://svc"})


@pytest.mark.parametrize(
    "hostile",
    [
        "../../admin/whatever",
        "..",
        "../admin",
        "a/b",
        "/absolute",
        "a?query=1",
        "a#fragment",
        "",
        "a\\b",
    ],
)
def test_substitution_refuses_a_value_that_would_leave_the_declared_path(hostile):
    tool = _tool()
    with pytest.raises(ToolInvocationError) as excinfo:
        build_request(tool, _registry(tool), {"txId": hostile})
    assert excinfo.value.code == "invalid_arguments"


def test_a_reserved_character_is_encoded_rather_than_structuring_the_url():
    tool = _tool()
    url, _ = build_request(tool, _registry(tool), {"txId": "a:b;c=d"})
    assert url == "http://svc/api/transactions/a%3Ab%3Bc%3Dd"


def test_an_ordinary_id_survives_untouched():
    tool = _tool()
    url, query = build_request(tool, _registry(tool), {"txId": "tx_123-ABC"})
    assert url == "http://svc/api/transactions/tx_123-ABC"
    assert query == {}


# ------------------------------------------- F2-5/F2-8: the guard at the point of action ----


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def request(self, method, url, **kwargs):  # pragma: no cover - must never run
        self.calls.append((method, url))
        raise AssertionError(f"a {method} request reached the network: {url}")


async def test_the_executor_refuses_a_mutating_method_at_the_point_of_action():
    """The loader runs once, at startup; invocation runs continuously on model-controlled
    input. A ReadTool built by any path other than load_manifest() must still be refused."""
    rogue = dataclasses.replace(
        _tool(),
        tool_id="rogue_tool",
        target=ToolTarget(
            service="transaction-service",
            method="POST",
            path="/api/transactions/{txId}",
            timeout_ms=1000,
        ),
    )
    client = _RecordingClient()
    executor = ToolExecutor(_registry(rogue), client)

    with pytest.raises(ToolInvocationError) as excinfo:
        await executor.invoke("rogue_tool", {"txId": "tx_1"}, "token")

    assert excinfo.value.code == "write_tool_refused"
    assert client.calls == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "get", "HEAD"])
async def test_no_non_read_method_reaches_the_network(method):
    rogue = dataclasses.replace(
        _tool(),
        tool_id="rogue_tool",
        target=ToolTarget(
            service="transaction-service",
            method=method,
            path="/api/transactions/{txId}",
            timeout_ms=1000,
        ),
    )
    client = _RecordingClient()
    executor = ToolExecutor(_registry(rogue), client)

    with pytest.raises(ToolInvocationError):
        await executor.invoke("rogue_tool", {"txId": "tx_1"}, "token")
    assert client.calls == []
