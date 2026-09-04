"""
Shared JWT authentication for the Python/FastAPI services.

Validates RS256 tokens issued by `user-service`, the platform's sole issuer (issue #334).

WHAT CHANGED AND WHY
Previously every service validated the single audience `banking-demo` using HS256 with a
shared secret. Two consequences, both serious:

  * The token was a platform-wide bearer credential. One leaked from a read path was equally
    good against money movement.
  * Symmetric signing means the ability to VERIFY is the ability to MINT. Every service — and
    anything that could read the `jwt-key` secret — was a supervisor-token generator.

Now: `user-service` holds an RSA private key and nothing else does. Public keys are fetched
from its JWKS endpoint, so a service that can validate still cannot sign. Each service
validates only the audience that names it, plus (for services the approval broker executes
against) the mediator audience.

Config env vars:
  JWT_JWKS_URI            — issuer's JWKS endpoint (required unless JWT_PUBLIC_KEY_PEM is set)
  JWT_PUBLIC_KEY_PEM      — pinned public key, an alternative to JWKS (tests, air-gapped)
  JWT_AUDIENCE            — THIS service's audience, from config/jwt-audiences.yaml
  JWT_ADDITIONAL_AUDIENCES— comma-separated extras (the mediator audience, where applicable)
  JWT_ISSUER              — expected issuer (default: user-service)

Retired — their presence aborts startup rather than being ignored, because an operator who
sets a security value and is not told it does nothing is worse off than one who never set it:
  JWT_KEY, JWT_SECRET     — the symmetric signing secret
  JWT_PRIVATE_KEY_PEM     — no Python service is the issuer; none may hold signing material
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHM = "RS256"

#: Symmetric-era settings. Retired by #334; fail closed if any is still set.
RETIRED_ENV_VARS = ("JWT_KEY", "JWT_SECRET")

#: No Python service is the issuer, so none of them may ever hold a private key.
FORBIDDEN_ENV_VARS = ("JWT_PRIVATE_KEY_PEM",)

_jwk_client: Optional["jwt.PyJWKClient"] = None


class JwtConfigurationError(RuntimeError):
    """Raised when the token model cannot be established safely. Always fatal at startup."""


@dataclass
class UserContext:
    """Authenticated user extracted from JWT claims."""

    user_id: str
    username: str
    role: str


def assert_token_configuration(service_name: str) -> None:
    """Fail-closed startup check. Call from the app's lifespan/startup hook.

    Deliberately raises rather than logging a warning: a service that starts up with a retired
    signing secret set looks healthy while misrepresenting its own security posture.
    """
    offenders = [name for name in RETIRED_ENV_VARS if os.environ.get(name, "").strip()]
    if offenders:
        raise JwtConfigurationError(
            f"{service_name}: {', '.join(offenders)} is set, but symmetric JWT signing was "
            "retired by issue #334. Tokens are RS256 and only user-service holds a private "
            "key. Remove the variable — leaving it set and ignored would tell whoever set it "
            "that it took effect."
        )

    forbidden = [name for name in FORBIDDEN_ENV_VARS if os.environ.get(name, "").strip()]
    if forbidden:
        raise JwtConfigurationError(
            f"{service_name}: {', '.join(forbidden)} is set. Only user-service may hold JWT "
            "signing material; a validation-key holder that can also mint is precisely the "
            "property #334 exists to remove. Refusing to start."
        )

    if not os.environ.get("JWT_AUDIENCE", "").strip():
        raise JwtConfigurationError(
            f"{service_name}: JWT_AUDIENCE is not set. There is no default audience by design "
            "— a shared fallback is what made every token valid everywhere."
        )

    if not (os.environ.get("JWT_JWKS_URI", "").strip() or os.environ.get("JWT_PUBLIC_KEY_PEM", "").strip()):
        raise JwtConfigurationError(
            f"{service_name}: neither JWT_JWKS_URI nor JWT_PUBLIC_KEY_PEM is set. A service "
            "that cannot obtain the issuer's public key must not accept tokens."
        )


def _get_jwt_issuer() -> str:
    return os.environ.get("JWT_ISSUER", "user-service")


def _audiences() -> list[str]:
    """This service's audience plus any extras the registry grants it.

    Returned as a list so PyJWT accepts a token whose `aud` contains ANY of them — that is how
    a service the approval broker executes against accepts both its own audience and the
    mediator audience, without accepting anything else.
    """
    audiences = [os.environ["JWT_AUDIENCE"].strip()] if os.environ.get("JWT_AUDIENCE") else []
    extra = os.environ.get("JWT_ADDITIONAL_AUDIENCES", "")
    audiences.extend(item.strip() for item in extra.split(",") if item.strip())

    if not audiences:
        raise JwtConfigurationError("JWT_AUDIENCE is not set; refusing to validate any token.")

    return audiences


def _signing_key(token: str):
    """Resolve the issuer's public key for this token.

    A pinned PEM wins when present. Otherwise the key comes from the issuer's JWKS endpoint,
    fetched lazily and cached by PyJWKClient. Lazy rather than at startup on purpose: fetching
    at startup would make every service depend on user-service booting first, which neither
    docker-compose nor Kubernetes guarantees, turning a slow issuer into a cluster-wide
    crashloop. A fetch failure fails the request closed with a 401 — never open.
    """
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
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        key = _signing_key(token)
    except JwtConfigurationError:
        raise
    except Exception as exc:  # JWKS unreachable, malformed header, unknown kid
        logger.error("Could not resolve a signing key: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to verify token signature",
        )

    try:
        return jwt.decode(
            token,
            key,
            # Pinned. Without this, a validator can be talked into a weaker algorithm by an
            # attacker-supplied header — the alg-confusion downgrade that turns a public key
            # back into a shared secret and hands minting to every holder.
            algorithms=[ALGORITHM],
            issuer=_get_jwt_issuer(),
            audience=_audiences(),
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


def _extract_user(payload: dict) -> UserContext:
    """Extract UserContext from decoded JWT claims."""
    user_id = payload.get("userId") or payload.get("sub", "")
    username = payload.get("unique_name", "")
    # .NET ClaimTypes.Role serialises as the full URI or short "role" depending on handler
    role = payload.get("role", payload.get(
        "http://schemas.microsoft.com/ws/2008/06/identity/claims/role", "user"
    ))
    return UserContext(user_id=user_id, username=username, role=role)


async def verify_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> UserContext:
    """FastAPI dependency — validates the bearer token and returns UserContext."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode_token(credentials.credentials)
    return _extract_user(payload)


async def require_admin(user: UserContext = Depends(verify_jwt)) -> UserContext:
    """FastAPI dependency — requires authenticated user with admin role."""
    if user.role.lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user
