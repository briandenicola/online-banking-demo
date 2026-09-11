"""The projection ENGINE — four verbs, and a closed door on everything else.

This file tests an implementation, not a seam. The seam — "does the projected shape actually
satisfy `authority-policy.yaml`?" — is held in C# by
`authority-service.UnitTests/EvidenceContractSeamTests`, because that test can call the REAL
`PolicyEvaluator.EvidenceComplete` instead of restating it in a second language. A Python test
asserting "the projected object contains the required fields" would be a third document that can
drift from both, and it would keep passing if `EvidenceComplete` were ever strengthened.
(Gate B ruling §R7.)
"""

from __future__ import annotations

import pytest

from app.tools.manifest import ManifestError, parse_manifest
from app.tools.projection import ProjectionError, parse_projection, project

REQUIRED = frozenset({"accountId"})


def rules(block, required=REQUIRED, tool_id="t"):
    return parse_projection(block, tool_id, required)


# ---------------------------------------------------------------- the four verbs ----


def test_rename_adds_a_more_specific_name_and_keeps_the_original():
    projected = project(
        {"id": "acct-1", "balance": 100}, rules({"accountId": {"rename": "id"}}), {}
    )

    assert projected["accountId"] == "acct-1"
    # Lossless: the original field survives the rename.
    assert projected["id"] == "acct-1"
    assert projected["balance"] == 100


def test_bind_takes_the_value_from_the_tools_own_argument():
    projected = project(
        [{"id": "txn-1"}],
        rules(
            {
                "accountId": {"bind": "$args.accountId"},
                "items": {"collect": "$"},
            }
        ),
        {"accountId": "acct-9"},
    )

    assert projected["accountId"] == "acct-9"


def test_count_is_the_arity_and_collect_keeps_the_whole_array():
    document = [{"id": "txn-1"}, {"id": "txn-2"}, {"id": "txn-3"}]

    projected = project(
        document,
        rules({"count": {"count": "$"}, "items": {"collect": "$"}}),
        {},
    )

    assert projected["count"] == 3
    assert projected["items"] == document


def test_projection_is_lossless_for_an_object_response():
    document = {"id": "acct-1", "balance": 100, "currency": "USD", "isActive": True}

    projected = project(document, rules({"accountId": {"rename": "id"}}), {})

    for key, value in document.items():
        assert projected[key] == value


# ------------------------------------------------------------- refused at load ----


@pytest.mark.parametrize(
    "verb",
    ["literal", "const", "value", "default", "filter", "where", "select", "first"],
)
def test_literals_defaults_and_filters_are_refused_by_name(verb):
    with pytest.raises(ProjectionError) as exc:
        rules({"x": {verb: "anything"}})

    assert verb in str(exc.value)


@pytest.mark.parametrize("verb", ["if", "when", "predicate", "sum", "expr", "template"])
def test_conditionals_and_arithmetic_are_refused_by_name(verb):
    with pytest.raises(ProjectionError) as exc:
        rules({"x": {verb: "anything"}})

    assert verb in str(exc.value)


@pytest.mark.parametrize("verb", ["tool", "evidence"])
def test_cross_tool_references_are_refused_by_name(verb):
    with pytest.raises(ProjectionError) as exc:
        rules({"x": {verb: "get_account.id"}})

    assert verb in str(exc.value)


def test_an_unknown_verb_is_refused_rather_than_skipped():
    with pytest.raises(ProjectionError) as exc:
        rules({"x": {"transmogrify": "$"}})

    assert "closed" in str(exc.value)


def test_two_verbs_on_one_key_is_a_computation_and_is_refused():
    with pytest.raises(ProjectionError):
        rules({"x": {"rename": "id", "count": "$"}})


def test_rename_will_not_walk_a_path():
    with pytest.raises(ProjectionError):
        rules({"accountId": {"rename": "account.id"}})


def test_count_of_a_sub_selection_is_a_filter_and_is_refused():
    with pytest.raises(ProjectionError):
        rules({"count": {"count": "$.items"}, "items": {"collect": "$"}})


def test_count_without_collect_is_an_unfalsifiable_claim():
    with pytest.raises(ProjectionError) as exc:
        rules({"count": {"count": "$"}})

    assert "lossless" in str(exc.value).lower()


# ------------------------------------------------- the payload is the hard boundary ----


@pytest.mark.parametrize("verb", ["payload", "facts"])
def test_payload_and_facts_verbs_are_refused_by_name(verb):
    with pytest.raises(ProjectionError) as exc:
        rules({"userId": {verb: "userId"}})

    assert "self-attesting" in str(exc.value) or "payload" in str(exc.value)


