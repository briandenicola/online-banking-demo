#!/usr/bin/env python3
"""Tamper harness — prove each guard by breaking it.

A test that has never been observed failing is a test nobody has evidence for.
Phase 1 found two guards that were REDUNDANT: production protected the same
property twice, so disabling either fold alone changed nothing observable. A
guard whose failure you cannot observe is not proven, however green it looks.

For each case: verify the file is byte-identical to the recorded checksum, apply
one surgical edit, run the named tests, require them to FAIL, restore, and verify
the checksum again. The restore is checksum-verified rather than trusted because
several of the targets are untracked files that `git checkout` cannot recover.

Outcomes:
  PROVEN      the named test failed while the guard was broken
  REDUNDANT   the test still passed — something else is also enforcing this, so
              this particular fold is not what the test is observing
  UNREACHABLE the edit did not apply (the code has moved on)

Usage:  python3 tamper-test.py            # run every case
        python3 tamper-test.py <id> ...   # run named cases
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SUITE = Path(__file__).resolve().parent
REPO = SUITE.parents[1]


@dataclass
class Tamper:
    id: str
    guard: str
    path: str
    find: str
    replace: str
    tests: list[str]
    note: str = ""
    original: str | None = field(default=None, repr=False)


CASES: list[Tamper] = [
    Tamper(
        id="token-algorithm-allowlist",
        guard="auth.py ALGORITHM — RS256 only; the harness holds no signing material (#334)",
        path="src/banker-copilot-service/app/auth.py",
        find='ALGORITHM = "RS256"',
        replace='ALGORITHM = "HS256"',
        tests=[
            "tests/production/test_stream_authentication.py::test_a_symmetrically_signed_token_is_refused",
        ],
        note="Algorithm confusion. With HS256 accepted, the issuer's PUBLIC key — which is "
             "published and not a secret — becomes an HMAC secret anyone can mint with. The "
             "named test forges a 'supervisor' claim that way, so this case proves the "
             "refusal is the service's own and not PyJWT declining to build the token.",
    ),
    Tamper(
        id="retired-symmetric-env-refusal",
        guard="auth.py assert_token_configuration — presence of retired signing material "
              "aborts startup instead of being ignored",
        path="src/banker-copilot-service/app/auth.py",
        find='RETIRED_ENV_VARS = ("JWT_KEY", "JWT_SECRET")',
        replace="RETIRED_ENV_VARS = ()",
        tests=[
            "tests/production/test_token_posture.py::test_a_retired_signing_secret_aborts_startup",
        ],
        note="Added after this suite's own fixtures were found still exporting JWT_KEY. The "
             "fail-closed check is what turned that from a silent downgrade into a loud stop.",
    ),
    Tamper(
        id="invoke-time-read-method",
        guard="executor.py — the read-method check at the point of action, not merely at load",
        path="src/banker-copilot-service/app/tools/executor.py",
        find="if tool.target.method not in READ_METHODS:",
        replace='if tool.target.method not in READ_METHODS and tool.target.method != "POST":',
        tests=[
            "tests/production/test_execution_path.py::test_the_executor_refuses_a_mutating_method_at_the_point_of_action",
            "tests/production/test_execution_path.py::test_no_mutating_method_reaches_the_wire_by_any_name",
        ],
        note="Deliberately a NARROW break — one method let through, the rest still refused. "
             "A suite that only ever tried POST would stay green here. The parameterised "
             "case is what makes the hole observable, so both tests are named and both "
             "must be seen to go red for the right reason.",
    ),
    Tamper(
        id="path-pattern-anchoring-probe",
        guard="manifest.py _require_confined_path_parameters — proves each declared "
              "pattern REFUSES a corpus of escape values, rather than merely existing",
        path="src/banker-copilot-service/app/tools/manifest.py",
        find="escaped = [probe for probe in _PATH_ESCAPE_PROBES if compiled.search(probe)]",
        replace="escaped = []",
        tests=[
            "tests/production/test_execution_path.py::test_an_unanchored_pattern_is_refused_by_the_loader",
        ],
        note="This is the fold that distinguishes 'a pattern is declared' from 'the pattern "
             "actually confines'. With it neutered the loader still requires a pattern, so a "
             "test that only asserted presence would stay green — which is precisely the "
             "false pass this case exists to rule out.",
    ),
    Tamper(
        id="read-method-allowlist",
        guard="manifest.py READ_METHODS — the loader's method allowlist",
        path="src/banker-copilot-service/app/tools/manifest.py",
        find='READ_METHODS: frozenset[str] = frozenset({"GET"})',
        replace='READ_METHODS: frozenset[str] = frozenset({"GET", "POST"})',
        tests=[
            "tests/production/test_registry_and_manifest.py::test_every_shipping_tool_is_a_read",
            "tests/production/test_registry_and_manifest.py::test_a_mutating_method_in_the_manifest_refuses_startup",
        ],
    ),
    Tamper(
        id="capability-scope-suffix",
        guard="manifest.py — capabilityScope must end .read",
        path="src/banker-copilot-service/app/tools/manifest.py",
        find='.endswith(".read")',
        replace='.endswith((".read", ".write"))',
        tests=["tests/production/test_registry_and_manifest.py::test_a_write_capability_scope_is_refused"],
        note="The second, independent refusal. If breaking this alone changes nothing, "
             "the method allowlist is masking it and only one guard is really observable.",
    ),
    Tamper(
        id="registry-startup-assertion",
        guard="registry.py assert_zero_write_tools — the guard that catches a tool "
              "that never went through the loader",
        path="src/banker-copilot-service/app/tools/registry.py",
        find="offending_methods = registry.methods_in_use() - READ_METHODS",
        replace="offending_methods = frozenset()",
        tests=["tests/production/test_registry_and_manifest.py::test_the_startup_assertion_catches_a_write_tool_that_bypassed_the_loader"],
    ),
    Tamper(
        id="reserved-propose-id",
        guard="registry.py — a manifest entry cannot claim the id propose_action",
        path="src/banker-copilot-service/app/tools/registry.py",
        find="PROPOSE_TOOL_ID",
        replace="_PROPOSE_TOOL_ID_DISABLED",
        tests=["tests/production/test_registry_and_manifest.py::test_the_reserved_propose_action_id_cannot_be_claimed_by_a_manifest_entry"],
        note="A blunt rename; if it does not apply cleanly the case reports UNREACHABLE "
             "rather than pretending.",
    ),
    Tamper(
        id="propose-refuses-execute",
        guard="propose.py — 'execute' is refused by name",
        path="src/banker-copilot-service/app/tools/propose.py",
        find='    "execute": (',
        replace='    "_execute_disabled": (',
        tests=["tests/production/test_propose_cannot_execute.py::test_every_self_authorising_argument_is_refused_by_name"],
    ),
    Tamper(
        id="propose-refuses-cosigner",
        guard="propose.py — 'cosignerId' is refused by name",
        path="src/banker-copilot-service/app/tools/propose.py",
        find='    "cosignerId": (',
        replace='    "_cosignerId_disabled": (',
        tests=["tests/production/test_propose_cannot_execute.py::test_every_self_authorising_argument_is_refused_by_name"],
    ),
    Tamper(
        id="propose-schema-closed",
        guard="propose.py PROPOSE_TOOL_SCHEMA additionalProperties: false",
        path="src/banker-copilot-service/app/tools/propose.py",
        find='    "required": ["actionId", "payload"],\n    "additionalProperties": False,',
        replace='    "required": ["actionId", "payload"],\n    "additionalProperties": True,',
        tests=["tests/production/test_propose_cannot_execute.py::test_the_propose_schema_admits_no_execution_argument"],
    ),
    Tamper(
        id="session-ownership",
        guard="sessions.py _load_owned_session — one banker cannot read another's session",
        path="src/banker-copilot-service/app/routes/sessions.py",
        find="    if session.actor_id != user.user_id:",
        replace="    if False:",
        tests=[
            "tests/production/test_stream_authentication.py::test_one_bankers_stream_is_not_readable_by_another_banker",
            "tests/production/test_session_and_run_are_distinct.py::test_a_run_cannot_be_started_in_another_bankers_session",
        ],
    ),
    Tamper(
        id="sse-no-buffering-header",
        guard="sessions.py — X-Accel-Buffering: no on the stream response",
        path="src/banker-copilot-service/app/routes/sessions.py",
        find='"X-Accel-Buffering": "no",',
        replace='"X-Accel-Buffering-Disabled": "no",',
        tests=["tests/production/test_stream_authentication.py::test_the_stream_declares_the_sse_content_type_and_disables_buffering"],
    ),
    Tamper(
        id="gateway-buffering",
        guard="gateway.nginx.conf — proxy_buffering off on /api/copilot/",
        path="infra/local/gateway.nginx.conf",
        find="proxy_buffering off;",
        replace="proxy_buffering on;",
        tests=["tests/production/test_cross_lane_gates.py::test_the_gateway_does_not_buffer_the_copilot_stream"],
    ),
    Tamper(
        id="ui-header-auth",
        guard="copilotStream.ts — the bearer token travels in a header",
        path="src/ui-app/src/api/copilotStream.ts",
        find="headers.Authorization",
        replace="headers.X_Disabled_Authorization",
        tests=["tests/production/test_cross_lane_gates.py::test_the_ui_stream_client_sends_the_token_in_a_header"],
    ),
    Tamper(
        id="trace-partition-key",
        guard="cosmos.tf — copilot-traces partitions on /runId",
        path="infra/cloud/cosmos.tf",
        find='partition_key_paths = ["/runId"]',
        replace='partition_key_paths = ["/sessionId"]',
        tests=["tests/production/test_cross_lane_gates.py::test_the_trace_container_partitions_on_the_run"],
    ),
    Tamper(
        id="manifest-write-tool",
        guard="config/copilot-tools.yaml — the shipping manifest itself",
        path="config/copilot-tools.yaml",
        find="apiVersion: copilot-tools/v1",
        replace="apiVersion: copilot-tools/v2",
        tests=["tests/production/test_registry_and_manifest.py::test_the_shipping_manifest_loads_and_is_not_empty"],
        note="An unknown apiVersion must refuse the whole manifest rather than "
             "guessing at a schema.",
    ),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(tests: list[str], timeout: int = 120) -> bool | None:
    """True if every named test passed, False if any failed, None if it hung.

    A hang is not a pass. A tampered guard that makes the suite hang has to be
    reported as such rather than silently blocking the harness — which is what a
    missing timeout here did the first time this was run.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *tests],
            cwd=SUITE,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    return result.returncode == 0


