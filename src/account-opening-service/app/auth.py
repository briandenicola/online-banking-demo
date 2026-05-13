from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt


@dataclass
class UserClaims:
    user_id: str
    email: str
    role: str


def _get_settings() -> tuple[str, str, str]:
    secret = os.getenv("JWT_KEY", "YourSuperSecretKeyForJWTTokenGeneration12345")
    issuer = os.getenv("JWT_ISSUER", "user-service")
    audience = os.getenv("JWT_AUDIENCE", "banking-demo")
    return secret, issuer, audience


def _decode_token(token: str) -> dict:
    secret, issuer, audience = _get_settings()
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer=issuer,
        audience=audience,
    )


async def require_auth(request: Request) -> UserClaims:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        claims = _decode_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = claims.get("sub") or claims.get("userId") or claims.get("oid")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")

    return UserClaims(
        user_id=user_id,
        email=claims.get("email", ""),
        role=claims.get("role", "User"),
    )


async def require_admin(request: Request) -> UserClaims:
    user = await require_auth(request)
    if user.role.lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
