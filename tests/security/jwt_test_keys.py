"""Test-side token minting for the asymmetric (RS256) auth model introduced by #334.

Lives here, once, and is put on ``sys.path`` by each Python service's ``conftest.py``. The
services are packaged independently and share no Python path, so the alternative was five
copies — and five copies of a security helper is the same failure mode #334 is about. The
audiences it returns are read from ``config/jwt-audiences.yaml``, the one place they are
stated: a test that hardcoded ``banking-demo`` would keep passing while the service it tests
validated something else, which is exactly how the shared-audience weakness survived review.

Production code cannot use this module. It generates a signing key, and under #334 only
``user-service`` may hold one; every other service aborts at startup if it finds private key
material in its environment.
"""

from __future__ import annotations

import re
import time
from functools import lru_cache
from pathlib import Path

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ALGORITHM = "RS256"


@lru_cache(maxsize=1)
def _registry_text() -> str:
    """Locate config/jwt-audiences.yaml by walking up from this file."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "jwt-audiences.yaml"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise RuntimeError(
        "config/jwt-audiences.yaml not found. It is the single source of truth for "
        "audiences; tests must not invent one."
    )


@lru_cache(maxsize=1)
def _registry() -> dict:
    """Minimal parse of the fields tests need.

    Hand-rolled rather than PyYAML on purpose: this helper is imported by five service test
    suites and must not add a dependency to any of them. The parse is strict — a shape it
    does not recognise raises rather than quietly returning a default.
    """
    text = _registry_text()
    audiences: dict = {}
    session: list = []
    mediator = ""
    issuer = ""

    section = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue

        if not line.startswith(" "):
            section = line.split(":", 1)[0]
            continue

        stripped = line.strip()

        if section == "issuer":
            match = re.match(r"^name:\s*(\S+)$", stripped)
            if match:
                issuer = match.group(1)
        elif section == "audiences":
            match = re.match(r"^([a-z0-9-]+):\s*(\S+)$", stripped)
            if match:
                audiences[match.group(1)] = match.group(2)
        elif section == "session":
            match = re.match(r"^-\s*(\S+)$", stripped)
            if match:
                session.append(match.group(1))
        elif section == "mediator":
            match = re.match(r"^audience:\s*(\S+)$", stripped)
            if match:
                mediator = match.group(1)

    if not audiences or not session or not mediator or not issuer:
        raise RuntimeError("config/jwt-audiences.yaml did not parse as expected.")

    return {
        "issuer": issuer,
        "audiences": audiences,
        "session": session,
        "mediator": mediator,
    }


def issuer_name() -> str:
    return str(_registry()["issuer"])


def audience_for(service: str) -> str:
    audiences = _registry()["audiences"]
    if service not in audiences:
        raise KeyError(
            f"'{service}' has no entry in config/jwt-audiences.yaml. Add it there rather "
            "than defaulting to one, or every token minted for it is unscoped."
        )
    return str(audiences[service])


def session_audiences() -> list:
    return list(_registry()["session"])


def mediator_audience() -> str:
    return str(_registry()["mediator"])


@lru_cache(maxsize=1)
def _keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_key, public_pem


def public_key_pem() -> str:
    """The half a validating service is allowed to hold."""
    return _keypair()[1]


def private_key_pem() -> str:
    """Only the issuer holds this. Tests use it to stand in for user-service."""
    private_key, _ = _keypair()
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def foreign_private_key_pem() -> str:
    """A key the platform has never seen — an attacker's, in other words."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def make_token(
    user_id: str = "usr-test-001",
    role: str = "User",
    audience=None,
    issuer=None,
    expires_in: int = 3600,
    signing_key=None,
    algorithm: str = ALGORITHM,
    extra_claims=None,
) -> str:
    """Mint a token in the shape user-service produces.

    ``audience`` defaults to the full session set, matching a real login. Every parameter is
    overridable so negative tests can mint the wrong thing on purpose — a security suite that
    can only produce valid tokens proves nothing.
    """
    now = int(time.time())
    claims = {
        "sub": user_id,
        "userId": user_id,
        "unique_name": "testuser",
        "role": role,
        "iss": issuer if issuer is not None else issuer_name(),
        "aud": audience if audience is not None else session_audiences(),
        "iat": now,
        "exp": now + expires_in,
        "jti": "test-jti-001",
        "token_use": "session",
    }
    if extra_claims:
        claims.update(extra_claims)

    key = signing_key if signing_key is not None else private_key_pem()
    return pyjwt.encode(claims, key, algorithm=algorithm)


def forge_hs256_with_public_key(claims: dict) -> str:
    """Hand-build an HS256 token whose 'secret' is the service's own public key.

    This is the algorithm-confusion attack, and it is assembled by hand on purpose: PyJWT
    refuses to HMAC-sign with a PEM that looks asymmetric, so minting it through the library
    would fail in the *test* and never reach the validator. A test that stops before the code
    under test proves nothing about that code.
    """
    import base64
    import hashlib
    import hmac
    import json

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    signing_input = header + b"." + body
    signature = b64(
        hmac.new(public_key_pem().encode(), signing_input, hashlib.sha256).digest()
    )
    return (signing_input + b"." + signature).decode()


def session_claims(
    user_id: str = "usr-test-001",
    role: str = "User",
    audience=None,
    expires_in: int = 3600,
    extra_claims=None,
) -> dict:
    """The claim set make_token() would sign, for tests that need to sign it differently."""
    now = int(time.time())
    claims = {
        "sub": user_id,
        "userId": user_id,
        "unique_name": "testuser",
        "role": role,
        "iss": issuer_name(),
        "aud": audience if audience is not None else session_audiences(),
        "iat": now,
        "exp": now + expires_in,
        "jti": "test-jti-001",
        "token_use": "session",
    }
    if extra_claims:
        claims.update(extra_claims)
    return claims
