"""The execution path itself, at the point of action.

Everything else in this suite proves that the *manifest* cannot describe a write
and that the *registry* would refuse one. This file asks the narrower question
the four-layer model in epic §4.4 actually requires: at the moment an HTTP
request is issued, what stops it being a POST?

That is a different question, and it has a different answer.
"""

from __future__ import annotations

import copy
import re as _re
from dataclasses import replace

import pytest

from . import service_import  # noqa: F401

from app.tools.executor import ToolExecutor, ToolInvocationError, build_request
from app.tools.manifest import (
    READ_METHODS,
    ReadTool,
    ToolManifest,
    ToolTarget,
    parse_manifest,
)
from app.tools.registry import ToolRegistry


class RecordingClient:
    """Records the method and URL of every request the executor issues.

    A test double at the transport boundary, not at the tool boundary: the point
    is to observe what would actually go on the wire.
    """

    def __init__(self):
        self.calls = []

    async def request(self, method, url, params=None, headers=None, timeout=None):
        self.calls.append((method, url, params))
        return _Response()


class _Response:
    status_code = 200
    text = "{}"

    def json(self):
        return {}


def _rogue_read_tool(method: str, base: ReadTool) -> ReadTool:
    """A tool object that never passed through the loader.

    Derived from a REAL shipping tool with only the method changed, rather than
    hand-constructed. Hand-constructing it means transcribing the ReadTool field
    list into this file, where it silently rots — the first version of this
    helper broke the moment a `display_name` field was added, and a transcribed
    expectation is the exact failure mode this suite exists to avoid. Copying the
    real thing also makes the rogue tool maximally plausible: everything about it
    is valid except the one property under test.
    """
    return replace(base, tool_id="rogue_tool", target=replace(base.target, method=method))


def _placeholders(path: str) -> list[str]:
    return _re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path)


