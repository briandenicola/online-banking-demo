"""JWT authentication for account-opening-service.

RS256 tokens issued by `user-service`, the platform's sole issuer (issue #334). This service
holds only the public half, fetched from the issuer's JWKS endpoint, so it can verify a token
and cannot mint one. Under the previous HS256 model those were the same capability.

This service is executed against by `authority-service`, so it accepts the mediator audience
in addition to its own — see `mediator.acceptedBy` in `config/jwt-audiences.yaml`. Both come
from configuration; neither is written down here.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"

#: Symmetric-era settings, retired by #334. Presence aborts startup rather than being ignored.
RETIRED_ENV_VARS = ("JWT_KEY", "JWT_SECRET")

#: This service is not the issuer and may never hold signing material.
FORBIDDEN_ENV_VARS = ("JWT_PRIVATE_KEY_PEM",)

_jwk_client: Optional[jwt.PyJWKClient] = None


class JwtConfigurationError(RuntimeError):
    """Raised when the token model cannot be established safely. Always fatal at startup."""


@dataclass
class UserClaims:
    user_id: str
    email: str
    role: str


def assert_token_configuration(service_name: str = "account-opening-service") -> None:
    offenders = [name for name in RETIRED_ENV_VARS if os.environ.get(name, "").strip()]
    if offenders:
        raise JwtConfigurationError(
            f"{service_name}: {', '.join(offenders)} is set, but symmetric JWT signing was "
            "retired by issue #334. Remove the variable — leaving it set and ignored would "
            "tell whoever set it that it took effect."
        )

    forbidden = [name for name in FORBIDDEN_ENV_VARS if os.environ.get(name, "").strip()]
    if forbidden:
        raise JwtConfigurationError(
            f"{service_name}: {', '.join(forbidden)} is set. Only user-service may hold JWT "
            "signing material. Refusing to start."
        )

    if not os.environ.get("JWT_AUDIENCE", "").strip():
        raise JwtConfigurationError(
            f"{service_name}: JWT_AUDIENCE is not set. There is no default audience by design."
        )

    if not (os.environ.get("JWT_JWKS_URI", "").strip() or os.environ.get("JWT_PUBLIC_KEY_PEM", "").strip()):
        raise JwtConfigurationError(
            f"{service_name}: neither JWT_JWKS_URI nor JWT_PUBLIC_KEY_PEM is set."
        )


def _audiences() -> list[str]:
    audiences = [os.environ["JWT_AUDIENCE"].strip()] if os.environ.get("JWT_AUDIENCE") else []
    extra = os.environ.get("JWT_ADDITIONAL_AUDIENCES", "")
    audiences.extend(item.strip() for item in extra.split(",") if item.strip())
    if not audiences:
        raise JwtConfigurationError("JWT_AUDIENCE is not set; refusing to validate any token.")
    return audiences


def _signing_key(token: str):
    pem = os.environ.get("JWT_PUBLIC_KEY_PEM", "").strip()
    if pem:
        return pem

    global _jwk_client
    if _jwk_client is None:
        uri = os.environ.get("JWT_JWKS_URI", "").strip()
        if not uri:
            raise JwtConfigurationError("JWT_JWKS_URI is not set.")
        _jwk_client = jwt.PyJWKClient(uri, cache_keys=True, lifespan=600)

    return _jwk_client.get_signing_key_from_jwt(token).key


def reset_key_cache() -> None:
    """Drop the cached JWKS client. Used by tests that swap key material."""
    global _jwk_client
    _jwk_client = None


def _decode_token(token: str) -> dict:
    key = _signing_key(token)
    return jwt.decode(
        token,
        key,
        algorithms=[ALGORITHM],
        issuer=os.getenv("JWT_ISSUER", "user-service"),
        audience=_audiences(),
        options={"require": ["exp", "iss", "aud", "sub"]},
    )


def _extract_role(claims: dict) -> str:
    role_claim = claims.get("role")
    if isinstance(role_claim, str) and role_claim:
        return role_claim

    uri_role_claim = claims.get("http://schemas.microsoft.com/ws/2008/06/identity/claims/role")
    if isinstance(uri_role_claim, str) and uri_role_claim:
        return uri_role_claim

    return "User"


async def require_auth(request: Request) -> UserClaims:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        claims = _decode_token(token)
    except JwtConfigurationError:
        raise
    except Exception as exc:
        logger.warning("Token rejected: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = claims.get("sub") or claims.get("userId") or claims.get("oid")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")

    return UserClaims(
        user_id=user_id,
        email=claims.get("email", ""),
        role=_extract_role(claims),
    )


async def require_admin(request: Request) -> UserClaims:
    user = await require_auth(request)
    if user.role.lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
