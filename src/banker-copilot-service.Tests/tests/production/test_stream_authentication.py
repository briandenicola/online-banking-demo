"""The event stream is authenticated, and it is authenticated the hard way.

Native ``EventSource`` cannot set an ``Authorization`` header. The two usual
workarounds are both vulnerabilities: put the token in the query string (it lands
in access logs, proxy logs and browser history) or fall back to a cookie (which
reintroduces CSRF on a GET). The design chose SSE-over-fetch precisely so the
bearer token travels in a header — see `docs/design/banker-copilot-ui.md` §4.1.

A test that only asserts "the stream returns 200 for a valid token" is a false
pass: an entirely unauthenticated endpoint returns 200 for a valid token too.
Every case here is therefore a REFUSAL, plus one positive case so the refusals
cannot be satisfied by an endpoint that refuses everyone.
"""

from __future__ import annotations

import os
import time

import pytest

from . import service_import  # noqa: F401
from .service_import import FOREIGN_PRIVATE_KEY_PEM, TEST_PRIVATE_KEY_PEM
from .conftest import make_token

STREAM = "/api/copilot/sessions/{sid}/stream"


def _new_session(client, headers) -> str:
    response = client.post("/api/copilot/sessions", headers=headers, json={"objective": "review"})
    assert response.status_code == 201, response.text
    return response.json()["sessionId"]


def _new_run(client, headers, session_id: str) -> str:
    """A session is not a run. The stream is session-scoped but streams a RUN,
    so a session with no run has nothing to stream — see the session/run tests."""
    response = client.post(
        f"/api/copilot/sessions/{session_id}/runs",
        headers=headers,
        json={"intent": "review flagged transaction txn_1"},
    )
    assert response.status_code == 202, response.text
    return response.json()["runId"]


def _stream_status(client, url, headers=None):
    """Open the stream, take the status, and close immediately.

    The body is an infinite generator; reading it to completion never returns.
    """
    with client.stream("GET", url, headers=headers or {}) as response:
        status = response.status_code
        if status >= 400:
            response.read()
        return status


def test_a_stream_with_no_authorization_header_is_refused(client):
    assert _stream_status(client, STREAM.format(sid="sess_anything")) == 401


def test_a_token_in_the_query_string_is_not_honoured(client, banker_token):
    """The EventSource workaround. If this ever returns 200 the token is being
    read from a place that gets logged."""
    url = STREAM.format(sid="sess_anything") + f"?access_token={banker_token}"
    assert _stream_status(client, url) == 401

    for alias in ("token", "jwt", "auth"):
        aliased = STREAM.format(sid="sess_anything") + f"?{alias}={banker_token}"
        assert _stream_status(client, aliased) == 401, alias


def test_a_token_signed_with_the_wrong_key_is_refused(client):
    """A valid signature by a signer the service was never told about.

    Signed with a real RSA key, so the token is well-formed and parses cleanly;
    only the signer is wrong. A garbage string is rejected inside the JWT library
    before verification is ever reached, which would have told us nothing about
    whether signatures are actually checked.
    """
    forged = make_token(key=FOREIGN_PRIVATE_KEY_PEM)
    assert _stream_status(client, STREAM.format(sid="s"), {"Authorization": f"Bearer {forged}"}) == 401


def test_a_symmetrically_signed_token_is_refused(client):
    """Algorithm confusion — the classic way an RS256 migration is undone.

    The service holds only the issuer's PUBLIC key. If it accepted HS256, that
    public key — not a secret, and published via JWKS — would double as the HMAC
    secret, and anyone able to read it could mint any claim they liked. This
    forgery claims ``supervisor``, precisely the escalation issue #334 argues is
    structurally unavailable to the harness.

    Assembled by hand because PyJWT refuses to PRODUCE this token: it rejects a
    PEM as an HMAC secret. That client-side courtesy is not a defence — an
    attacker is not using PyJWT — so the token is built from bytes to make sure
    the refusal being observed is the service's, not the library's.
    """
    import base64
    import hashlib
    import hmac
    import json

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(
        json.dumps(
            {
                "sub": "usr_banker_1",
                "userId": "usr_banker_1",
                "unique_name": "banker",
                "role": "supervisor",
                "effectiveRoles": ["banker", "supervisor"],
                "iss": os.environ["JWT_ISSUER"],
                "aud": os.environ["JWT_AUDIENCE"],
                "exp": int(time.time()) + 900,
            }
        ).encode()
    )
    signing_input = header + b"." + payload
    secret = os.environ["JWT_PUBLIC_KEY_PEM"].encode()
    signature = b64(hmac.new(secret, signing_input, hashlib.sha256).digest())
    forged = (signing_input + b"." + signature).decode()
    assert _stream_status(client, STREAM.format(sid="s"), {"Authorization": f"Bearer {forged}"}) == 401


