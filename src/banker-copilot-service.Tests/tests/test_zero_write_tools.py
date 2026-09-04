"""ZERO WRITE TOOLS — the Phase 2 enforcement mechanism, tested structurally.

Epic §4.4 layer 1. The weak form of this test counts the tools registered today
and asserts none is a write. It is worth almost nothing:

  * it passes vacuously if the registry is empty;
  * it passes forever after someone adds a write tool with a typo'd ``mode``,
    because the typo'd value is not the string ``"write"``;
  * it passes if a "read" tool is pointed at a PUT endpoint;
  * it passes if the write path moved somewhere the count never looked.

So the assertions below are about IMPOSSIBILITY, not about today's inventory:
what can be constructed, what the type system admits, and what the transport
will carry — plus an anti-vacuous guard on every count so an empty registry can
never be mistaken for a safe one.
"""

from __future__ import annotations

import copy
import inspect

import pytest

from spec import registry as registry_mod
from spec.manifest import ManifestError, load_manifest
from spec.registry import (
    AuthorityClient,
    DomainReadTransport,
    ProposeActionTool,
    ReadTool,
    ToolRegistrationRefused,
    ToolRegistry,
    WriteAttemptBlocked,
    build_registry,
)


class PermissiveTransport:
    """A stub that would happily carry a DELETE.

    Its whole purpose is to ISOLATE guard A. If the type guard in the registry
    is the only thing standing between the model and a mutation, then swapping
    in a transport with no opinion must not change the outcome. Phase 1 produced
    two guards I had to report as REDUNDANT because I only ever exercised them
    together; that is not happening twice.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def request(self, method, service, path, headers):  # noqa: ANN001
        self.calls.append((method, service, path))
        return {"executed": True}


@pytest.fixture
def wiring(worked_manifest):
    entries = load_manifest(worked_manifest)
    transport = DomainReadTransport()
    authority = AuthorityClient(sink=lambda body: {"approvalId": "apr_1", "status": "proposed"})
    return entries, transport, authority, build_registry(entries, transport, authority)


# ---------------------------------------------------------------------------
# The inventory check — kept, but only as a supporting fact, and guarded
# against the empty-registry vacuum.
# ---------------------------------------------------------------------------


def test_the_registered_tool_surface_is_reads_plus_propose_action_only(wiring):
    entries, _, _, reg = wiring
    read_ids = [e.toolId for e in entries if e.is_read]
    write_ids = [e.toolId for e in entries if e.is_write]

    assert read_ids, "anti-vacuous: a manifest with no read tools proves nothing here"
    assert write_ids, (
        "anti-vacuous: epic §3.3 contains write-MODE entries. If they disappear, this "
        "test stops exercising the routing rule it exists to check and would pass "
        "trivially"
    )

    assert set(reg.tool_ids) == set(read_ids) | {"propose_action"}
    for write_id in write_ids:
        with pytest.raises(ToolRegistrationRefused):
            reg.get(write_id)


def test_a_write_manifest_entry_contributes_an_action_id_and_no_executable_tool(wiring):
    entries, transport, _, reg = wiring
    write = next(e for e in entries if e.is_write)

    propose = reg.get("propose_action")
    assert write.actionId in {
        e.actionId for e in propose.manifest.values() if e.actionId is not None
    }
    assert write.toolId not in reg.tool_ids
    assert transport.calls == []


# ---------------------------------------------------------------------------
# GUARD A — type. Exercised against a transport that would allow anything, so a
# failure here can only be the registry's doing.
# ---------------------------------------------------------------------------


def test_a_write_entry_cannot_be_made_into_a_callable_tool_even_with_a_permissive_transport(
    wiring,
):
    entries, _, _, _ = wiring
    write = next(e for e in entries if e.is_write)

    with pytest.raises(ToolRegistrationRefused):
        ReadTool(entry=write, transport=PermissiveTransport())


def test_a_read_entry_pointed_at_a_mutating_method_cannot_be_constructed(worked_manifest):
    """The typo'd-flag attack: keep ``mode: read``, change only the method.

    A manifest reviewer skims ``mode`` and moves on. This is the shape a write
    tool actually arrives in.
    """
    raw = copy.deepcopy(worked_manifest)
    read_entry = next(e for e in raw if e["mode"] == "read")
    read_entry["target"]["method"] = "DELETE"

    # Caught at manifest load. Belt.
    with pytest.raises(ManifestError, match="method must be GET"):
        load_manifest(raw)


def test_the_same_typo_is_also_refused_at_construction_if_it_reached_that_far(worked_manifest):
    """Braces. Isolates the registry guard from the loader guard.

    Two guards that only ever fire together are one guard with extra steps —
    the redundancy trap from Phase 1. Here the loader is bypassed entirely by
    hand-building the entry, so this test can only be satisfied by
    ``ReadTool.__post_init__``.
    """
    from spec.manifest import Authority, Target, ToolManifestEntry

    smuggled = ToolManifestEntry(
        toolId="looks_like_a_read",
        displayName="x",
        description="x",
        mode="read",
        actionId=None,
        authority=Authority(declaredRung="L1", policyRef="read.any"),
        target=Target(service="user-service", method="DELETE", path="/api/admin/users/{id}",
                      timeoutMs=1000),
        parameters={},
        requiredEvidence=(),
        capabilityScope="identity.read",
        redaction=(),
    )

    with pytest.raises(ToolRegistrationRefused, match="must be a GET"):
        ReadTool(entry=smuggled, transport=PermissiveTransport())


def test_the_registry_refuses_anything_that_is_not_a_read_tool_or_propose_action():
    class ArbitraryWriteTool:
        tool_id = "delete_user"

        def __call__(self, *args, **kwargs):
            return "deleted"

    reg = ToolRegistry()
    with pytest.raises(ToolRegistrationRefused):
        reg.register(ArbitraryWriteTool())
    assert len(reg) == 0


def test_a_duck_typed_impostor_is_refused_because_the_check_is_isinstance_not_attributes():
    """Refusing by shape ("has a ``tool_id``") is refusing nothing.

    Anything can grow an attribute. The check has to be on identity of type.
    """

    class Impostor:
        tool_id = "get_flagged_transaction"
        entry = None
        transport = None

        def __call__(self, args, bearer):
            return "mutated"

    reg = ToolRegistry()
    with pytest.raises(ToolRegistrationRefused):
        reg.register(Impostor())


# ---------------------------------------------------------------------------
# GUARD B — transport. Exercised by a ROGUE executor that never went near the
# registry, so a failure here can only be the transport's doing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_the_domain_transport_refuses_every_mutating_method_whoever_asks(method):
    transport = DomainReadTransport()
    with pytest.raises(WriteAttemptBlocked):
        transport.request(method, "ai-service", "/api/admin/flagged-transactions/t1/review", {})
    assert transport.mutating_calls == []


def test_a_rogue_executor_that_skipped_the_registry_still_cannot_mutate(wiring):
    """The realistic failure: not a malicious tool, a forgotten code path.

    Somebody writes a helper that calls ``transport.request`` directly for a
    "quick" status update. It never touches the registry, so guard A never sees
    it. Guard B has to hold on its own.
    """
    _, transport, _, _ = wiring

    def rogue_helper():
        return transport.request(
            "PUT", "ai-service", "/api/admin/scored-transactions/t1/override", {}
        )

    with pytest.raises(WriteAttemptBlocked):
        rogue_helper()
    assert transport.mutating_calls == []


# ---------------------------------------------------------------------------
# The strongest form: no third class exists that could execute a mutation.
# ---------------------------------------------------------------------------


def test_the_registry_module_defines_no_other_callable_tool_class():
    """An inventory of TYPES, not of instances.

    Counting registered tools describes today. Counting the classes capable of
    being a tool describes what tomorrow can contain. Adding an executable tool
    class fails this test even if nobody has registered one yet.
    """
    callable_classes = [
        obj
        for _, obj in inspect.getmembers(registry_mod, inspect.isclass)
        if obj.__module__ == registry_mod.__name__ and "__call__" in obj.__dict__
    ]
    assert {c.__name__ for c in callable_classes} == {"ReadTool", "ProposeActionTool"}, (
        "a new callable class in spec.registry is a new way for the model to act; it "
        "must be justified against epic §4.4 layer 1 before this expectation is widened"
    )


def test_propose_action_holds_no_reference_capable_of_reaching_a_domain_service():
    """``propose_action`` is write-shaped, so its ATTRIBUTES are the attack surface.

    Give it a transport — even by accident, even as an unused convenience — and
    the sole write affordance becomes a universal write primitive one prompt
    injection away.
    """
    authority = AuthorityClient(sink=lambda body: {"approvalId": "apr_1"})
    tool = ProposeActionTool(authority=authority, manifest={})

    for name, value in vars(tool).items():
        assert not isinstance(value, DomainReadTransport), f"{name} is a domain transport"
        assert not hasattr(value, "request"), (
            f"propose_action.{name} exposes a generic request() method; the authority "
            "client must have exactly one operation and no caller-supplied target"
        )

    assert not hasattr(tool, "execute")
    assert not hasattr(tool, "sign")

    ops = sorted(n for n in dir(authority) if not n.startswith("_"))
    assert ops == ["proposals", "propose"], (
        "the authority client grew an operation; the harness may create an approval "
        "request and nothing else"
    )
