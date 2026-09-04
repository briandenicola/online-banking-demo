"""Tool registry and transports — the service split, made structural.

Epic §4.4 layer 1:

    "``banker-copilot-service`` registers *no* write tool with the Foundry agent.
    The only write-shaped affordance is ``propose_action(actionId, payload,
    evidenceRefs)``, whose target is ``authority-service``. There is no tool the
    model can call whose target is a mutating domain endpoint."

A test that counts today's registered tools and finds no writes among them is
worth very little: it passes forever after somebody adds a write tool with a
typo'd flag, and it passes vacuously if the registry is empty. So the property
is made **unrepresentable** instead of merely checked, by TWO independent
guards:

  A. **Type.** ``ToolRegistry.register`` accepts only a ``ReadTool`` or the one
     ``ProposeActionTool``. ``ReadTool.__post_init__`` refuses anything whose
     manifest entry is not ``mode == 'read'`` and ``method == 'GET'``. There is
     no third class in this module that can issue a domain mutation.
  B. **Transport.** ``DomainReadTransport`` refuses any method but GET,
     regardless of which caller asks. Even a hand-constructed rogue executor
     that skipped the registry cannot reach a mutating endpoint through it.

Phase 1 taught me what happens when two guards protect one property and the
tests only ever exercise them together: breaking either one alone is
unobservable, and both go into the report as REDUNDANT rather than PROVEN. So
each guard here has a test that isolates it — guard A is exercised against a
deliberately permissive stub transport, guard B against a rogue executor that
never went through the registry. Both must be independently observable failing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .manifest import MODE_READ, READ_METHOD, ToolManifestEntry

# The one action the harness may take against authority-service. Not a prefix
# match: a prefix would also admit /api/authority/approvals/{id}/sign, and the
# harness signing anything is the invariant failing.
AUTHORITY_PROPOSE_PATH = "/api/authority/approvals"


class WriteAttemptBlocked(RuntimeError):
    """A non-GET was attempted through the harness's domain transport."""


class ToolRegistrationRefused(TypeError):
    """Something that is not a read tool was offered to the registry."""


@dataclass(frozen=True)
class HttpCall:
    method: str
    service: str
    path: str
    headers: Mapping[str, str]


class DomainReadTransport:
    """GUARD B. The harness's only route to domain services. GET or nothing.

    Every call is recorded, so a test can assert on the *absence* of a mutating
    request after a whole agent run — the only way to check "nothing was
    executed" that does not depend on knowing in advance which path an attacker
    would have taken.
    """

    def __init__(self, responder: Callable[[HttpCall], Any] | None = None) -> None:
        self.calls: list[HttpCall] = []
        self._responder = responder or (lambda call: {})

    def request(self, method: str, service: str, path: str, headers: Mapping[str, str]) -> Any:
        if method != READ_METHOD:
            raise WriteAttemptBlocked(
                f"{method} {service}{path} refused: the harness holds a read-only "
                "transport; agent-originated writes go through authority-service"
            )
        call = HttpCall(method=method, service=service, path=path, headers=dict(headers))
        self.calls.append(call)
        return self._responder(call)

    @property
    def mutating_calls(self) -> list[HttpCall]:
        return [c for c in self.calls if c.method != READ_METHOD]


@dataclass(frozen=True)
class ReadTool:
    """GUARD A. A callable tool. Cannot be constructed from a write entry."""

    entry: ToolManifestEntry
    transport: DomainReadTransport

    def __post_init__(self) -> None:
        if self.entry.mode != MODE_READ:
            raise ToolRegistrationRefused(
                f"'{self.entry.toolId}' has mode '{self.entry.mode}'; only read tools "
                "are directly executable (epic §3.1 rule 3)"
            )
        if self.entry.target.method != READ_METHOD:
            raise ToolRegistrationRefused(
                f"'{self.entry.toolId}' targets {self.entry.target.method}; a directly "
                "executable tool must be a GET"
            )

    @property
    def tool_id(self) -> str:
        return self.entry.toolId

    def __call__(self, args: Mapping[str, Any], bearer: str) -> Any:
        # §3.1 rule 2: the banker's JWT is forwarded on every tool call. The
        # agent can see nothing the banker could not.
        path = self.entry.target.path
        for key, value in args.items():
            path = path.replace("{" + key + "}", str(value))
        return self.transport.request(
            READ_METHOD,
            self.entry.target.service,
            path,
            {"Authorization": f"Bearer {bearer}"},
        )


