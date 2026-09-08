from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _find_repo_root(start: Path) -> Path:
    """Walk up for the repo root instead of assuming a fixed depth.

    This used to be ``SERVICE_ROOT.parents[1]``, which is correct only when the
    suite runs from its normal checkout location. Mutation testing copies the
    service into a ``mutants/`` sandbox one level deeper, so the fixed index
    silently resolved to ``src/`` and every shared fixture below vanished —
    the whole Python mutation job failed to start on that alone.

    Anchoring on files we actually need means the answer is either right or a
    loud error, never a plausible wrong directory. Same discipline as the
    de-hardcoded repo root in the ai-service TLS suite.
    """
    for candidate in (start, *start.parents):
        if (candidate / "config" / "copilot-tools.yaml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise RuntimeError(
        f"could not locate the repository root from {start}. These tests assert against the "
        "real shipped manifests rather than fixtures, so a missing root is a hard error: "
        "silently falling back to a fixture is how a suite starts agreeing with itself."
    )


REPO_ROOT = _find_repo_root(SERVICE_ROOT)

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

#: Make this file importable by name so sibling test modules can import the repo root
#: rather than each recomputing it. The recomputed copies were fixed-depth and wrong
#: anywhere but a normal checkout.
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

#: The real, shipped manifest — tests assert against the artifact that actually deploys, not a
#: fixture that agrees with it. A fixture would let the shipped file drift while tests pass.
MANIFEST_PATH = REPO_ROOT / "config" / "copilot-tools.yaml"
ROLE_HIERARCHY_PATH = REPO_ROOT / "src" / "user-service" / "config" / "role-hierarchy.yaml"
#: The real, shipped fan-out limits file (epic §6.3). Same discipline as the manifest: tests
#: boot the harness against the artifact that deploys, so a drift in the shipped bounds fails
#: a test rather than passing against a fixture that quietly agrees with itself.
HARNESS_LIMITS_PATH = REPO_ROOT / "config" / "harness-limits.yaml"

#: #334: the RS256 test keypair and the canonical audiences live in one place for every
#: service's suite. Imported rather than restated so a token this file mints is a token the
#: registry says this service should accept.
JWT_TEST_HELPERS = REPO_ROOT / "tests" / "security"

if str(JWT_TEST_HELPERS) not in sys.path:
    sys.path.insert(0, str(JWT_TEST_HELPERS))

from jwt_test_keys import (  # noqa: E402
    audience_for,
    issuer_name,
    make_token as _mint,
    public_key_pem,
)

SERVICE_NAME = "banker-copilot-service"


@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    # The harness gets the VALIDATING half only. It has no signing key, no mediator client
    # secret, and its own audience — so it cannot mint a token, cannot present one that
    # satisfies a signature slot, and cannot replay a customer's token at the mediator.
    for retired in ("JWT_KEY", "JWT_SECRET", "JWT_PRIVATE_KEY_PEM", "JWT_MEDIATOR_CLIENT_SECRET"):
        monkeypatch.delenv(retired, raising=False)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", public_key_pem())
    monkeypatch.setenv("JWT_ISSUER", issuer_name())
    monkeypatch.setenv("JWT_AUDIENCE", audience_for(SERVICE_NAME))
    monkeypatch.setenv("COPILOT_TOOL_MANIFEST_PATH", str(MANIFEST_PATH))
    monkeypatch.delenv("TOOL_MANIFEST_PATH", raising=False)
    monkeypatch.setenv("ROLE_HIERARCHY_PATH", str(ROLE_HIERARCHY_PATH))
    monkeypatch.setenv("COPILOT_HARNESS_LIMITS_PATH", str(HARNESS_LIMITS_PATH))
    monkeypatch.delenv("HARNESS_LIMITS_PATH", raising=False)
    monkeypatch.delenv("COSMOS_DB_ENDPOINT", raising=False)
    # #334 lesson: a test's outcome must never depend on ambient env. An inherited
    # AZURE_CLIENT_ID silently flips credential_mode to 'entra' and, with it, the
    # session-ownership path this suite asserts on — so it is cleared explicitly here
    # rather than assumed absent.
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
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
    # Short enough that a test can observe a heartbeat without waiting on the production
    # default. Set here rather than in the service so the default is never tuned for tests.
    monkeypatch.setenv("COPILOT_SSE_HEARTBEAT_SECONDS", "1")
    monkeypatch.setenv("COPILOT_SESSION_TTL_SECONDS", "3")
    # The suite exercises the API, not a model, so it runs the deterministic planner. That is
    # now stated rather than obtained by leaving the Foundry variables unset: `planner_mode()`
    # used to infer deterministic from missing configuration, which meant these tests passed
    # identically whether the deployment had model access or had silently lost it.
    # tests/test_planner_mode.py owns the mode-selection behaviour itself.
    monkeypatch.setenv("COPILOT_PLANNER_MODE", "deterministic")
    from app.auth import reset_key_cache

    reset_key_cache()
    yield


@pytest.fixture
def manifest_path() -> Path:
    return MANIFEST_PATH


@pytest.fixture
def settings():
    from app.config import load_settings

    return load_settings()


@pytest.fixture
def registry(settings):
    from app.tools.manifest import load_manifest
    from app.tools.registry import build_registry

    return build_registry(load_manifest(str(MANIFEST_PATH)), settings)


def make_token(
    user_id: str = "usr_banker_1",
    username: str = "banker@example.com",
    role: str = "banker",
    effective_roles: list[str] | None = None,
    audience: str | list[str] | None = None,
    signing_key: str | None = None,
) -> str:
    extra: dict[str, object] = {"unique_name": username}
    if effective_roles is not None:
        extra["effectiveRoles"] = effective_roles

    return _mint(
        user_id=user_id,
        role=role,
        audience=audience if audience is not None else os.environ["JWT_AUDIENCE"],
        issuer=os.environ["JWT_ISSUER"],
        expires_in=900,
        signing_key=signing_key,
        extra_claims=extra,
    )


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
