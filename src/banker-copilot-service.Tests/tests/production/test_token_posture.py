"""The harness may hold no key it could sign with (issue #334).

WHY THIS IS A PHASE 2 TEST AND NOT AN AUTH DETAIL
The Phase 2 invariant is that agents never approve, and its enforcement is the
service split: `banker-copilot-service` registers zero write tools and can only
`propose_action`; `authority-service` is the sole executor. That split is worth
exactly as much as the tokens it rests on.

Under a shared HS256 secret the split was decorative. Verifying a banker's token
and minting one were the same capability, so a harness that had been talked into
something by injected tool output could have forged a `supervisor` claim and
satisfied a co-signature slot it was never meant to reach. No write tool would
have been registered and no rung would have been skipped; the signature would
simply have been fake, and every structural guard in the suite would still have
been green.

So these tests are the floor under the rest of the suite. They assert the
harness cannot start while holding signing material, rather than that it happens
not to use any — a service that merely does not sign today is one import away
from signing tomorrow.

FOUND WHILE WRITING THIS FILE: this suite's own fixtures were still exporting
`JWT_KEY` and minting HS256 after the migration landed. They did not fail
softly — `assert_token_configuration` refused to start and 28 tests errored,
which is precisely the behaviour under test here. Had it been ignored instead,
the suite would have gone on passing against a configuration that no longer
ships, and nothing would have said so.
"""

from __future__ import annotations

import os

import pytest

from . import service_import  # noqa: F401


def _fresh_app():
    """Build the app the way the process does, so startup checks actually run.

    `TestClient` as a context manager is what triggers lifespan; constructing it
    and never entering it would skip every assertion this file cares about, and
    the tests would pass without exercising anything.
    """
    from fastapi.testclient import TestClient

    from app.main import app as production_app

    return TestClient(production_app)


@pytest.mark.parametrize("retired", ["JWT_KEY", "JWT_SECRET"])
def test_a_retired_signing_secret_aborts_startup(monkeypatch, retired):
    """Set a symmetric secret and the service must refuse to run.

    A failure here means the harness starts while holding a key that both signs
    and verifies, which hands it the ability to authorise its own actions.

    A FALSE PASS would be an exception raised for some other reason — a missing
    manifest, an unset audience — so the message is matched, not merely the
    type.
    """
    monkeypatch.setenv(retired, "any-non-empty-value")

    with pytest.raises(Exception) as raised:
        with _fresh_app():
            pass

    message = str(raised.value)
    assert retired in message, f"aborted, but not because of {retired}: {message}"
    assert "334" in message or "symmetric" in message.lower(), message


@pytest.mark.parametrize("forbidden", ["JWT_PRIVATE_KEY_PEM", "JWT_MEDIATOR_CLIENT_SECRET"])
def test_signing_material_and_the_broker_credential_are_both_fatal(monkeypatch, forbidden):
    """The two things that would let the harness satisfy a signature slot.

    A private key lets it sign directly; the mediator client secret lets it
    obtain a broker token and have something else sign for it. Either one
    reopens the same hole, so both must be fatal — and they must be fatal
    SEPARATELY, or one is only being caught by the other.
    """
    monkeypatch.setenv(forbidden, "any-non-empty-value")

    with pytest.raises(Exception) as raised:
        with _fresh_app():
            pass

    assert forbidden in str(raised.value)


def test_the_harness_is_not_a_declared_mediator_client():
    """Config, not code: it must not be able to ask for a broker token either.

    Refusing the secret in the environment is one half. If the harness were
    listed as a mediator client, the credential could be issued to it legitimately
    and the environment check would be the only thing standing in the way.
    """
    import yaml

    path = service_import.REPO_ROOT / "config" / "jwt-audiences.yaml"
    if not path.exists():
        pytest.fail(f"{path} is missing; the mediator client list cannot be checked")

    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    clients = ((document.get("mediator") or {}).get("clients")) or {}
    names = clients if isinstance(clients, (list, dict)) else []

    assert "banker-copilot-service" not in names, (
        "banker-copilot-service is a declared mediator client, so it can obtain a broker "
        "token — which is a second way to satisfy a signature it should never satisfy"
    )


def test_a_clean_environment_still_starts():
    """Positive control.

    Without it, a service that refused to start under ANY condition would pass
    every test above, and the file would prove nothing at all.
    """
    with _fresh_app() as client:
        assert client.get("/api/copilot/tools").status_code in (200, 401, 403)


def test_no_retired_variable_is_set_by_this_suites_own_fixtures():
    """Turned on the suite itself.

    The fixtures were the thing that got this wrong. If they ever re-export a
    signing secret to make something convenient, the containment property is off
    for every test in the run and only this assertion would notice.
    """
    for name in ("JWT_KEY", "JWT_SECRET", "JWT_PRIVATE_KEY_PEM", "JWT_MEDIATOR_CLIENT_SECRET"):
        assert not os.environ.get(name), (
            f"{name} is set during the test run. The suite is exercising a configuration the "
            "service refuses to start in."
        )


def test_the_public_key_is_present_and_is_not_a_private_key():
    """The other half of the same posture: it must hold the PUBLIC key only.

    Asserting the variable is set would pass just as happily if a private key
    had been pasted into it, which is exactly the mistake worth catching.
    """
    pem = os.environ.get("JWT_PUBLIC_KEY_PEM", "")
    assert pem, "JWT_PUBLIC_KEY_PEM is not set; the service cannot verify anything"
    assert "PUBLIC KEY" in pem
    assert "PRIVATE KEY" not in pem, "a private key is being passed as the public key"
