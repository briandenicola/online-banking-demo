"""`propose_action` — the sole write affordance, and the things it refuses."""

from __future__ import annotations

import httpx
import pytest

from app.tools.propose import (
    PROPOSE_PATH,
    AuthorityClient,
    ProposeRejected,
    validate_propose_arguments,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


VALID = {"actionId": "transaction.flag.review", "payload": {"transactionId": "tx_1"}}


def test_cosigner_id_is_rejected_not_ignored():
    """Naming a co-signer at proposal time lets the requester choose their own reviewer — the
    exact self-dealing pattern L2 exists to prevent. Silently dropping the field would let a
    caller send it, get a 201 back, and believe it took effect."""
    with pytest.raises(ProposeRejected) as excinfo:
        validate_propose_arguments({**VALID, "cosignerId": "usr_supervisor_1"})

    assert excinfo.value.code == "refused_field"
    assert "cosignerId" in excinfo.value.message


@pytest.mark.parametrize(
    "field, value",
    [
        ("requiredRung", "L1"),
        ("requiredSigners", 1),
        ("policyVersion", "pv1:deadbeef"),
        ("payloadHash", "sha256:0000"),
        ("execute", True),
        ("status", "signed"),
    ],
)
def test_ladder_owned_fields_are_rejected(field, value):
    """Every one of these has exactly one authoritative home in authority-service. A
    caller-supplied copy is a second, lower authority for the same decision."""
    with pytest.raises(ProposeRejected) as excinfo:
        validate_propose_arguments({**VALID, field: value})

    assert excinfo.value.code == "refused_field"
    assert field in excinfo.value.message


def test_unknown_field_is_refused():
    with pytest.raises(ProposeRejected, match="does not accept"):
        validate_propose_arguments({**VALID, "urgency": "high"})


def test_action_id_and_payload_are_required():
    with pytest.raises(ProposeRejected):
        validate_propose_arguments({"payload": {"a": 1}})
    with pytest.raises(ProposeRejected):
        validate_propose_arguments({"actionId": "transaction.flag.review", "payload": {}})


@pytest.mark.asyncio
async def test_propose_posts_the_authority_contract_and_never_executes():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.read().decode()
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            201,
            json={
                "id": "apr_1",
                "status": "pending",
                "requiredRung": "L2",
                "requiredSigners": 2,
                "payloadHash": "sha256:abc",
                "policyVersion": "pv1:1234",
            },
        )

    async with _client(handler) as http:
        authority = AuthorityClient("http://authority-service:8080", http, 8000)
        outcome = await authority.propose(
            VALID, bearer_token="tok", session_id="sess_1", agent_id="asst_1"
        )

    assert outcome.admitted
    assert outcome.approval_id == "apr_1"
    assert captured["url"] == f"http://authority-service:8080{PROPOSE_PATH}"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer tok"
    # The banker's own token is forwarded — the agent acts only with delegated identity.
    assert "cosignerId" not in captured["body"]
    # The harness never names a rung or a signer count; authority-service derives both.
    assert "requiredRung" not in captured["body"]


@pytest.mark.asyncio
async def test_refusals_from_authority_are_returned_verbatim():
    """The tool returns the refusal to the model unaltered, so the agent knows it is blocked
    and can say so, rather than assuming success."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": "action_not_permitted",
                "requiredRung": "L3",
                "reason": "outside the Copilot's authority",
            },
        )

    async with _client(handler) as http:
        authority = AuthorityClient("http://authority-service:8080", http, 8000)
        outcome = await authority.propose(
            VALID, bearer_token="tok", session_id="sess_1", agent_id="asst_1"
        )

    assert outcome.admitted is False
    assert outcome.status_code == 403
    assert outcome.body["error"] == "action_not_permitted"


@pytest.mark.asyncio
async def test_no_authority_url_means_nothing_can_be_proposed():
    """The correct failure direction: with no ladder reachable, the agent can act on nothing."""

    async with _client(lambda r: httpx.Response(200)) as http:
        authority = AuthorityClient(None, http, 8000)
        with pytest.raises(ProposeRejected, match="no other write path"):
            await authority.propose(
                VALID, bearer_token="tok", session_id="sess_1", agent_id="asst_1"
            )


@pytest.mark.asyncio
async def test_propose_never_targets_an_execute_or_sign_route():
    """Whatever else changes, the URL this module builds must remain the propose route."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(201, json={"id": "apr_1"})

    async with _client(handler) as http:
        authority = AuthorityClient("http://authority-service:8080", http, 8000)
        await authority.propose(
            VALID, bearer_token="tok", session_id="sess_1", agent_id="asst_1"
        )

    assert len(seen) == 1
    assert not any(segment in seen[0] for segment in ("/sign", "/deny", "/execute"))
