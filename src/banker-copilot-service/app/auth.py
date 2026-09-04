"""JWT authentication for the harness.

Based on the canonical Python auth module (`src/ai-service/app/auth.py`) — RS256 tokens minted
by `user-service`, which is the platform's sole issuer (issue #334).

WHY THE ASYMMETRY MATTERS MORE HERE THAN ANYWHERE ELSE
The harness is the one component defined by its inability to act: it registers zero write
tools and its only write-shaped affordance is ``propose_action``. Under the previous shared
HS256 secret that containment was undone by the key itself — verifying a banker's token and
minting one were the same capability, so a prompt-injected harness could have forged a
``supervisor`` claim and satisfied an L2 co-signature it was never supposed to reach.

Three properties now make that structurally impossible rather than merely unimplemented:

  * It holds only the issuer's PUBLIC key, fetched from JWKS. There is nothing here to sign with.
  * ``assert_token_configuration`` refuses to start if signing material is present anyway —
    mounted by mistake, inherited from a copied manifest, or injected by a compromised store.
  * It is absent from ``mediator.clients`` in `config/jwt-audiences.yaml` and refuses to start
    holding a mediator client secret, so it cannot obtain a broker token either.

Two harness-specific additions:

1. The harness reads the ``effectiveRoles`` claim and **does not re-expand the role hierarchy.**
   `user-service` computes `effectiveRoles` once, at token issuance, from
   `config/role-hierarchy.yaml`. A second expansion here would be a second place for the ladder
   to be subtly wrong — which is exactly how Phase 1 shipped a privilege escalation.

2. Harness access requires the banking role ``banker``. A token with no ``effectiveRoles`` claim
   is refused rather than falling back to the flat ``role`` claim: the fallback would be a
   re-derivation, and a re-derivation is the bug.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import jwt
import yaml
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import ConfigurationError

_bearer_scheme = HTTPBearer(auto_error=False)

#: The banking role that grants harness access. Named once, here, and cross-checked against
#: the role-hierarchy file at startup so a rename in that file is a startup failure, not a
#: silently-open door.
HARNESS_ROLE = "banker"

EFFECTIVE_ROLES_CLAIM = "effectiveRoles"


@dataclass
class UserContext:
    """Authenticated banker. ``bearer_token`` is forwarded verbatim on every tool call so the
    agent can never see or do anything the banker could not (delegated identity, epic I-7)."""

    user_id: str
    username: str
    role: str
    effective_roles: frozenset[str] = field(default_factory=frozenset)
    bearer_token: str = ""

    @property
    def is_supervisor(self) -> bool:
        return "supervisor" in self.effective_roles


def verify_role_hierarchy(path: str) -> dict:
    """Load `role-hierarchy.yaml` and assert the harness role is present.

    This is a *consumption* check, not a second copy: the file remains owned by `user-service`
    and this service derives nothing from it beyond "the role I gate on still exists".
    Fails closed — a missing or unreadable hierarchy aborts startup.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"Role hierarchy not found at {path!r}. The harness refuses to start without it: "
            "gating on a role whose definition cannot be read is not a control."
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Role hierarchy at {path!r} is not valid YAML: {exc}") from exc

    roles = (document or {}).get("roles") or {}
    if HARNESS_ROLE not in roles:
        raise ConfigurationError(
            f"Role hierarchy at {path!r} does not define {HARNESS_ROLE!r}. The harness gates "
            "access on that role; if it has been renamed, this service must be updated "
            "deliberately rather than admitting everyone."
        )
    return document


ALGORITHM = "RS256"

#: Symmetric-era settings, retired by #334. Presence aborts startup rather than being ignored:
#: an operator who sets a signing secret and is not told it does nothing is worse off than one
#: who never set it.
RETIRED_ENV_VARS = ("JWT_KEY", "JWT_SECRET")

#: Signing material and the broker credential. The harness may hold NEITHER. These are the two
#: things that would let it satisfy a signature slot, so their presence is fatal by design.
FORBIDDEN_ENV_VARS = ("JWT_PRIVATE_KEY_PEM", "JWT_MEDIATOR_CLIENT_SECRET")

_jwk_client: "jwt.PyJWKClient | None" = None