class AuthorityClient:
    """The harness's ONLY write-shaped outbound call, and it creates a request.

    Deliberately not a general HTTP client: it has one method, one path, and no
    parameter through which a caller could redirect it at a domain service. A
    ``base_url`` plus a caller-supplied path would have been the natural design
    and would have made ``propose_action`` a universal write primitive one
    prompt injection away.
    """

    def __init__(self, sink: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> None:
        self._sink = sink
        self.proposals: list[Mapping[str, Any]] = []

    def propose(self, body: Mapping[str, Any], bearer: str) -> Mapping[str, Any]:
        call = dict(body)
        call["_path"] = AUTHORITY_PROPOSE_PATH
        call["_authorization"] = f"Bearer {bearer}"
        self.proposals.append(call)
        return self._sink(call)


@dataclass
class ProposeActionTool:
    """The sole write affordance. It cannot execute; it can only ask.

    Note what is NOT here: no ``transport``, no ``execute``, no ``sign``, no
    reference to a domain service of any kind. ``propose_action`` returning an
    approval in status ``proposed`` is the whole of its power. Execution belongs
    to authority-service, after human signature, behind the re-evaluation gate.
    """

    authority: AuthorityClient
    manifest: Mapping[str, ToolManifestEntry]
    tool_id: str = field(default="propose_action", init=False)

    def __call__(
        self,
        actionId: str,
        payload: Mapping[str, Any],
        evidenceRefs: Mapping[str, Any],
        bearer: str,
    ) -> Mapping[str, Any]:
        known = {e.actionId for e in self.manifest.values() if e.actionId is not None}
        if actionId not in known:
            # Fail closed. An unknown actionId must not be forwarded on the hope
            # that authority-service will recognise it — that would let the model
            # name endpoints the manifest deliberately omits (the L3 set, §3.3).
            raise ToolRegistrationRefused(
                f"actionId '{actionId}' is not in the manifest; the agent cannot name "
                "an action that was not registered"
            )
        return self.authority.propose(
            {"actionId": actionId, "payload": dict(payload), "evidenceRefs": dict(evidenceRefs)},
            bearer,
        )


class ToolRegistry:
    """The set of tools handed to the model. Nothing else reaches the agent."""

    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, tool: Any) -> None:
        if not isinstance(tool, (ReadTool, ProposeActionTool)):
            raise ToolRegistrationRefused(
                f"{type(tool).__name__} is not registrable; the harness exposes read "
                "tools and propose_action, and nothing else"
            )
        tool_id = tool.tool_id
        if tool_id in self._tools:
            raise ToolRegistrationRefused(f"duplicate tool id '{tool_id}'")
        self._tools[tool_id] = tool

    @property
    def tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def get(self, tool_id: str) -> Any:
        if tool_id not in self._tools:
            raise ToolRegistrationRefused(f"unknown tool '{tool_id}'")
        return self._tools[tool_id]

    def __len__(self) -> int:
        return len(self._tools)


def build_registry(
    entries: tuple[ToolManifestEntry, ...],
    transport: DomainReadTransport,
    authority: AuthorityClient,
) -> ToolRegistry:
    """Turn a validated manifest into the agent's tool surface.

    A ``mode == 'write'`` manifest entry is NOT an error and is NOT registered:
    it contributes its ``actionId`` to what ``propose_action`` may name, and
    nothing else. That routing is the enforcement mechanism — the write entry
    describes an action a human may authorise, never a call the agent may make.
    """
    registry = ToolRegistry()
    for entry in entries:
        if entry.is_read:
            registry.register(ReadTool(entry=entry, transport=transport))
    registry.register(
        ProposeActionTool(authority=authority, manifest={e.toolId: e for e in entries})
    )
    return registry
