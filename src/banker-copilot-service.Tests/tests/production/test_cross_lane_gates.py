"""Cross-lane gates: infrastructure, gateway and UI.

These assert properties of other people's artefacts, which is deliberate. The
invariant "agents never approve" is not held by any single service — it is held
by a Cosmos role assignment that does not include the approvals container for
writing, by a gateway that does not buffer the stream, and by a UI that cannot
send a token anywhere it gets logged. Each of those lives in a different lane,
so nobody's own test suite covers the seam.

The false pass throughout this file is a grep for a string that is present for
an unrelated reason. Each gate therefore also asserts the NEGATIVE case — the
thing that must be absent — because "the good string is present" is satisfiable
alongside the bad one.
"""

from __future__ import annotations

import re

import pytest

TF = "infra/cloud"


def _read(repo_root, relative):
    path = repo_root / relative
    assert path.exists(), f"{relative} does not exist"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Cosmos containers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "container", ["copilot-sessions", "copilot-artifacts", "copilot-traces", "copilot-approvals"]
)
def test_the_copilot_containers_are_declared(repo_root, container):
    """A trace that is not persisted is not replayable, and #333 has nothing to
    score. The lifespan log already warns about this in-process; the deployed
    system needs the container to exist."""
    assert container in _read(repo_root, f"{TF}/cosmos.tf")


def test_the_trace_container_partitions_on_the_run(repo_root):
    """Frames are read one run at a time. Partitioning on session would make a
    replay a cross-partition query over every run the banker ever started."""
    text = _read(repo_root, f"{TF}/cosmos.tf")
    block = re.search(
        r'resource\s+"azurerm_cosmosdb_sql_container"\s+"copilot_traces"\s*\{.*?\n\}',
        text,
        re.S,
    )
    assert block, "copilot_traces container block not found"
    # The PARTITION KEY specifically. `"/runId" in block` was the original
    # assertion and it was a false pass: the same block lists /runId among its
    # indexing paths, so changing the partition key to /sessionId left the test
    # green. Tamper-testing is what surfaced it.
    declared = re.search(r"partition_key_paths\s*=\s*\[([^\]]*)\]", block.group(0))
    assert declared, "copilot_traces declares no partition key"
    assert declared.group(1).strip() == '"/runId"', (
        f"copilot-traces partitions on {declared.group(1).strip()}; a replay reads one run, so "
        "any other key makes it a cross-partition query over every run the banker ever started"
    )


def test_trace_retention_is_configuration_not_a_literal(repo_root):
    """No hardcoded thresholds — the retention window is a policy decision that
    differs per environment, and a literal here is a policy decision made in
    Terraform by whoever typed fastest."""
    text = _read(repo_root, f"{TF}/cosmos.tf")
    block = re.search(
        r'resource\s+"azurerm_cosmosdb_sql_container"\s+"copilot_traces"\s*\{.*?\n\}', text, re.S
    ).group(0)
    ttl = re.search(r"default_ttl\s*=\s*(\S+)", block)
    assert ttl, "copilot_traces declares no default_ttl"
    assert ttl.group(1).startswith("var."), f"retention is hardcoded as {ttl.group(1)}"


def test_the_copilot_identity_cannot_write_the_approvals_container(repo_root):
    """The service split, expressed in Azure RBAC.

    Even if a write tool were somehow registered, the harness's identity must not
    hold Data Contributor over the approvals container. This is the layer that
    survives a code mistake.
    """
    text = _read(repo_root, f"{TF}/identity-copilot.tf")
    contributor_blocks = [
        block
        for block in re.findall(r"resource\s+\"[^\"]+\"\s+\"[^\"]+\"\s*\{.*?\n\}", text, re.S)
        if "00000000-0000-0000-0000-000000000002" in block or "Contributor" in block
    ]
    assert contributor_blocks, "no Cosmos data-plane role assignment found for the copilot identity"
    for block in contributor_blocks:
        assert "copilot-approvals" not in block and "copilot_approvals" not in block, (
            "the copilot identity holds a data CONTRIBUTOR scope that includes the approvals "
            "container. Approvals are authority-service's to write.\n" + block[:400]
        )


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


