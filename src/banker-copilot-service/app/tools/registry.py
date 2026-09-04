"""The tool registry.

Holds the registered read tools and the one built-in write affordance, ``propose_action``,
which is **not** a member of the registry — it is a separate, named attribute so that
"iterate the tools" can never accidentally include something that mutates state.

The zero-write assertion runs at load. It is expressed as a **set difference**, not a count:
``methods_in_use - READ_METHODS`` must be empty. A count is satisfied by arithmetic and a
miscount passes silently; a set-membership check names the offender and fails loudly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, resolve_service_url
from app.tools.manifest import READ_METHODS, ManifestError, ReadTool, ToolManifest

#: The one write-shaped affordance. It takes no upstream target of its own: it POSTs a proposal
#: to authority-service, which is the sole executor of agent-originated writes.
PROPOSE_TOOL_ID = "propose_action"


class WriteToolRegistrationError(ManifestError):
    """Raised when anything mutating reaches the registry. There is no recovery path."""


@dataclass(frozen=True)
class ToolRegistry:
    manifest: ToolManifest
    service_urls: dict[str, str]

    @property
    def tools(self) -> tuple[ReadTool, ...]:
        return self.manifest.tools

    @property
    def tool_ids(self) -> frozenset[str]:
        return frozenset(tool.tool_id for tool in self.tools)

    def get(self, tool_id: str) -> ReadTool | None:
        for tool in self.tools:
            if tool.tool_id == tool_id:
                return tool
        return None

    def methods_in_use(self) -> frozenset[str]:
        return frozenset(tool.target.method for tool in self.tools)

    def write_tools(self) -> tuple[ReadTool, ...]:
        """Every registered tool whose method is outside the read allowlist. Always empty."""
        return tuple(tool for tool in self.tools if tool.target.method not in READ_METHODS)

    def base_url(self, service: str) -> str:
        try:
            return self.service_urls[service]
        except KeyError as exc:  # pragma: no cover - guarded at build time
            raise WriteToolRegistrationError(f"upstream {service!r} is not configured") from exc

    def describe(self) -> list[dict]:
        """Model-facing and UI-facing tool descriptions. Never includes a resolved URL."""
        return [
            {
                "toolId": tool.tool_id,
                "displayName": tool.display_name,
                "description": tool.description,
                "capabilityScope": tool.capability_scope,
                "service": tool.target.service,
                "method": tool.target.method,
                "path": tool.target.path,
                "parameters": tool.parameters,
            }
            for tool in self.tools
        ]


def assert_zero_write_tools(registry: ToolRegistry) -> None:
    """The epic's enforcement mechanism, checked at startup.

    Two independent set-membership checks, because they fail for different reasons:
    a tool that slipped past the loader's method allowlist, and the reserved
    ``propose_action`` name being claimed by a manifest entry that would then be executed
    directly as an ordinary tool call.
    """
    offending_methods = registry.methods_in_use() - READ_METHODS
    if offending_methods:
        offenders = sorted(tool.tool_id for tool in registry.write_tools())
        raise WriteToolRegistrationError(
            f"registry contains tool(s) {offenders} using non-read method(s) "
            f"{sorted(offending_methods)}. banker-copilot-service registers ZERO write tools — "
            "the service split IS the enforcement mechanism for this epic. Route the action "
            "through propose_action and authority-service instead."
        )

    if PROPOSE_TOOL_ID in registry.tool_ids:
        raise WriteToolRegistrationError(
            f"a manifest entry claims the reserved tool id {PROPOSE_TOOL_ID!r}. The sole write "
            "affordance is built in and mediated; a manifest entry of that name would be "
            "executed directly as a read call, silently bypassing the authority ladder."
        )


def build_registry(manifest: ToolManifest, settings: Settings) -> ToolRegistry:
    """Resolve every logical upstream and assert the zero-write invariant.

    An unresolvable upstream is a startup failure rather than a tool that 500s on first use:
    a harness whose evidence-gathering fails at demo time looks identical to a harness whose
    evidence-gathering is broken, and the two want opposite responses.
    """
    service_urls: dict[str, str] = {}
    unresolved: list[str] = []

    for tool in manifest.tools:
        service = tool.target.service
        if service in service_urls:
            continue
        url = resolve_service_url(service, settings)
        if url:
            service_urls[service] = url
        else:
            unresolved.append(service)

    if unresolved:
        raise ManifestError(
            f"no base URL configured for upstream service(s) {sorted(set(unresolved))}. Set "
            "DOWNSTREAM__<service> (the convention authority-service already uses) or "
            "<SERVICE>_URL. The harness refuses to start with a tool it cannot call."
        )

    registry = ToolRegistry(manifest=manifest, service_urls=service_urls)
    assert_zero_write_tools(registry)
    return registry