@pytest.mark.parametrize("operand", ["$payload.userId", "$facts.userId"])
def test_bind_cannot_reach_the_proposal_payload(operand):
    """The security boundary. `$args` is a statement about the HTTP call that actually happened
    and the trace can be used to check it; the payload is the proposer's own claim, and evidence
    derived from it would let the proposer justify itself."""
    with pytest.raises(ProjectionError) as exc:
        rules({"userId": {"bind": operand}})

    assert "self-attesting" in str(exc.value)


def test_bind_is_confined_to_a_required_parameter_of_its_own_tool():
    """§R5, made unspellable rather than merely documented.

    `list_login_audits` filters by recency, not by user: `userId` is not one of its parameters.
    A projection that could bind it would put "here are user X's N recent logins" into an audit
    record when the truth is "here are the last N logins of anybody at all".
    """
    with pytest.raises(ProjectionError) as exc:
        parse_projection(
            {"userId": {"bind": "$args.userId"}, "items": {"collect": "$"}},
            "list_login_audits",
            frozenset({"limit"}),  # the tool's real required set is even narrower: empty
        )

    assert "scoped" in str(exc.value)


def test_bind_of_an_optional_parameter_is_refused():
    with pytest.raises(ProjectionError):
        parse_projection(
            {"limit": {"bind": "$args.limit"}, "items": {"collect": "$"}},
            "list_login_audits",
            frozenset(),
        )


# --------------------------------------------------------- refused at apply time ----


def test_a_projection_may_not_overwrite_material_the_response_carries():
    with pytest.raises(ProjectionError) as exc:
        project({"id": "acct-1", "accountId": "someone-else"}, rules({"accountId": {"rename": "id"}}), {})

    assert "overwrite" in str(exc.value)


def test_renaming_a_field_the_service_did_not_return_fails_loudly():
    with pytest.raises(ProjectionError):
        project({"balance": 100}, rules({"accountId": {"rename": "id"}}), {})


def test_an_array_response_without_collect_cannot_be_projected():
    with pytest.raises(ProjectionError):
        project([{"id": "txn-1"}], rules({"accountId": {"bind": "$args.accountId"}}), {"accountId": "a"})


def test_collect_declared_against_an_object_response_fails_loudly():
    with pytest.raises(ProjectionError):
        project({"id": "acct-1"}, rules({"items": {"collect": "$"}}), {})


# ------------------------------------------------------ fatal at manifest load ----


def _manifest(projection):
    return {
        "apiVersion": "copilot-tools/v1",
        "metadata": {"manifestId": "test"},
        "tools": [
            {
                "toolId": "get_account",
                "displayName": "Get account",
                "description": "d",
                "target": {
                    "service": "account-service",
                    "method": "GET",
                    "path": "/api/accounts/{accountId}",
                    "timeoutMs": 8000,
                },
                "parameters": {
                    "type": "object",
                    "properties": {
                        "accountId": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"}
                    },
                    "required": ["accountId"],
                    "additionalProperties": False,
                },
                "capabilityScope": "accounts.read",
                "redaction": [],
                "evidenceProjection": projection,
            }
        ],
    }


def test_a_valid_projection_survives_the_manifest_loader():
    manifest = parse_manifest(_manifest({"accountId": {"rename": "id"}}))

    assert manifest.tools[0].evidence_projection[0].key == "accountId"


def test_a_bad_projection_aborts_startup_rather_than_being_ignored():
    with pytest.raises(ManifestError) as exc:
        parse_manifest(_manifest({"accountId": {"literal": "acct-1"}}))

    assert "literal" in str(exc.value)


def test_the_shipped_manifest_still_refuses_required_evidence():
    """`requiredEvidence` stays refused even though `evidenceProjection` is now allowed: the
    policy says what an action NEEDS, the manifest says what a tool EMITS."""
    document = _manifest({"accountId": {"rename": "id"}})
    document["tools"][0]["requiredEvidence"] = ["get_account"]

    with pytest.raises(ManifestError) as exc:
        parse_manifest(document)

    assert "requiredEvidence" in str(exc.value)


# ------------------------------------------------- the fixtures the C# seam test reads ----
#
# The seam ("does the projected shape satisfy authority-policy.yaml?") is held in C# by the REAL
# PolicyEvaluator. That test reads the `projected` block of these fixtures. This test is the
# other half of the join: it proves that block is what the REAL loader and the REAL projection
# engine actually produce from the recorded response — so a `projected` block cannot be
# hand-edited into agreement with a policy the shipped code would not satisfy.
#
# Deliberately, this asserts NOTHING about requiredFields. Restating the policy here would be the
# third drifting document the Gate B ruling (§R7) refuses.

