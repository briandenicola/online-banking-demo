"""Shared fixtures. Note what is NOT here: a copied manifest fixture.

Phase 1's most expensive lesson was ``ProductionRoleModelTests`` — two tests
that asserted ``admin`` IS a signer role with ascending seniority. They were
internally coherent, they passed, and they encoded the vulnerable model. They
would have DEFENDED the bug.

The mechanism behind that failure is copying: an expectation transcribed by
hand into a test drifts from the ratified document, and once it has drifted, it
is the test that wins. So the fixtures below parse the SPEC TEXT — epic §3.3's
worked manifest, the UI design §4.2 event-kind union — out of the documents
themselves. If a document changes, these tests see the change. If a document
becomes unparseable, that is a failure and not a skip.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_ROOT))


def _find_repo_root() -> Path:
    d = TESTS_ROOT
    while d != d.parent:
        if (d / ".git").exists():
            return d
        d = d.parent
    raise RuntimeError("repository root not found")


REPO_ROOT = _find_repo_root()
EPIC = REPO_ROOT / "docs" / "epics" / "banker-copilot.md"
UI_DESIGN = REPO_ROOT / "docs" / "design" / "banker-copilot-ui.md"
POLICY_DESIGN = REPO_ROOT / "docs" / "design" / "banker-copilot-policy-engine.md"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def _strip_jsonc(text: str) -> str:
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        # Only trailing comments; none of the manifest's string values contain '//'.
        out.append(re.sub(r"\s+//.*$", "", line))
    return "\n".join(out)


def _fenced_block_after(path: Path, heading: str, lang: str) -> str:
    text = path.read_text(encoding="utf-8")
    idx = text.find(heading)
    if idx < 0:
        raise AssertionError(
            f"heading {heading!r} not found in {path.name}; the spec moved and every "
            "expectation derived from it is now unverified"
        )
    fence = f"```{lang}"
    start = text.find(fence, idx)
    if start < 0:
        raise AssertionError(f"no {lang} block under {heading!r} in {path.name}")
    body_start = start + len(fence)
    end = text.find("```", body_start)
    if end < 0:
        raise AssertionError(f"unterminated {lang} block under {heading!r} in {path.name}")
    return text[body_start:end]


def load_worked_manifest() -> list[dict]:
    """Epic §3.3 — the six real endpoints, parsed from the epic itself."""
    block = _fenced_block_after(EPIC, "### 3.3 Worked manifest", "jsonc")
    return json.loads(_strip_jsonc(block))


def load_ui_event_kinds() -> list[str]:
    """UI design §4.2 — the ``CopilotEventKind`` union, parsed from the design."""
    block = _fenced_block_after(UI_DESIGN, "### 4.2 Event envelope", "ts")
    union = re.search(r"export type CopilotEventKind\s*=(.*?);", block, re.S)
    if union is None:
        raise AssertionError("CopilotEventKind union not found in UI design §4.2")
    return re.findall(r"'([a-z][a-z.]*)'", union.group(1))


@pytest.fixture
def manifest_section_3_3() -> list[dict]:
    """Epic §3.3 EXACTLY as printed — six entries, nothing added."""
    return copy.deepcopy(load_worked_manifest())


# Epic Phase 2 bullet: "Read tools for the six manifest entries in §3.3 plus
# `get_account`, `get_transfer`, `get_user`, `get_account_application`,
# `get_application_audit`, `get_scored_transaction`." The epic names these six
# read tools but never prints their manifest entries, so they are synthesised
# here as TEST SCAFFOLDING. They are not an expectation about anyone's code —
# they exist only so the evidence graph in §3.3 can close (see
# test_manifest_fail_closed::test_section_3_3_alone_does_not_load, which is the
# finding this scaffolding works around).
def load_phase2_extra_read_tool_ids() -> list[str]:
    text = EPIC.read_text(encoding="utf-8")
    idx = text.find("- Read tools for the six manifest entries in §3.3 plus")
    if idx < 0:
        raise AssertionError(
            "the Phase 2 read-tool bullet moved; the synthesised scaffolding below is no "
            "longer anchored to the spec"
        )
    return re.findall(r"`([a-z_]+)`", text[idx : text.find("\n-", idx + 1)])


def _synthesised_read(tool_id: str) -> dict:
    return {
        "toolId": tool_id,
        "displayName": tool_id.replace("_", " "),
        "description": f"Test scaffolding for {tool_id} (epic Phase 2 bullet).",
        "mode": "read",
        "actionId": None,
        "authority": {"declaredRung": "L1", "policyRef": "read.any"},
        "target": {
            "service": "scaffolding",
            "method": "GET",
            "path": f"/api/scaffolding/{tool_id}",
            "timeoutMs": 8000,
        },
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "requiredEvidence": [],
        "capabilityScope": "scaffolding.read",
        "redaction": [],
    }


@pytest.fixture
def worked_manifest() -> list[dict]:
    # A deep copy per test: several tests tamper with their copy on purpose, and
    # a shared mutable fixture would make the suite order-dependent — which is
    # its own species of false pass.
    entries = copy.deepcopy(load_worked_manifest())
    present = {e["toolId"] for e in entries}
    for tool_id in load_phase2_extra_read_tool_ids():
        if tool_id not in present:
            entries.append(_synthesised_read(tool_id))
    return entries


@pytest.fixture(scope="session")
def ui_event_kinds() -> list[str]:
    return load_ui_event_kinds()


@pytest.fixture
def fixed_clock():
    counter = {"n": 0}

    def clock() -> str:
        counter["n"] += 1
        return f"2026-09-04T00:00:{counter['n']:02d}Z"

    return clock
