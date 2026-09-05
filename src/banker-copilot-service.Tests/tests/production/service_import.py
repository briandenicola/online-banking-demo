"""Import the shipping harness. Absence is a FAILURE, never a skip.

``pytest.importorskip`` is the idiomatic thing here and it is exactly wrong: a
skipped production suite is invisible in a green run, and this whole test plan
exists because invisible non-coverage is the failure mode that costs the most.
If the service is gone or unimportable, that is a red build with a message
saying so.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = TESTS_ROOT.parents[1]
SERVICE_ROOT = REPO_ROOT / "src" / "banker-copilot-service"

if not SERVICE_ROOT.exists():
    raise AssertionError(
        f"{SERVICE_ROOT} does not exist. The production suite cannot run. This is a "
        "failure and not a skip: see the integration ledger, which is the only place "
        "a missing dependency may be recorded."
    )

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

CONFIG_ROOT = REPO_ROOT / "config"
TOOL_MANIFEST = CONFIG_ROOT / "copilot-tools.yaml"
HARNESS_LIMITS = CONFIG_ROOT / "harness-limits.yaml"
ROLE_HIERARCHY = REPO_ROOT / "src" / "user-service" / "config" / "role-hierarchy.yaml"

# The service reads its settings once, at import. Env therefore has to be in
# place before ANY `app.*` module is imported — a fixture that sets it later is
# setting it after the value it wanted to control was already frozen. This is
# the same ordering trap that makes configuration tests pass vacuously.

def _generate_test_keypair() -> tuple[str, str]:
    """(private PEM, public PEM) for this test session.

    Generated here rather than in a fixture because the service freezes its token
    configuration at import, and because the PRIVATE half must never reach the
    environment: the harness aborts startup if it finds signing material, which
    is the whole containment property. Exporting a key to make a fixture
    convenient would have silently switched that property off.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode(),
    )


TEST_PRIVATE_KEY_PEM, TEST_PUBLIC_KEY_PEM = _generate_test_keypair()

#: A second, well-formed keypair the service has never been told about. This is
#: what a forgery actually looks like under RS256 — a valid signature by the
#: wrong signer — as distinct from a malformed token, which fails far earlier and
#: for a different reason.
FOREIGN_PRIVATE_KEY_PEM, _FOREIGN_PUBLIC_KEY_PEM = _generate_test_keypair()

_BASE_ENV = {
    "JWT_PUBLIC_KEY_PEM": TEST_PUBLIC_KEY_PEM,
    "JWT_ISSUER": "user-service",
    "JWT_AUDIENCE": "banking-demo",
    "TOOL_MANIFEST_PATH": str(TOOL_MANIFEST),
    "COPILOT_HARNESS_LIMITS_PATH": str(HARNESS_LIMITS),
    "ROLE_HIERARCHY_PATH": str(ROLE_HIERARCHY),
    "AUTHORITY_SERVICE_URL": "http://authority-service:8080",
}
for _service in (
    "ai-service",
    "transaction-service",
    "account-service",
    "transfer-service",
    "user-service",
    "account-opening-service",
):
    _BASE_ENV[f"DOWNSTREAM__{_service}"] = f"http://{_service}:8080"

os.environ.pop("COSMOS_DB_ENDPOINT", None)
for _key, _value in _BASE_ENV.items():
    os.environ.setdefault(_key, _value)