@pytest.fixture
def document():
    import yaml

    from .service_import import TOOL_MANIFEST

    return yaml.safe_load(TOOL_MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture
def registry():
    import yaml

    from .service_import import TOOL_MANIFEST

    manifest = parse_manifest(yaml.safe_load(TOOL_MANIFEST.read_text(encoding="utf-8")))
    return ToolRegistry(
        manifest=manifest,
        service_urls={t.target.service: "http://stub" for t in manifest.tools},
    )


def test_a_registered_read_tool_issues_a_get(registry):
    """Positive control. Without it, an executor that refused everything would
    pass the negative test below."""
    tool = registry.tools[0]
    assert tool.target.method in READ_METHODS


def _registry_with(extra: ReadTool, base: ToolRegistry) -> ToolRegistry:
    """A registry carrying a tool the loader never saw, built through the PUBLIC
    surface.

    The first version of this reached into ``registry._by_id`` — an attribute
    ``ToolRegistry`` does not have. It therefore died on AttributeError whether
    the guard worked or not: it could not pass when the code was right and could
    not fail for the right reason when the code was wrong. A test that cannot
    pass proves exactly as little as one that cannot fail, and it reports the
    same green-adjacent nothing either way.

    ``ToolRegistry`` is a frozen dataclass over a ``ToolManifest``, so the honest
    way to inject a rogue tool is to build a new manifest containing it. That is
    also the realistic shape of the bug: some future code path — a plugin, a
    second manifest format, a fixture left in place — constructs a registry
    without going through ``load_manifest``.
    """
    manifest = ToolManifest(
        api_version=base.manifest.api_version,
        manifest_id=base.manifest.manifest_id,
        tools=base.manifest.tools + (extra,),
    )
    return ToolRegistry(
        manifest=manifest,
        service_urls={**base.service_urls, extra.target.service: "http://stub"},
    )


@pytest.mark.asyncio
async def test_the_executor_refuses_a_mutating_method_at_the_point_of_action(registry):
    """The layer that survives a mistake in the other three.

    The loader runs once at startup; invocation runs continuously on
    model-controlled input. A guard only at load time is defence in depth
    everywhere except the last inch.
    """
    rogue = _registry_with(_rogue_read_tool("POST", registry.tools[0]), registry)
    assert rogue.get("rogue_tool") is not None, (
        "the rogue tool did not reach the registry, so the guard below is never exercised"
    )

    client = RecordingClient()
    executor = ToolExecutor(rogue, client)

    with pytest.raises(ToolInvocationError) as excinfo:
        await executor.invoke("rogue_tool", {}, "tok")

    assert excinfo.value.code in ("write_tool_refused", "invalid_tool", "unknown_tool", "not_a_read")
    assert "POST" in excinfo.value.message, (
        "the refusal must name the offending method; a generic error leaves the caller unable "
        "to tell a blocked write from a broken read"
    )
    assert client.calls == [], "a request was issued before the refusal"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_no_mutating_method_reaches_the_wire_by_any_name(registry, method):
    """Parameterised, because a guard written as `!= "POST"` passes the single
    case above and lets every other verb through."""
    rogue = _registry_with(_rogue_read_tool(method, registry.tools[0]), registry)
    client = RecordingClient()

    with pytest.raises(ToolInvocationError):
        await ToolExecutor(rogue, client).invoke("rogue_tool", {}, "tok")

    assert client.calls == []


@pytest.mark.asyncio
async def test_a_genuine_read_still_reaches_the_wire(registry):
    """The positive control for the two tests above.

    Without it, an executor that raised on every invocation would pass both and
    the harness would be provably safe and entirely useless.
    """
    client = RecordingClient()
    tool = next(t for t in registry.tools if not t.target.path_params)

    await ToolExecutor(registry, client).invoke(tool.tool_id, {}, "tok")

    assert len(client.calls) == 1
    assert client.calls[0][0] == "GET"


@pytest.mark.asyncio
async def test_a_tool_absent_from_the_manifest_cannot_be_called_at_all(registry):
    """The manifest is the complete set of affordances. A model naming a
    plausible-sounding tool must get a refusal, not a best-effort URL."""
    executor = ToolExecutor(registry, RecordingClient())

    with pytest.raises(ToolInvocationError) as excinfo:
        await executor.invoke("approve_transfer", {}, "tok")

    assert excinfo.value.code == "unknown_tool"


# My own escape corpus, deliberately NOT imported from the loader.
#
# The loader proves each declared pattern refuses a corpus of hostile values. If
# I import that corpus to check the same property, I am asserting the loader
# agrees with itself, and a hole in the corpus is invisible from both sides. An
# independent list is the only version of this test that can disagree with the
# implementation.
ESCAPE_ATTEMPTS = (
    "..",
    "../admin",
    "../../admin/execute",
    "....//admin",
    "a/b",
    "/absolute",
    "a%2fb",
    "%2e%2e%2f",
    "..%2Fadmin",
    "..;/admin",
    "a\\b",
    "a?query=1",
    "a#fragment",
    "",
    " ",
    "a\nb",
    "a\x00b",
    "http://elsewhere.invalid/x",
    "//elsewhere.invalid/x",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("hostile", ESCAPE_ATTEMPTS)
async def test_arguments_cannot_smuggle_a_different_path(registry, hostile):
    """Path traversal through an argument.

    The declared path IS the tool's capability scope. If a model-supplied value
    can leave it, the scope is advisory — and tool arguments are model-controlled
    while model context contains tool output, so this is reachable by injection.
    """
    tool = next(t for t in registry.tools if t.target.path_params)
    parameter = next(iter(tool.target.path_params))

    client = RecordingClient()
    with pytest.raises(ToolInvocationError):
        await ToolExecutor(registry, client).invoke(tool.tool_id, {parameter: hostile}, "tok")

    assert client.calls == [], f"a request was issued for {hostile!r} before the refusal"


@pytest.mark.asyncio
async def test_a_legitimate_identifier_still_works(registry):
    """The positive control. A parameter validator that refuses everything
    passes all twenty cases above and breaks every tool in the manifest."""
    tool = next(t for t in registry.tools if t.target.path_params)
    parameter = next(iter(tool.target.path_params))

    client = RecordingClient()
    await ToolExecutor(registry, client).invoke(tool.tool_id, {parameter: "txn_12345"}, "tok")

    assert len(client.calls) == 1
    assert client.calls[0][1].endswith("txn_12345")


def test_every_shipping_path_parameter_is_provably_anchored(registry):
    """Anchoring, proven by probe rather than by inspection.

    This is the false-pass generator worth internalising: **JSON Schema
    ``pattern`` is a search, not a full match.** A plausible
    ``[A-Za-z0-9_-]+`` matches ``../../admin`` — it finds ``admin`` inside it —
    and sails through code review looking exactly like the fix. Asserting that a
    pattern *exists*, or even eyeballing it, would therefore certify the bug.

    So: compile each declared pattern and require it to REFUSE every hostile
    value, which is a property no unanchored pattern can have.
    """
    import re

    checked = 0
    for tool in registry.tools:
        for name in tool.target.path_params:
            schema = tool.parameters["properties"][name]
            pattern = schema.get("pattern")
            assert isinstance(pattern, str) and pattern.strip(), (
                f"{tool.tool_id}.{name} declares no pattern; an unconstrained path parameter "
                "walks straight out of the declared path"
            )
            compiled = re.compile(pattern)
            accepted = [v for v in ESCAPE_ATTEMPTS if compiled.search(v)]
            assert not accepted, (
                f"{tool.tool_id}.{name} pattern {pattern!r} ACCEPTS {accepted!r}. "
                "`pattern` is a search, not a full match — anchor it with ^ and $."
            )
            checked += 1

    assert checked >= 9, (
        f"only {checked} path parameters were checked; the shipping manifest has nine, so "
        "this test is no longer covering what it claims to"
    )


def test_an_unanchored_pattern_is_refused_by_the_loader(document):
    """The specific mistake, at the layer that must catch it.

    ``[A-Za-z0-9_-]+`` is what a careful person writes when asked to constrain an
    id. It is also unanchored, so it matches ``../../admin``. A loader that
    accepts it has implemented the fix and kept the bug.
    """
    from app.tools.manifest import ManifestError

    doc = copy.deepcopy(document)
    tool = next(t for t in doc["tools"] if "{" in t["target"]["path"])
    name = next(iter(_placeholders(tool["target"]["path"])))
    tool["parameters"]["properties"][name] = {"type": "string", "pattern": "[A-Za-z0-9_-]+"}

    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(doc)
    assert name in str(excinfo.value)


def test_a_missing_pattern_is_refused_by_the_loader(document):
    """Fail closed. An absent constraint must refuse startup, not default to
    permissive."""
    from app.tools.manifest import ManifestError

    doc = copy.deepcopy(document)
    tool = next(t for t in doc["tools"] if "{" in t["target"]["path"])
    name = next(iter(_placeholders(tool["target"]["path"])))
    tool["parameters"]["properties"][name] = {"type": "string"}

    with pytest.raises(ManifestError):
        parse_manifest(doc)


@pytest.mark.asyncio
async def test_the_executor_confines_the_segment_even_when_the_pattern_is_permissive(registry):
    """The second layer, isolated from the first.

    The loader runs once at startup; invocation runs continuously on
    model-controlled input. If the only thing confining a path parameter is a
    manifest rule, then a future manifest edit is all that stands between a
    prompt injection and an undeclared endpoint. Here the tool is given a
    deliberately permissive pattern — as if it had bypassed the loader — and the
    executor must still refuse.
    """
    base = next(t for t in registry.tools if t.target.path_params)
    name = next(iter(base.target.path_params))
    permissive = replace(
        base,
        tool_id="permissive_tool",
        parameters={
            **base.parameters,
            "properties": {
                **base.parameters["properties"],
                name: {"type": "string"},
            },
        },
    )
    rogue = _registry_with(permissive, registry)
    client = RecordingClient()

    with pytest.raises(ToolInvocationError):
        await ToolExecutor(rogue, client).invoke("permissive_tool", {name: "../../admin"}, "tok")

    assert client.calls == []


@pytest.mark.asyncio
async def test_a_reserved_character_is_encoded_rather_than_passed_through(registry):
    """Values that are legal but structurally significant must not survive as
    structure. Encoding is what makes "one segment" true rather than hoped for.
    """
    base = next(t for t in registry.tools if t.target.path_params)
    name = next(iter(base.target.path_params))
    permissive = replace(
        base,
        tool_id="permissive_tool",
        parameters={
            **base.parameters,
            "properties": {**base.parameters["properties"], name: {"type": "string"}},
        },
    )
    rogue = _registry_with(permissive, registry)
    client = RecordingClient()

    await ToolExecutor(rogue, client).invoke("permissive_tool", {name: "a:b@c"}, "tok")

    url = client.calls[0][1]
    assert "a%3Ab%40c" in url, url


def test_arguments_that_are_not_path_parameters_become_query_not_path(registry):
    """Query strings cannot change which endpoint is addressed. Path
    substitution can, so the split between them is a security boundary."""
    tool = next(t for t in registry.tools if "{" in t.target.path)
    parameter = next(iter(tool.target.path_params))

    url, query = build_request(tool, registry, {parameter: "abc", "unexpected": "xyz"})

    assert "abc" in url
    assert query == {"unexpected": "xyz"}
    assert "unexpected" not in url


def test_the_executor_module_exposes_no_write_helper():
    """Structural. A `post`/`mutate` helper is a write path that exists before
    anybody calls it."""
    import app.tools.executor as module

    public = {name for name in dir(module) if not name.startswith("_")}
    for forbidden in ("post", "put", "patch", "delete", "mutate", "write"):
        assert forbidden not in public, forbidden


def test_no_module_in_the_service_names_a_mutating_http_verb_against_a_domain_service(repo_root):
    """The sweep that catches a write path added somewhere nobody thought to
    test. `propose.py` is the single permitted exception, and it targets
    authority-service — which is the whole design.
    """
    import re

    offenders = []
    for path in (repo_root / "src" / "banker-copilot-service" / "app").rglob("*.py"):
        if path.name == "propose.py":
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if re.search(r"client\.(post|put|patch|delete)\s*\(", line):
                offenders.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")

    assert not offenders, (
        "a mutating HTTP call exists outside propose.py:\n" + "\n".join(offenders)
    )
