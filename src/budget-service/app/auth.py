"""
Shared JWT authentication module for Python/FastAPI services.

Validates JWTs issued by the .NET user-service using symmetric HMAC-SHA256.
This is the canonical source — copies live in each service's app/auth.py.

Config env vars (SCREAMING_SNAKE_CASE):
  JWT_KEY       — HMAC signing key (required)
  JWT_ISSUER    — expected issuer (default: user-service)
  JWT_AUDIENCE  — expected audience (default: banking-demo)
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


@dataclass
class UserContext:
    """Authenticated user extracted from JWT claims."""
    user_id: str
    username: str
    role: str


def _get_jwt_key() -> str:
    key = os.environ.get("JWT_KEY", "")
    if not key:
        raise RuntimeError("JWT_KEY environment variable is not set")
    return key


def _get_jwt_issuer() -> str:
    return os.environ.get("JWT_ISSUER", "user-service")


def _get_jwt_audience() -> str:
    return os.environ.get("JWT_AUDIENCE", "banking-demo")


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(
            token,
            _get_jwt_key(),
            algorithms=["HS256"],
            issuer=_get_jwt_issuer(),
            audience=_get_jwt_audience(),
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
        return payload
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
    """FastAPI dependency — validates Bearer token, returns UserContext."""
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
