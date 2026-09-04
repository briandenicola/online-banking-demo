"""`propose_action` is the only write affordance, and it cannot execute.

Every path this module tries is a path a model could actually take: naming a
different route, asking for its own status, supplying its own rung, choosing its
own reviewer, or simply calling something that is not in the manifest.

The false pass to watch for: a test that asserts `propose_action` "returns a
proposal" proves nothing about execution — a service that executed AND returned
a proposal would pass it. The assertions here are about what the harness is
*incapable* of, so they are written against the refusal surface and against the
absence of any downstream mutation.
"""

from __future__ import annotations

import inspect

import pytest

from . import service_import  # noqa: F401

from app.tools import propose as propose_module
from app.tools.propose import (
    PROPOSE_PATH,
    PROPOSE_TOOL_SCHEMA,
    AuthorityClient,
    ProposeRejected,
    validate_propose_arguments,
)

VALID = {"actionId": "transaction.flag.review", "payload": {"transactionId": "txn_1"}}


class RecordingTransport:
    """Records every HTTP request the harness attempts, and answers none of them
    with a success. Anything that reaches a downstream service shows up here."""

    def __init__(self):
        self.requests = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.requests.append(("POST", url, json))
        return _Response(201, {"id": "apr_1", "status": "proposed"})

    async def request(self, method, url, params=None, headers=None, timeout=None):
        self.requests.append((method, url, params))
        return _Response(200, {})


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


# ---------------------------------------------------------------------------
# The contract of the tool itself
# ---------------------------------------------------------------------------


def test_the_propose_schema_admits_no_execution_argument():
    """The model can only send what the schema admits. `additionalProperties:
    false` is what makes the allowlist an allowlist rather than a suggestion."""
    assert PROPOSE_TOOL_SCHEMA["additionalProperties"] is False
    properties = set(PROPOSE_TOOL_SCHEMA["properties"])
    for forbidden in ("execute", "status", "approve", "sign", "commit", "force"):
        assert forbidden not in properties, forbidden


@pytest.mark.parametrize(
    "smuggled",
    [
        {"execute": True},
        {"status": "signed"},
        {"requiredSigners": 0},
        {"requiredRung": "L0"},
        {"policyVersion": "pv1:forged"},
        {"payloadHash": "deadbeef"},
        {"cosignerId": "usr_supervisor_1"},
    ],
)
def test_every_self_authorising_argument_is_refused_by_name(smuggled):
    """Refused, not ignored.

    Silently dropping the field is the dangerous behaviour: the caller reads back
    a 201 and believes the field took effect. A named refusal is the only answer
    that cannot be misread.
    """
    with pytest.raises(ProposeRejected) as excinfo:
        validate_propose_arguments({**VALID, **smuggled})

    key = next(iter(smuggled))
    assert key in excinfo.value.message, (
        "the refusal must name the field; a generic 'invalid request' lets the caller "
        "assume the field was accepted"
    )
    # Isolate the fold. Two guards cover this: an allowlist that refuses anything
    # unknown, and a by-name refusal that explains WHY this particular field is
    # refused. Asserting only "it was rejected" is satisfied by the allowlist
    # alone, so deleting the explanation would be unobservable — the Phase 1
    # redundant-guard shape. Pinning the code observes the named refusal itself.
    assert excinfo.value.code == "refused_field", (
        f"{key} was rejected as {excinfo.value.code!r} rather than by name. The reasoned "
        "refusal is what tells a model it is blocked on purpose rather than mistaken."
    )


def test_an_unknown_argument_is_refused_rather_than_dropped():
    with pytest.raises(ProposeRejected):
        validate_propose_arguments({**VALID, "someNewIdea": 1})


def test_a_valid_proposal_still_validates():
    """Both directions. A validator that rejects everything passes every refusal
    test above and makes the tool useless — which is not the same as safe."""
    assert validate_propose_arguments(dict(VALID)) is not None


# ---------------------------------------------------------------------------
# The transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_posts_to_the_proposal_route_and_nothing_else():
    transport = RecordingTransport()
    client = AuthorityClient("http://authority-service:8080", transport, timeout_ms=2000)

    await client.propose(dict(VALID), "tok", "sess_1", "agent_1")

    assert len(transport.requests) == 1
    method, url, body = transport.requests[0]
    assert method == "POST"
    assert url.endswith(PROPOSE_PATH), url
    for execution_route in ("/execute", "/sign", "/approve", "/commit"):
        assert execution_route not in url


@pytest.mark.asyncio
async def test_the_body_sent_to_authority_carries_no_authorisation_fields():
    """What leaves this service must not contain anything that could substitute
    for a human signature."""
    transport = RecordingTransport()
    client = AuthorityClient("http://authority-service:8080", transport, timeout_ms=2000)

    await client.propose(dict(VALID), "tok", "sess_1", "agent_1")
    body = transport.requests[0][2]

    for forbidden in (
        "cosignerId",
        "requiredRung",
        "requiredSigners",
        "policyVersion",
        "payloadHash",
        "status",
        "execute",
        "signatures",
    ):
        assert forbidden not in body, f"{forbidden} left the harness"


@pytest.mark.asyncio
async def test_with_no_authority_configured_the_harness_has_no_write_path_at_all():
    """The failure direction matters. Unconfigured must mean "cannot propose",
    never "proceed locally"."""
    client = AuthorityClient(None, RecordingTransport(), timeout_ms=2000)

    with pytest.raises(ProposeRejected) as excinfo:
        await client.propose(dict(VALID), "tok", "sess_1", "agent_1")

    assert excinfo.value.code == "authority_unavailable"


@pytest.mark.asyncio
async def test_authority_refusal_is_returned_verbatim_and_not_reinterpreted():
    """A harness that "handles" a 422 by retrying, downgrading or synthesising a
    success is a harness that decides its own authorisation."""

    class Refusing(RecordingTransport):
        async def post(self, url, json=None, headers=None, timeout=None):
            self.requests.append(("POST", url, json))
            return _Response(422, {"error": "under_evidenced", "requiredEvidence": ["x"]})

    transport = Refusing()
    client = AuthorityClient("http://authority-service:8080", transport, timeout_ms=2000)

    outcome = await client.propose(dict(VALID), "tok", "sess_1", "agent_1")

    assert outcome.status_code == 422
    assert outcome.admitted is False
    assert outcome.body["error"] == "under_evidenced"
    assert len(transport.requests) == 1, "a refusal must not be retried into a success"


# ---------------------------------------------------------------------------
# Structural: nothing in the module can execute
# ---------------------------------------------------------------------------


def test_the_propose_module_names_no_execution_route():
    """Source-level. A second constant beside PROPOSE_PATH pointing at an
    execution route would be a write path nobody had to call to create."""
    source = inspect.getsource(propose_module)
    for route in ("/execute", "/sign", "/approve", "/signatures"):
        assert route not in source, f"{route} appears in the propose module"


def test_the_authority_client_exposes_no_execute_or_sign_method():
    public = {name for name in dir(AuthorityClient) if not name.startswith("_")}
    for forbidden in ("execute", "sign", "approve", "commit", "finalize", "finalise"):
        assert forbidden not in public, forbidden
