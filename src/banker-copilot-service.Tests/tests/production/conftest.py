"""Fixtures for the production suite — the real app, the real manifest, real JWTs.

Environment is set the way the service's own conftest sets it, deliberately: if
the two diverge, one of us is testing a configuration that never ships.

TOKENS ARE RS256 (issue #334)
The suite mints its own RSA keypair per session and hands the service only the
PUBLIC half, via ``JWT_PUBLIC_KEY_PEM``. The private half never enters the
environment — it lives in a module variable and nothing but ``make_token``
touches it.

That is not fastidiousness. The harness aborts startup if ``JWT_PRIVATE_KEY_PEM``
or ``JWT_KEY`` is present, because holding signing material would let the
component defined by its inability to act mint its own supervisor claim. A test
fixture that exported a signing key to satisfy the fixture would have disabled
the very property the suite exists to check, and everything downstream would
still have passed.
"""

from __future__ import annotations

import os
import time

import pytest

from . import service_import  # noqa: F401
from .service_import import (
    HARNESS_LIMITS,
    REPO_ROOT,
    TEST_PRIVATE_KEY_PEM,
    TEST_PUBLIC_KEY_PEM,
    TOOL_MANIFEST,
)

ROLE_HIERARCHY_PATH = REPO_ROOT / "src" / "user-service" / "config" / "role-hierarchy.yaml"

#: Retired or forbidden by the service's own startup check. Named here so the
#: fixture actively clears them rather than assuming the runner is clean — an
#: inherited JWT_KEY from a developer's shell would otherwise abort every test
#: with a configuration error that looks nothing like the bug it is.
_MUST_NOT_BE_SET = ("JWT_KEY", "JWT_SECRET", "JWT_PRIVATE_KEY_PEM", "JWT_MEDIATOR_CLIENT_SECRET")

@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    for name in _MUST_NOT_BE_SET:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", TEST_PUBLIC_KEY_PEM)
    monkeypatch.setenv("JWT_ISSUER", "user-service")
    monkeypatch.setenv("JWT_AUDIENCE", "banking-demo")
    monkeypatch.setenv("TOOL_MANIFEST_PATH", str(TOOL_MANIFEST))
    monkeypatch.setenv("COPILOT_HARNESS_LIMITS_PATH", str(HARNESS_LIMITS))
    monkeypatch.setenv("ROLE_HIERARCHY_PATH", str(ROLE_HIERARCHY_PATH))
    monkeypatch.delenv("COSMOS_DB_ENDPOINT", raising=False)
    for service in (
        "ai-service",
        "transaction-service",
        "account-service",
        "transfer-service",
        "user-service",
        "account-opening-service",
    ):
        monkeypatch.setenv(f"DOWNSTREAM__{service}", f"http://{service}:8080")
    monkeypatch.setenv("AUTHORITY_SERVICE_URL", "http://authority-service:8080")

    # The service's own conftest states this; this file's docstring promises not to diverge
    # from it, and it did. `supervisor_mode()` defaults to `foundry` and aborts when no model
    # is reachable, so on a runner without Foundry credentials every fixture that builds the
    # app errored at setup — the suite did not fail, it never ran. Stated rather than left to
    # inference for the reason the service conftest gives: a suite that obtains the
    # deterministic decider by accident cannot tell that outcome apart from losing model
    # access. tests/test_supervisor_model.py owns mode selection itself.
    monkeypatch.setenv("COPILOT_SUPERVISOR_MODE", "deterministic")
    # And the planner, for the identical reason — `planner_mode()` defaults to `foundry` and
    # aborts the same way. Setting only the supervisor fixed the first error and revealed this
    # one behind it.
    monkeypatch.setenv("COPILOT_PLANNER_MODE", "deterministic")
    # Third instance of the same divergence. `DEFAULT_ACTION_METADATA_PATH` is the CONTAINER
    # path `/app/config/copilot-actions.yaml`, and the loader fail-closes when it is absent —
    # correct in production, unreachable from a checkout. The service's own conftest points it
    # at the repo copy; this file did not, so every app-building fixture errored once the two
    # mode errors above stopped masking it.
    monkeypatch.setenv(
        "COPILOT_ACTION_METADATA_PATH", str(REPO_ROOT / "config" / "copilot-actions.yaml")
    )

    # The service caches a JWKS client across calls; a stale one would validate
    # against a previous session's key and quietly decide the outcome.
    from app.auth import reset_key_cache

    reset_key_cache()
    yield


def make_token(
    user_id: str = "usr_banker_1",
    username: str = "banker@example.com",
    role: str = "banker",
    effective_roles: list[str] | None = None,
    audience: str | None = None,
    key: str | None = None,
    algorithm: str = "RS256",
) -> str:
    import jwt

    claims = {
        "sub": user_id,
        "userId": user_id,
        "unique_name": username,
        "role": role,
        "iss": os.environ["JWT_ISSUER"],
        "aud": audience or os.environ["JWT_AUDIENCE"],
        "exp": int(time.time()) + 900,
    }
    if effective_roles is not None:
        claims["effectiveRoles"] = effective_roles
    elif effective_roles is None and role:
        # The service refuses a token with no ``effectiveRoles`` claim (403).
        # Default to the single declared role so the auth path under test is the
        # one being tested, not the claim-shape path.
        claims["effectiveRoles"] = [role]
    return jwt.encode(claims, key or TEST_PRIVATE_KEY_PEM, algorithm=algorithm)



@pytest.fixture
def banker_token() -> str:
    return make_token()


@pytest.fixture
def other_banker_token() -> str:
    return make_token(user_id="usr_banker_2", username="other@example.com")


@pytest.fixture
def client():
    """A real ASGI client over the real app, with no Cosmos configured.

    In-memory stores are the fallback the service already implements for local
    development, so this exercises the shipping code paths rather than a test
    double of them.
    """
    from fastapi.testclient import TestClient

    from app.main import app as production_app

    with TestClient(production_app) as test_client:
        yield test_client


@pytest.fixture
def banker_headers(banker_token):
    return {"Authorization": f"Bearer {banker_token}"}
