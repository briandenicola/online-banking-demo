"""Tool manifest loader — fail-closed, per epic §3.1 rule 4 and §3.2.

    "A tool with a missing or unknown ``actionId`` fails registration at service
    start. Fail closed, loudly."

The load-bearing word is *loudly*. The failure mode this module is built to make
impossible is the quiet one: a loader that validates each entry, logs a warning
for the bad ones, and registers the rest. That loader passes every test that
asks "are the good tools present?" while shipping a harness whose tool surface
silently differs from the reviewed manifest — which is precisely the artefact
the whole authority argument rests on.

So there is exactly one entry point, it is all-or-nothing, and a partially
valid manifest yields NO registry at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

MODE_READ = "read"
MODE_WRITE = "write"
MODES = (MODE_READ, MODE_WRITE)

# Epic §4.3: the rung total order. L3 is outside the harness entirely — the
# agent may not even propose at L3 — so a manifest entry declaring L3 is a
# manifest that should not load, not a tool that gets hidden at runtime.
RUNGS = ("L1", "L2", "L3")
PROPOSABLE_RUNGS = ("L1", "L2")

# Epic §3.1 rule 1: tools call REST. Read tools execute directly; a read tool is
# a GET. Anything else is a write wearing a read's clothes.
READ_METHOD = "GET"
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

REQUIRED_FIELDS = frozenset(
    {
        "toolId",
        "displayName",
        "description",
        "mode",
        "actionId",
        "authority",
        "target",
        "parameters",
        "requiredEvidence",
        "capabilityScope",
        "redaction",
    }
)

# ``idempotencyKeyFrom`` is write-only (§3.2), and ``$schema`` may ride along on
# the document. Everything else is unknown, and unknown is fatal.
OPTIONAL_FIELDS = frozenset({"idempotencyKeyFrom", "$schema"})
KNOWN_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

AUTHORITY_FIELDS = frozenset({"declaredRung", "policyRef"})
TARGET_FIELDS = frozenset({"service", "method", "path", "timeoutMs"})

# Epic §0.1: ``<domain>.<entity>.<verb>`` or ``<domain>.<verb>``. Action ids are
# POLICY LOOKUP KEYS, so a typo is a silent policy miss rather than a compile
# error. That is the entire reason this regex exists at load time.
ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$")
TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Epic §3.3: deliberately not exposed as tools, at any rung. These are the L3
# set; "they are absent from the manifest entirely; the agent cannot even name
# them." A loader that merely refused to *execute* them would still have put
# their names into the model's context.
FORBIDDEN_TARGET_PATHS = (
    "/api/admin/users/{id}",
    "/api/admin/promote",
    "/api/admin/users/{id}/reset-password",
    "/api/admin/replay-events",
)


class ManifestError(ValueError):
    """Raised for any defect in any entry. Refuses the whole manifest."""


@dataclass(frozen=True)
class Authority:
    declaredRung: str
    policyRef: str


@dataclass(frozen=True)
class Target:
    service: str
    method: str
    path: str
    timeoutMs: int


@dataclass(frozen=True)
class ToolManifestEntry:
    toolId: str
    displayName: str
    description: str
    mode: str
    actionId: str | None
    authority: Authority
    target: Target
    parameters: Mapping[str, Any]
    requiredEvidence: tuple[str, ...]
    capabilityScope: str
    redaction: tuple[str, ...]
    idempotencyKeyFrom: tuple[str, ...] = field(default=())

    @property
    def is_read(self) -> bool:
        return self.mode == MODE_READ

    @property
    def is_write(self) -> bool:
        return self.mode == MODE_WRITE


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"{what} must be an object, got {type(value).__name__}")
    return value


def _require_str(entry: Mapping[str, Any], key: str, what: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{what}: '{key}' must be a non-empty string")
    return value


def _require_str_list(entry: Mapping[str, Any], key: str, what: str) -> tuple[str, ...]:
    value = entry.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ManifestError(f"{what}: '{key}' must be an array")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ManifestError(f"{what}: '{key}' must contain only non-empty strings")
    return tuple(value)


def _parse_entry(raw: Any, index: int) -> ToolManifestEntry:
    entry = _require_mapping(raw, f"manifest entry {index}")
    what = f"manifest entry {index}"

    unknown = set(entry) - KNOWN_FIELDS
    if unknown:
        # An unknown key is the shape of a typo, and a typo'd flag is exactly
        # how a write tool sneaks past a loader that ignores what it does not
        # recognise. Refuse it.
        raise ManifestError(f"{what}: unknown manifest field(s) {sorted(unknown)}")

    missing = REQUIRED_FIELDS - set(entry)
    if missing:
        raise ManifestError(f"{what}: missing required field(s) {sorted(missing)}")

    tool_id = _require_str(entry, "toolId", what)
    if not TOOL_ID_RE.match(tool_id):
        raise ManifestError(f"{what}: toolId '{tool_id}' is not stable snake_case")
    what = f"tool '{tool_id}'"

    _require_str(entry, "displayName", what)
    _require_str(entry, "description", what)

    mode = entry["mode"]
    if mode not in MODES:
        raise ManifestError(f"{what}: mode must be one of {list(MODES)}, got {mode!r}")

    authority = _require_mapping(entry["authority"], f"{what}: authority")
    if set(authority) != AUTHORITY_FIELDS:
        raise ManifestError(
            f"{what}: authority must have exactly {sorted(AUTHORITY_FIELDS)}, "
            f"got {sorted(authority)}"
        )
    declared_rung = authority["declaredRung"]
    if declared_rung not in RUNGS:
        raise ManifestError(f"{what}: declaredRung {declared_rung!r} is not a rung")
    if declared_rung not in PROPOSABLE_RUNGS:
        raise ManifestError(
            f"{what}: declaredRung L3 is not proposable (epic §4.3); an L3 action "
            "must be absent from the manifest, not present and refused"
        )
    policy_ref = _require_str(authority, "policyRef", f"{what}: authority")

    target = _require_mapping(entry["target"], f"{what}: target")
    if set(target) != TARGET_FIELDS:
        raise ManifestError(
            f"{what}: target must have exactly {sorted(TARGET_FIELDS)}, got {sorted(target)}"
        )
    method = target["method"]
    if method not in (READ_METHOD, *WRITE_METHODS):
        raise ManifestError(f"{what}: target.method {method!r} is not an HTTP method")
    timeout = target["timeoutMs"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ManifestError(f"{what}: target.timeoutMs must be a positive integer")
    path = _require_str(target, "path", f"{what}: target")
    if path in FORBIDDEN_TARGET_PATHS:
        raise ManifestError(
            f"{what}: target.path '{path}' is in the L3 set (epic §3.3) and must not "
            "appear in the manifest at any rung"
        )

    action_id = entry["actionId"]
    if mode == MODE_READ:
        if action_id is not None:
            raise ManifestError(f"{what}: actionId must be null iff mode == 'read'")
        if method != READ_METHOD:
            raise ManifestError(
                f"{what}: a read tool executes directly, so its method must be "
                f"{READ_METHOD}, not {method}"
            )
    else:
        if not isinstance(action_id, str) or not ACTION_ID_RE.match(action_id):
            raise ManifestError(
                f"{what}: a write tool needs an actionId of the form "
                "<domain>.<entity>.<verb>; a missing or malformed one is a silent "
                "policy miss"
            )
        if method == READ_METHOD:
            raise ManifestError(f"{what}: a write tool must not declare method GET")

    _require_mapping(entry["parameters"], f"{what}: parameters")
    required_evidence = _require_str_list(entry, "requiredEvidence", what)
    capability_scope = _require_str(entry, "capabilityScope", what)
    redaction = _require_str_list(entry, "redaction", what)
    for jsonpath in redaction:
        if not jsonpath.startswith("$"):
            raise ManifestError(f"{what}: redaction entry {jsonpath!r} is not a JSONPath")

    idem = entry.get("idempotencyKeyFrom", ())
    if mode == MODE_WRITE:
        idem = _require_str_list(entry, "idempotencyKeyFrom", what)
        if not idem:
            raise ManifestError(f"{what}: a write tool must declare idempotencyKeyFrom")
    elif "idempotencyKeyFrom" in entry:
        raise ManifestError(f"{what}: idempotencyKeyFrom is write-only")

    return ToolManifestEntry(
        toolId=tool_id,
        displayName=entry["displayName"],
        description=entry["description"],
        mode=mode,
        actionId=action_id,
        authority=Authority(declaredRung=declared_rung, policyRef=policy_ref),
        target=Target(
            service=_require_str(target, "service", f"{what}: target"),
            method=method,
            path=path,
            timeoutMs=timeout,
        ),
        parameters=entry["parameters"],
        requiredEvidence=required_evidence,
        capabilityScope=capability_scope,
        redaction=redaction,
        idempotencyKeyFrom=tuple(idem),
    )


def load_manifest(raw: Any) -> tuple[ToolManifestEntry, ...]:
    """Parse and validate a whole manifest, or raise. There is no middle result.

    All-or-nothing is the point. A loader returning ``(good_entries, errors)``
    hands the caller a decision it will get wrong under deadline.
    """
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ManifestError("manifest must be an array of tool entries")
    if len(raw) == 0:
        # An empty manifest starts a harness with no tools. It also makes every
        # "no write tool is registered" assertion vacuously true, which is the
        # exact false pass this suite is built around. Refuse it.
        raise ManifestError("manifest is empty; a harness with no tools is not a harness")

    entries = tuple(_parse_entry(item, i) for i, item in enumerate(raw))

    seen: set[str] = set()
    for entry in entries:
        if entry.toolId in seen:
            raise ManifestError(f"duplicate toolId '{entry.toolId}'")
        seen.add(entry.toolId)

    action_ids: set[str] = set()
    for entry in entries:
        if entry.actionId is None:
            continue
        if entry.actionId in action_ids:
            raise ManifestError(f"duplicate actionId '{entry.actionId}'")
        action_ids.add(entry.actionId)

    for entry in entries:
        for evidence_tool in entry.requiredEvidence:
            if evidence_tool not in seen:
                raise ManifestError(
                    f"tool '{entry.toolId}' requires evidence from unknown tool "
                    f"'{evidence_tool}'; an unresolvable evidence reference makes "
                    "requiredEvidence unsatisfiable, so the tool could never be proposed"
                )
            if evidence_tool == entry.toolId:
                raise ManifestError(f"tool '{entry.toolId}' requires itself as evidence")

    for entry in entries:
        if entry.is_write and not entry.requiredEvidence:
            raise ManifestError(
                f"write tool '{entry.toolId}' declares no requiredEvidence; "
                "requiredEvidence is the teeth behind 'agents gather evidence' (§3.2)"
            )

    return entries