import json
from pathlib import Path

from app.tools.manifest import load_manifest

_ROOT = Path(__file__).resolve().parents[3]
_SAMPLES = _ROOT / "tests" / "fixtures" / "evidence-samples"


def _samples():
    return sorted(_SAMPLES.glob("*.json"))


def test_there_are_recorded_samples_at_all():
    """Guards the guard: an empty directory would make the parametrized test below vacuous."""
    assert _samples(), f"no evidence samples found in {_SAMPLES}"


@pytest.mark.parametrize("path", _samples(), ids=lambda p: p.stem)
def test_committed_projection_matches_what_the_shipped_engine_produces(path):
    sample = json.loads(path.read_text())
    manifest = load_manifest(str(_ROOT / "config" / "copilot-tools.yaml"))
    tool = next((t for t in manifest.tools if t.tool_id == sample["toolId"]), None)

    assert tool is not None, f"{sample['toolId']} has a sample but no manifest entry"
    assert tool.evidence_projection, (
        f"{sample['toolId']} has a recorded sample but declares no evidenceProjection; the "
        "fixture would then be asserting a shape nothing produces"
    )

    recomputed = project(sample["response"], tool.evidence_projection, sample["arguments"])

    assert sample["projected"] == recomputed, (
        f"{path.name} is stale or hand-edited. Regenerate it with:\n"
        "  scripts/demo/evidence-contract.py . --samples --write"
    )


@pytest.mark.parametrize("path", _samples(), ids=lambda p: p.stem)
def test_every_sample_records_where_it_came_from(path):
    """A fixture with no provenance is an assertion with no author."""
    provenance = json.loads(path.read_text()).get("provenance") or {}

    assert provenance.get("capturedFrom")
    assert provenance.get("derivedFrom")
    assert provenance.get("warning"), (
        "every sample must state what it does NOT prove. This requirement outlives the reason it was "
        "written for. It was added when every sample was hand-built from a C# response type, where "
        "the gap was obvious. `get_account` and `list_account_transactions` are now live captures "
        "(2026-09-08), which is strictly stronger evidence -- and that is exactly when a warning "
        "stops being a formality and starts being load-bearing, because a real captured payload "
        "invites more trust than it has earned. Both are the happy path: the account is owned by "
        "the acting banker, so neither sample can reach the case where a banker reads a CUSTOMER's "
        "account and `list_account_transactions` returns 200 with an empty array that satisfies "
        "EvidenceComplete while asserting something false. Do not drop this assertion when the last "
        "hand-built sample is replaced."
    )


# ----------------------------------------------- the ids that make evidence joinable ----


def test_propose_carries_the_ids_that_join_evidence_back_to_its_trace():
    """Gate B ruling §R3.3.

    A projected object with no path back to the call that produced it cannot satisfy the ratified
    requirement that evidence rows deep-link to the originating trace node. Both ids were already
    carried and persisted (`ApprovalService` writes them onto the record — held in C# by
    `EvidenceContractSeamTests.An_approval_is_joinable_to_the_run_that_produced_it`), but nothing
    held the wire side. This is that half.
    """
    import asyncio

    import httpx

    from app.tools.propose import AuthorityClient

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["correlation"] = request.headers.get("X-Correlation-ID")
        return httpx.Response(201, json={"id": "apr_1"})

    client = AuthorityClient(
        base_url="http://authority.invalid",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        timeout_ms=8000,
    )

    asyncio.run(
        client.propose(
            {
                "actionId": "account.balance.adjust",
                "payload": {"accountId": "acct-1001"},
                "evidence": {"get_account": {"accountId": "acct-1001", "balance": 1}},
            },
            bearer_token="t",
            session_id="sess-1",
            agent_id="agent-1",
            correlation_id="corr-abc123",
        )
    )

    assert seen["body"]["sessionId"] == "sess-1"
    assert seen["correlation"] == "corr-abc123"


# ------------------------------------------- the wiring, not just the engine ----
#
# Found by tampering: unwiring `project(...)` from executor.py left the ENTIRE Python suite green
# and the whole Gate B fix inert, because every other test here exercises the engine or the
# fixtures directly. A guard nobody has watched fail is not a guard.


class _StubResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._payload


class _StubClient:
    def __init__(self, payload):
        self._payload = payload
        self.requests = []

    async def request(self, method, url, **kwargs):
        self.requests.append((method, url))
        return _StubResponse(self._payload)


