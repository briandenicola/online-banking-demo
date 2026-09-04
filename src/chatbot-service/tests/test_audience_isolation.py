"""Cross-service token isolation for chatbot-service (#334).

Before #334 every service validated the audience ``banking-demo``, so a token minted for any
one of them was a token for all of them — and because signing was symmetric, any service
holding the validation secret could mint one. These tests assert the properties that replaced
that: a token addressed to a different service is refused here, a holder of the validating
key cannot produce a token this service accepts, and the mediator audience is not a session
token.

Written against ``app.auth`` rather than an HTTP route so they keep proving the property even
if the routes move. The audiences come from ``config/jwt-audiences.yaml`` via the shared
helper — restating them here would let this file agree with itself while disagreeing with
what the service actually validates.
"""

import os

import pytest
from jwt_test_keys import (
    audience_for,
    foreign_private_key_pem,
    forge_hs256_with_public_key,
    issuer_name,
    make_token,
    mediator_audience,
    session_claims,
)

SERVICE_UNDER_TEST = "chatbot-service"

OTHER_SERVICES = [
    "user-service",
    "account-service",
    "transaction-service",
    "transfer-service",
    "authority-service",
    "banker-copilot-service",
    "ai-service",
    "budget-service",
    "chatbot-service",
    "account-opening-service",
]


def _decode(token):
    from app.auth import _decode_token

    return _decode_token(token)


def _accepted_audiences():
    from app.auth import _audiences

    return _audiences()


@pytest.mark.parametrize(
    "other", [s for s in OTHER_SERVICES if s != SERVICE_UNDER_TEST]
)
def test_a_token_for_another_service_is_refused(other):
    """The whole point of per-service audiences."""
    token = make_token(audience=audience_for(other))

    with pytest.raises(Exception):
        _decode(token)


def test_the_token_for_this_service_is_accepted():
    """The positive direction — otherwise the test above could pass by rejecting everything."""
    claims = _decode(make_token(audience=os.environ["JWT_AUDIENCE"]))

    assert claims["iss"] == issuer_name()


def test_a_holder_of_the_validating_key_cannot_mint():
    """Asymmetric signing, stated as the property it buys.

    The public key is what this service holds. Signing with it as though it were an HMAC
    secret is the classic algorithm-confusion downgrade; pinning RS256 is what stops it.
    """
    forged = forge_hs256_with_public_key(
        session_claims(audience=os.environ["JWT_AUDIENCE"])
    )

    with pytest.raises(Exception):
        _decode(forged)


def test_a_foreign_keypair_cannot_mint():
    """The realistic forgery once nobody but the issuer holds a signing key."""
    forged = make_token(
        audience=os.environ["JWT_AUDIENCE"],
        signing_key=foreign_private_key_pem(),
    )

    with pytest.raises(Exception):
        _decode(forged)


def test_a_forged_privileged_role_still_needs_a_valid_signature():
    """Claims are only worth the key that signed them."""
    forged = make_token(
        role="supervisor",
        audience=os.environ["JWT_AUDIENCE"],
        signing_key=foreign_private_key_pem(),
        extra_claims={"effectiveRoles": ["supervisor", "admin"]},
    )

    with pytest.raises(Exception):
        _decode(forged)


def test_the_mediator_audience_is_handled_as_the_registry_declares():
    """A broker token is not a user token — unless this service is a declared target."""
    token = make_token(audience=mediator_audience())

    if mediator_audience() in _accepted_audiences():
        assert _decode(token)["iss"] == issuer_name()
    else:
        with pytest.raises(Exception):
            _decode(token)