def test_the_gateway_does_not_buffer_the_copilot_stream(repo_root):
    """A buffered SSE response is a batch response. The banker sees nothing for
    the whole run and then everything at once, which reads as a hang."""
    text = _read(repo_root, "infra/local/gateway.nginx.conf")
    block = re.search(r"location\s+/api/copilot/\s*\{.*?\n\s*\}", text, re.S)
    assert block, "no /api/copilot/ location in the gateway config"
    body = block.group(0)
    assert re.search(r"proxy_buffering\s+off", body), body


def test_the_gateway_does_not_time_out_a_long_run(repo_root):
    """The default proxy_read_timeout is 60s. An agent run is longer than that,
    and a stream cut at 60s is indistinguishable to the UI from a finished run."""
    text = _read(repo_root, "infra/local/gateway.nginx.conf")
    body = re.search(r"location\s+/api/copilot/\s*\{.*?\n\s*\}", text, re.S).group(0)
    assert re.search(r"proxy_read_timeout", body), (
        "no proxy_read_timeout on the copilot location; the stream inherits nginx's 60s default"
    )


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def _ui_sources(repo_root):
    for pattern in ("src/ui-app/src/**/*.ts", "src/ui-app/src/**/*.tsx"):
        for path in repo_root.glob(pattern):
            if "node_modules" in str(path):
                continue
            yield path


def test_the_ui_never_constructs_a_native_event_source(repo_root):
    """`new EventSource(...)` cannot carry a bearer token. Every workaround for
    that is worse than the problem."""
    offenders = []
    for path in _ui_sources(repo_root):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bnew\s+EventSource\s*\(", line):
                offenders.append(f"{path.relative_to(repo_root)}:{lineno}")
    assert not offenders, offenders


def test_the_ui_stream_client_sends_the_token_in_a_header(repo_root):
    """The positive half. Absence of EventSource proves nothing if the
    replacement puts the token in the query string instead."""
    text = _read(repo_root, "src/ui-app/src/api/copilotStream.ts")
    # On a CODE line. The file's own comment explains at length why EventSource
    # cannot carry an Authorization header, so a grep of the whole file is
    # satisfied by the prose alone — a false pass that survives deleting the
    # header entirely. Tamper-testing this gate is what exposed it.
    setters = [
        line
        for line in text.splitlines()
        if re.search(r"""(headers(\.|\[['"])Authorization|['"]Authorization['"]\s*:)""", line)
        and not line.strip().startswith(("*", "//", "/*"))
    ]
    assert setters, "the stream client sets no Authorization header on any code line"
    assert not re.search(r"[?&](access_token|token|jwt)=", text), (
        "the stream client puts a token in the query string, where nginx logs it"
    )


def test_the_ui_does_not_render_an_approve_control_of_its_own(repo_root):
    """The UI may show an approval and link to it. It must not be a second place
    a signature can be produced — the signing surface is authority-service's."""
    offenders = []
    for path in _ui_sources(repo_root):
        if "copilot" not in str(path).lower():
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if re.search(r"(approvals?/[^\"'`\s]*/(sign|approve)|/execute\b)", line):
                offenders.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "a copilot component calls a signing or execution route directly:\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("banned", ["expired", "voided", "execution_failed"])
def test_no_lifecycle_state_outside_the_ratified_set_appears_in_copilot_code(repo_root, banned):
    """Epic §0.1 ratified one terminal rejection state, `denied`, with a closed
    `terminalReason` enum. A second terminal state is a second code path that has
    to be kept in agreement with the first, and they will not stay in agreement.
    """
    pattern = re.compile(r"""["']%s["']""" % banned)
    offenders = []
    roots = ["src/banker-copilot-service/app/**/*.py"]
    for glob_pattern in roots:
        for path in repo_root.glob(glob_pattern):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and "status" in line.lower():
                    offenders.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")
    assert not offenders, offenders