def main(selected: list[str]) -> int:
    cases = [c for c in CASES if not selected or c.id in selected]
    if selected and len(cases) != len(selected):
        print(f"unknown case ids: {set(selected) - {c.id for c in cases}}")
        return 2

    results = []
    for case in cases:
        target = REPO / case.path
        if not target.exists():
            results.append((case, "UNREACHABLE", "file does not exist"))
            continue

        print(f"tampering {case.id} ...", flush=True)
        original = target.read_text(encoding="utf-8")
        before = _sha(target)

        if case.find not in original:
            results.append((case, "UNREACHABLE", "anchor text not found — the code has moved"))
            continue

        # Sanity: the named tests must PASS before we break anything, or a
        # failure afterwards proves nothing about this guard.
        baseline = _run(case.tests)
        if baseline is not True:
            results.append((case, "UNREACHABLE", "the named tests do not pass before tampering"))
            print(f"  {case.id}: UNREACHABLE (baseline not green)", flush=True)
            continue

        target.write_text(original.replace(case.find, case.replace, 1), encoding="utf-8")
        try:
            still_green = _run(case.tests)
        finally:
            target.write_text(original, encoding="utf-8")
            after = _sha(target)
            if after != before:
                print(f"!!! RESTORE FAILED for {case.path}: {before} -> {after}")
                return 3

        if still_green is None:
            verdict, detail = "PROVEN", "the tampered guard made the test hang rather than fail"
        elif still_green:
            verdict, detail = "REDUNDANT", "the test still passed with the guard broken"
        else:
            verdict, detail = "PROVEN", ""
        results.append((case, verdict, detail))
        print(f"  {case.id}: {verdict}", flush=True)

    width = max(len(c.id) for c, _, _ in results)
    print()
    for case, verdict, detail in results:
        print(f"{case.id.ljust(width)}  {verdict:<12} {case.guard}")
        if detail:
            print(f"{' ' * width}  ↳ {detail}")
        if case.note and verdict != "PROVEN":
            print(f"{' ' * width}  ↳ {case.note}")

    counts = {}
    for _, verdict, _ in results:
        counts[verdict] = counts.get(verdict, 0) + 1
    print("\n" + ", ".join(f"{v}: {n}" for v, n in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