def test_an_unsigned_token_is_refused(client):
    """alg=none — the same attack, one rung cruder."""
    import jwt as _jwt

    forged = _jwt.encode(
        {
            "sub": "usr_banker_1",
            "userId": "usr_banker_1",
            "unique_name": "banker",
            "role": "banker",
            "effectiveRoles": ['banker'],
            "iss": os.environ["JWT_ISSUER"],
            "aud": os.environ["JWT_AUDIENCE"],
            "exp": int(time.time()) + 900,
        },
        None,
        algorithm="none",
    )
    assert _stream_status(client, STREAM.format(sid="s"), {"Authorization": f"Bearer {forged}"}) == 401



def test_a_token_for_the_wrong_audience_is_refused(client):
    wrong = make_token(audience="some-other-app")
    assert _stream_status(client, STREAM.format(sid="s"), {"Authorization": f"Bearer {wrong}"}) == 401


def test_an_expired_token_is_refused(client):
    import os
    import time

    import jwt

    stale = jwt.encode(
        {
            "sub": "usr_banker_1",
            "userId": "usr_banker_1",
            "unique_name": "banker",
            "role": "banker",
            "effectiveRoles": ["banker"],
            "iss": os.environ["JWT_ISSUER"],
            "aud": os.environ["JWT_AUDIENCE"],
            "exp": int(time.time()) - 60,
        },
        TEST_PRIVATE_KEY_PEM,
        algorithm="RS256",
    )
    assert _stream_status(client, STREAM.format(sid="s"), {"Authorization": f"Bearer {stale}"}) == 401


def test_a_valid_banker_can_open_their_own_stream(client, banker_headers):
    """The positive control. Without it, an endpoint that returns 401 to
    everybody would pass every test above."""
    session_id = _new_session(client, banker_headers)
    _new_run(client, banker_headers, session_id)
    assert _stream_status(client, STREAM.format(sid=session_id), banker_headers) == 200


def test_one_bankers_stream_is_not_readable_by_another_banker(client, banker_headers):
    """Authentication is not authorisation. A valid token for the wrong person
    must not open the stream."""
    session_id = _new_session(client, banker_headers)
    intruder = {"Authorization": f"Bearer {make_token(user_id='usr_banker_2')}"}

    status = _stream_status(client, STREAM.format(sid=session_id), intruder)
    assert status in (403, 404), status


def test_the_trace_endpoint_is_protected_the_same_way_as_the_stream(client, banker_headers):
    """The persisted trace holds the same content as the live stream. Guarding
    one and not the other guards nothing — the transcript is simply read from
    the other door."""
    session_id = _new_session(client, banker_headers)
    run_id = client.post(
        f"/api/copilot/sessions/{session_id}/runs",
        headers=banker_headers,
        json={"intent": "review flagged transaction txn_1"},
    ).json()["runId"]

    assert client.get(f"/api/copilot/runs/{run_id}/trace").status_code == 401

    intruder = {"Authorization": f"Bearer {make_token(user_id='usr_banker_2')}"}
    assert client.get(f"/api/copilot/runs/{run_id}/trace", headers=intruder).status_code in (403, 404)

    assert client.get(f"/api/copilot/runs/{run_id}/trace", headers=banker_headers).status_code == 200


def test_reconnecting_with_a_cursor_is_re_authenticated(client, banker_headers):
    """Resume is a new request. If ``lastSeq`` were treated as a resumption
    ticket, a reconnect would be a way in without a token."""
    session_id = _new_session(client, banker_headers)
    run_id = client.post(
        f"/api/copilot/sessions/{session_id}/runs",
        headers=banker_headers,
        json={"intent": "review flagged transaction txn_1"},
    ).json()["runId"]

    resume = STREAM.format(sid=session_id) + f"?runId={run_id}&lastSeq=1"
    assert _stream_status(client, resume) == 401
    assert _stream_status(client, resume, banker_headers) == 200


def test_the_stream_declares_the_sse_content_type_and_disables_buffering(client, banker_headers):
    """An SSE response behind a buffering proxy is a batch response that arrives
    at the end. The header is what tells nginx not to do that."""
    session_id = _new_session(client, banker_headers)
    _new_run(client, banker_headers, session_id)
    with client.stream("GET", STREAM.format(sid=session_id), headers=banker_headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers.get("x-accel-buffering") == "no"
        assert response.headers.get("cache-control", "").startswith("no-cache")


@pytest.mark.parametrize("route", ["/api/copilot/sessions", "/api/copilot/tools"])
def test_no_copilot_route_answers_without_a_token(client, route):
    """A blanket sweep. New routes get added; this fails when one arrives open."""
    assert client.get(route).status_code in (401, 405)
