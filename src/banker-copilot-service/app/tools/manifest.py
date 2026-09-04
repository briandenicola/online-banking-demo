"""The tool manifest — read-only *by construction*.

The whole epic rests on one structural fact: `banker-copilot-service` registers **zero write
tools**. Its only write-shaped affordance is `propose_action`, which hands a proposal to
`authority-service` and cannot execute anything.

The usual way to express that is a `mode: read | write` field plus a check that no entry says
``write``. That is a *count*, and a count is satisfied by arithmetic — a miscount passes
silently. So this schema takes the stronger shape: **there is no way to spell a write.**

- There is no ``mode`` field. A tool cannot declare itself a writer.
- There is no ``actionId``, ``authority`` or ``idempotencyKeyFrom`` field. Those exist only on
  the write path, and the write path is `authority-service`.
- ``method`` is constrained to the read-method allowlist. A manifest saying ``PUT`` does not
  register a write tool — it refuses to start the service.
- Any key not on the allowlist is a startup failure, so a *future* ``mode: write`` added by
  someone who has not read this docstring is rejected by name, loudly, rather than ignored.
  A silently-ignored safety toggle is worse than no toggle.

``requiredEvidence`` is deliberately absent too, though epic §3.2 lists it. It already lives in
`config/authority-policy.yaml` under each action's ``requiredEvidence``, and `authority-service`
re-validates it server-side at propose time. Restating it here would create a second copy of an
authorization-relevant fact, which is the defect class that cost Phase 1 a privilege escalation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from app.config import ConfigurationError
from app.tools.redaction import RedactionPathError, validate_paths

#: HTTP methods a registered tool may use. Membership in this set *is* the read/write boundary.
READ_METHODS: frozenset[str] = frozenset({"GET"})

SUPPORTED_API_VERSION = "copilot-tools/v1"

_ALLOWED_TOP_LEVEL = frozenset({"apiVersion", "metadata", "tools"})
_ALLOWED_TOOL_KEYS = frozenset(
    {"toolId", "displayName", "description", "target", "parameters", "capabilityScope", "redaction"}
)
_ALLOWED_TARGET_KEYS = frozenset({"service", "method", "path", "timeoutMs"})

#: Keys that must never appear. Each is rejected *by name* with the reason, because a key that
#: is silently ignored looks exactly like a key that works.
_REFUSED_TOOL_KEYS: dict[str, str] = {
    "mode": (
        "'mode' does not exist in this schema. Read/write is not a per-tool declaration here — "
        "the harness registers read tools only, and the sole write affordance is propose_action, "
        "which is built in rather than declared."
    ),
    "actionId": (
        "'actionId' belongs to the authority ladder, not the harness manifest. Action types are "
        "declared in config/authority-policy.yaml and owned by authority-service."
    ),
    "authority": (
        "'authority' (declaredRung/policyRef) is authority-service's contract. Restating a rung "
        "here would create a second, driftable copy of the ladder."
    ),
    "idempotencyKeyFrom": (
        "'idempotencyKeyFrom' is a write-path concern. No tool registered here writes."
    ),
    "requiredEvidence": (
        "'requiredEvidence' is declared per action type in config/authority-policy.yaml and "
        "re-validated server-side by authority-service. One copy, one owner."
    ),
    "cosignerId": (
        "'cosignerId' is deleted from this system. Naming a co-signer in advance lets the "
        "requester choose their own reviewer — the exact self-dealing pattern L2 prevents."
    ),
}

_PATH_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_TOOL_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class ManifestError(ConfigurationError):
    """A manifest that cannot be trusted. Always fatal at startup."""


@dataclass(frozen=True)
class ToolTarget:
    service: str
    method: str
    path: str
    timeout_ms: int

    @property
    def path_params(self) -> frozenset[str]:
        return frozenset(_PATH_PARAM.findall(self.path))


@dataclass(frozen=True)
class ReadTool:
    """A registered tool. There is no write counterpart to this class anywhere in the service."""

    tool_id: str
    display_name: str
    description: str
    target: ToolTarget
    parameters: dict[str, Any]
    capability_scope: str
    redaction: tuple[str, ...] = ()

    @property
    def is_read(self) -> bool:
        return self.target.method in READ_METHODS


@dataclass(frozen=True)
class ToolManifest:
    api_version: str
    manifest_id: str
    tools: tuple[ReadTool, ...] = field(default_factory=tuple)


def _require_mapping(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise ManifestError(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _reject_unknown(keys, allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(keys) - allowed)
    if unknown:
        raise ManifestError(
            f"{where} declares unknown key(s) {unknown}. The manifest loader fails closed: "
            "an entry it does not fully understand is refused, never skipped."
        )


def _parse_target(raw: Any, tool_id: str) -> ToolTarget:
    target = _require_mapping(raw, f"tool {tool_id!r} 'target'")
    _reject_unknown(target.keys(), _ALLOWED_TARGET_KEYS, f"tool {tool_id!r} 'target'")

    for required in ("service", "method", "path"):
        if not str(target.get(required, "")).strip():
            raise ManifestError(f"tool {tool_id!r} 'target.{required}' is required")

    method = str(target["method"]).strip().upper()
    if method not in READ_METHODS:
        raise ManifestError(
            f"tool {tool_id!r} declares target.method={method!r}, which is not in the read-method "
            f"allowlist {sorted(READ_METHODS)}. The harness cannot register a tool that mutates "
            "state: the only write affordance is propose_action, routed to authority-service."
        )

    path = str(target["path"]).strip()
    if not path.startswith("/"):
        raise ManifestError(f"tool {tool_id!r} 'target.path' must be an absolute path")

    timeout_ms = target.get("timeoutMs")
    if timeout_ms is None:
        raise ManifestError(
            f"tool {tool_id!r} must declare 'target.timeoutMs'. An unbounded upstream call "
            "stalls the planner loop and the live trace with it."
        )
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
        raise ManifestError(f"tool {tool_id!r} 'target.timeoutMs' must be a positive integer")

    return ToolTarget(
        service=str(target["service"]).strip().lower(),
        method=method,
        path=path,
        timeout_ms=timeout_ms,
    )


# A path parameter is confined by proving its declared pattern REFUSES a corpus of hostile values,
# not by reading the pattern and reasoning about it. JSON Schema `pattern` is a SEARCH, not a full
# match, so an innocent-looking `[a-z0-9]+` happily matches "../../admin" — the anchoring mistake is
# invisible by inspection and obvious against a probe. Each probe is a way to leave the declared
# path: traversal, an extra segment, an encoded separator, a query or fragment splice, or an empty
# value that collapses the segment and resolves a different endpoint.
_PATH_ESCAPE_PROBES = (
    "",
    "..",
    "../admin",
    "../../admin/whatever",
    "a/b",
    "/absolute",
    "a%2fb",
    "%2e%2e%2f",
    "..%2Fadmin",
    "a\\b",
    "a?query=1",
    "a#fragment",
    "a b",
    "a\nb",
    "a\rb",
    "a\x00b",
    "http://elsewhere.invalid/x",
)


def _require_confined_path_parameters(
    tool_id: str, target: "ToolTarget", parameters: dict[str, Any]
) -> None:
    """Refuse any tool whose path parameters are not provably confined to one path segment.

    The declared path IS the capability scope. If an argument can leave it, the scope is advisory,
    and tool arguments are model-controlled while tool output re-enters model context — so an
    unconstrained path parameter is reachable by prompt injection. Enforced here, at load, rather
    than at substitution time: a manifest that cannot EXPRESS an unconstrained path parameter is
    structurally safer than a substitution routine that has to remember to sanitise. Same reasoning
    as making write tools unregistrable rather than merely absent.
    """
    properties = parameters.get("properties") or {}

    for name in sorted(target.path_params):
        schema = properties.get(name)
        if not isinstance(schema, dict):
            raise ManifestError(
                f"tool {tool_id!r} path parameter {name!r} has no schema object"
            )
        if schema.get("type") != "string":
            raise ManifestError(
                f"tool {tool_id!r} path parameter {name!r} must declare type: string; a "
                f"non-string is stringified on substitution and escapes its own validation"
            )

        pattern = schema.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            raise ManifestError(
                f"tool {tool_id!r} path parameter {name!r} declares no 'pattern'. Every path "
                f"parameter must constrain itself to a single path segment, because "
                f"{target.path!r} is this tool's capability scope and an unconstrained argument "
                "walks out of it. Add an anchored pattern such as '^[A-Za-z0-9_-]{1,64}$'."
            )
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ManifestError(
                f"tool {tool_id!r} path parameter {name!r} pattern {pattern!r} is not a valid "
                f"regular expression: {exc}"
            ) from exc

        escaped = [probe for probe in _PATH_ESCAPE_PROBES if compiled.search(probe)]
        if escaped:
            raise ManifestError(
                f"tool {tool_id!r} path parameter {name!r} pattern {pattern!r} accepts "
                f"{escaped!r}, which leave the declared path {target.path!r}. JSON Schema "
                "'pattern' is a search, not a full match — anchor it with ^ and $."
            )


def _parse_tool(raw: Any, index: int) -> ReadTool:
    entry = _require_mapping(raw, f"tools[{index}]")

    for refused, reason in _REFUSED_TOOL_KEYS.items():
        if refused in entry:
            raise ManifestError(f"tools[{index}] declares refused key '{refused}': {reason}")

    _reject_unknown(entry.keys(), _ALLOWED_TOOL_KEYS, f"tools[{index}]")

    tool_id = str(entry.get("toolId", "")).strip()
    if not _TOOL_ID.match(tool_id):
        raise ManifestError(
            f"tools[{index}] 'toolId' must be snake_case matching {_TOOL_ID.pattern!r}, "
            f"got {tool_id!r}"
        )

    for required in ("displayName", "description", "capabilityScope"):
        if not str(entry.get(required, "")).strip():
            raise ManifestError(f"tool {tool_id!r} '{required}' is required")

    capability_scope = str(entry["capabilityScope"]).strip()

    # Target is parsed BEFORE the scope check on purpose. Both refuse a write, and when an
    # entry trips both, the method is the more fundamental fact — and a rule that can only
    # ever fire behind another rule is a rule nobody can observe working.
    target = _parse_target(entry.get("target"), tool_id)

    if not capability_scope.endswith(".read"):
        raise ManifestError(
            f"tool {tool_id!r} declares capabilityScope={capability_scope!r}. Registered tools "
            "carry read scopes only; a write scope is not registrable here."
        )

    parameters = _require_mapping(entry.get("parameters"), f"tool {tool_id!r} 'parameters'")
    if parameters.get("type") != "object":
        raise ManifestError(f"tool {tool_id!r} 'parameters' must be a JSON Schema object type")
    if parameters.get("additionalProperties", True) is not False:
        raise ManifestError(
            f"tool {tool_id!r} 'parameters' must set additionalProperties: false. An open "
            "parameter object lets the model smuggle unvalidated input into an upstream call."
        )

    declared = set((parameters.get("properties") or {}).keys())
    required_params = set(parameters.get("required") or [])

    missing_props = sorted(required_params - declared)
    if missing_props:
        raise ManifestError(
            f"tool {tool_id!r} lists required parameter(s) {missing_props} that are not declared "
            "in 'properties'"
        )

    unbound = sorted(target.path_params - declared)
    if unbound:
        raise ManifestError(
            f"tool {tool_id!r} path {target.path!r} references {unbound}, which no parameter "
            "supplies. A template hole filled from nowhere is a request to the wrong URL."
        )

    optional_path_params = sorted(target.path_params - required_params)
    if optional_path_params:
        raise ManifestError(
            f"tool {tool_id!r} path parameter(s) {optional_path_params} are optional. A path "
            "segment must always be present or the call resolves to a different endpoint."
        )

    _require_confined_path_parameters(tool_id, target, parameters)

    redaction = entry.get("redaction") or []
    if not isinstance(redaction, list) or any(not isinstance(item, str) for item in redaction):
        raise ManifestError(f"tool {tool_id!r} 'redaction' must be a list of JSONPath strings")

    try:
        validate_paths(redaction)
    except RedactionPathError as exc:
        raise ManifestError(
            f"tool {tool_id!r} declares an unusable redaction path: {exc}. A redaction rule that "
            "matches nothing looks exactly like one that worked."
        ) from exc

    return ReadTool(
        tool_id=tool_id,
        display_name=str(entry["displayName"]).strip(),
        description=str(entry["description"]).strip(),
        target=target,
        parameters=parameters,
        capability_scope=capability_scope,
        redaction=tuple(redaction),
    )


def parse_manifest(document: Any) -> ToolManifest:
    """Parse an already-deserialized manifest. Raises :class:`ManifestError` on anything unclear."""
    root = _require_mapping(document, "manifest root")
    _reject_unknown(root.keys(), _ALLOWED_TOP_LEVEL, "manifest root")

    api_version = str(root.get("apiVersion", "")).strip()
    if api_version != SUPPORTED_API_VERSION:
        raise ManifestError(
            f"manifest apiVersion is {api_version!r}; this service understands only "
            f"{SUPPORTED_API_VERSION!r}. Refusing to guess at an unknown schema."
        )

    metadata = _require_mapping(root.get("metadata") or {}, "manifest 'metadata'")
    manifest_id = str(metadata.get("manifestId", "")).strip()
    if not manifest_id:
        raise ManifestError("manifest 'metadata.manifestId' is required")

    raw_tools = root.get("tools")
    if not isinstance(raw_tools, list) or not raw_tools:
        raise ManifestError("manifest 'tools' must be a non-empty list")

    tools = tuple(_parse_tool(entry, index) for index, entry in enumerate(raw_tools))

    seen: dict[str, int] = {}
    for position, tool in enumerate(tools):
        if tool.tool_id in seen:
            raise ManifestError(
                f"duplicate toolId {tool.tool_id!r} at tools[{position}] (first seen at "
                f"tools[{seen[tool.tool_id]}]). Two entries for one name means one of them is "
                "silently unreachable."
            )
        seen[tool.tool_id] = position

    return ToolManifest(api_version=api_version, manifest_id=manifest_id, tools=tools)


def load_manifest(path: str) -> ToolManifest:
    """Read and parse the manifest file. A missing or malformed file aborts startup."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise ManifestError(
            f"Tool manifest not found at {path!r}. A harness that starts without its manifest "
            "would be a harness with undefined affordances; refusing to start."
        ) from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"Tool manifest at {path!r} is not valid YAML: {exc}") from exc

    return parse_manifest(document)