def _shipped_executor(payload):
    from app.tools.executor import ToolExecutor
    from app.tools.registry import ToolRegistry

    manifest = load_manifest(str(_ROOT / "config" / "copilot-tools.yaml"))
    registry = ToolRegistry(
        manifest=manifest,
        service_urls={
            "account-service": "http://accounts.invalid",
            "transaction-service": "http://transactions.invalid",
        },
    )
    return ToolExecutor(registry, _StubClient(payload))


async def test_the_executor_applies_the_declared_projection_to_a_real_tool_call():
    """End to end through the shipped manifest: what `loop.py` stores as evidence is the
    PROJECTED object, not the raw upstream response."""
    executor = _shipped_executor([{"id": "txn-1"}, {"id": "txn-2"}])

    result = await executor.invoke(
        "list_account_transactions", {"accountId": "acct-1001"}, "token"
    )

    assert result.data["accountId"] == "acct-1001"
    assert result.data["count"] == 2
    assert result.data["items"] == [{"id": "txn-1"}, {"id": "txn-2"}]


async def test_the_executor_projects_get_account_too():
    executor = _shipped_executor({"id": "acct-1001", "balance": 10})

    result = await executor.invoke("get_account", {"accountId": "acct-1001"}, "token")

    assert result.data["accountId"] == "acct-1001"
    assert result.data["balance"] == 10


async def test_a_response_that_does_not_match_its_declared_projection_fails_loudly():
    """Storing the raw response instead would resurface much later as an opaque
    `evidence_incomplete` at propose, with nothing pointing at the shape disagreement."""
    from app.tools.executor import ToolInvocationError

    executor = _shipped_executor({"balance": 10})  # no `id` to rename

    with pytest.raises(ToolInvocationError) as exc:
        await executor.invoke("get_account", {"accountId": "acct-1001"}, "token")

    assert exc.value.code == "evidence_projection_failed"


# ------------------------------------------------ the failed-read samples ----
#
# Captured live on 2026-09-09 (banker-customer-read-ruling.md §B4.1 asked for both; until the
# §B2 ruling shipped, neither response was producible, which is why the failed-read path had no
# fixture at all). They live in `failed-reads/` rather than beside the success samples because
# every consumer above enumerates the success samples and requires each one to project CLEANLY —
# and these, correctly, cannot.
#
# The assertion is the inverse of the one above: the shipped projection must RAISE on each. That
# is not a technicality. It is the mechanism §B3.1 depends on — a read that failed must not be
# able to become an evidence row, because a projected object asserts a fact about the world and
# a 403/404 body contains no such fact. Held here so the upheld behaviour is falsifiable rather
# than merely asserted: if someone later makes the projection tolerant of an error body, this
# fails instead of silently minting fabricated evidence.

_FAILED_READS = _SAMPLES / "failed-reads"


def _failed_reads():
    return sorted(_FAILED_READS.glob("*.json"))


def test_the_failed_read_samples_exist():
    """Guards the guard, exactly as `test_there_are_recorded_samples_at_all` does above."""
    captured = {p.name for p in _failed_reads()}

    assert "get_account.404.json" in captured, "no recorded 404 sample"
    assert "list_account_transactions.403.json" in captured, "no recorded 403 sample"


@pytest.mark.parametrize("path", _failed_reads(), ids=lambda p: p.stem)
def test_a_failed_read_cannot_be_projected_into_evidence(path):
    sample = json.loads(path.read_text())
    manifest = load_manifest(str(_ROOT / "config" / "copilot-tools.yaml"))
    tool = next((t for t in manifest.tools if t.tool_id == sample["toolId"]), None)

    assert tool is not None, f"{sample['toolId']} has a sample but no manifest entry"
    assert sample["outcome"]["status"] >= 400, "a failed-read sample must record a failure"

    # No `projected` block, and it must never acquire one: see each sample's own `warning`.
    assert "projected" not in sample, (
        f"{path.name} has a `projected` block. A failed read has nothing to project; a projected "
        "object here would be a fabricated evidence row asserting a state that was never read."
    )

    with pytest.raises(ProjectionError):
        project(sample["response"], tool.evidence_projection, sample["arguments"])


@pytest.mark.parametrize("path", _failed_reads(), ids=lambda p: p.stem)
def test_every_failed_read_sample_records_where_it_came_from(path):
    provenance = json.loads(path.read_text()).get("provenance") or {}

    assert provenance.get("capturedFrom")
    assert provenance.get("derivedFrom")
    assert provenance.get("warning")
    assert provenance.get("redaction"), (
        "these samples were captured against a live deployment, so each must state what was "
        "removed before it was committed — the 404 body carried a real W3C traceId."
    )