def assert_token_configuration(service_name: str = "banker-copilot-service") -> None:
    """Fail-closed startup check for the harness's token posture."""
    offenders = [name for name in RETIRED_ENV_VARS if os.environ.get(name, "").strip()]
    if offenders:
        raise ConfigurationError(
            f"{service_name}: {', '.join(offenders)} is set, but symmetric JWT signing was "
            "retired by issue #334. Tokens are RS256 and only user-service holds a private key."
        )

    forbidden = [name for name in FORBIDDEN_ENV_VARS if os.environ.get(name, "").strip()]
    if forbidden:
        raise ConfigurationError(
            f"{service_name}: {', '.join(forbidden)} is set. The harness registers zero write "
            "tools by design; holding signing material or the broker credential would hand it "
            "back the ability to authorise its own actions. Refusing to start."
        )

    if not os.environ.get("JWT_AUDIENCE", "").strip():
        raise ConfigurationError(
            f"{service_name}: JWT_AUDIENCE is not set. There is no default audience by design "
            "— a shared fallback is what made every token valid against every service."
        )

    if not (os.environ.get("JWT_JWKS_URI", "").strip() or os.environ.get("JWT_PUBLIC_KEY_PEM", "").strip()):
        raise ConfigurationError(
            f"{service_name}: neither JWT_JWKS_URI nor JWT_PUBLIC_KEY_PEM is set. A service "
            "that cannot obtain the issuer's public key must not accept tokens."
        )


def _audiences() -> list[str]:
    audiences = [os.environ["JWT_AUDIENCE"].strip()] if os.environ.get("JWT_AUDIENCE") else []
    extra = os.environ.get("JWT_ADDITIONAL_AUDIENCES", "")
    audiences.extend(item.strip() for item in extra.split(",") if item.strip())
    if not audiences:
        raise ConfigurationError("JWT_AUDIENCE is not set; refusing to validate any token.")
    return audiences


def _signing_key(token: str):
    """The issuer's PUBLIC key. Nothing in this process can sign with it."""
    pem = os.environ.get("JWT_PUBLIC_KEY_PEM", "").strip()
    if pem:
        return pem

    global _jwk_client
    if _jwk_client is None:
        uri = os.environ.get("JWT_JWKS_URI", "").strip()
        if not uri:
            raise ConfigurationError("JWT_JWKS_URI is not set.")
        _jwk_client = jwt.PyJWKClient(uri, cache_keys=True, lifespan=600)

    return _jwk_client.get_signing_key_from_jwt(token).key


def reset_key_cache() -> None:
    """Drop the cached JWKS client. Used by tests that swap key material."""
    global _jwk_client
    _jwk_client = None


def _decode_token(token: str) -> dict:
    try:
        key = _signing_key(token)
    except ConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 - JWKS unreachable, bad header, unknown kid
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to verify token signature",
        ) from exc

    try:
        return jwt.decode(
            token,
            key,
            # Pinned. Leaving the algorithm open lets an attacker-supplied header downgrade a
            # public key back into a shared secret, which would restore minting to every holder.
            algorithms=[ALGORITHM],
            issuer=os.environ.get("JWT_ISSUER", "user-service"),
            audience=_audiences(),
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        )


def _claim_as_set(payload: dict, claim: str) -> frozenset[str]:
    raw = payload.get(claim)
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        return frozenset({raw})
    return frozenset(str(item) for item in raw)


def extract_user(payload: dict, bearer_token: str) -> UserContext:
    return UserContext(
        user_id=payload.get("userId") or payload.get("sub", ""),
        username=payload.get("unique_name", ""),
        role=payload.get(
            "role",
            payload.get(
                "http://schemas.microsoft.com/ws/2008/06/identity/claims/role", "user"
            ),
        ),
        effective_roles=_claim_as_set(payload, EFFECTIVE_ROLES_CLAIM),
        bearer_token=bearer_token,
    )


async def verify_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserContext:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode_token(credentials.credentials)
    return extract_user(payload, credentials.credentials)


async def require_banker(user: UserContext = Depends(verify_jwt)) -> UserContext:
    """Harness access gate.

    ``supervisor`` reaches this through ``effectiveRoles`` because `role-hierarchy.yaml` says
    supervisor implies banker — expanded by `user-service`, not here. ``admin`` does not, and
    that is deliberate: platform power is not banking authority.
    """
    if not user.effective_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Token carries no effectiveRoles claim. The harness will not infer banking "
                "authority from the flat role claim."
            ),
        )
    if HARNESS_ROLE not in user.effective_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Harness access requires the {HARNESS_ROLE!r} banking role.",
        )
    return user
