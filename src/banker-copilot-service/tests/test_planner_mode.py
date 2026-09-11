"""The planner mode must be declared, never inferred.

`planner_mode()` previously returned "deterministic" whenever the Foundry preconditions were
not all satisfied. That turned three unrelated failures — the `agent_framework_foundry` extra
missing from the image, an unset endpoint, an unset model — into one indistinguishable
success. A deployment that had silently lost its model access still reported `status: ready`
on /readyz and answered questions with no model behind it, and a reviewer checking supervisor
disagreement would have been measuring a canned script while reading it as agreement.

Failure looked exactly like success, and the function had no tests at all. These are they.
"""

from __future__ import annotations

import pytest

from app.config import ConfigurationError
from app.planner import loop as planner_loop
from app.planner.loop import planner_mode

FOUNDRY_ENV = {
    "FOUNDRY_PROJECT_ENDPOINT": "https://example-foundry.services.ai.azure.com/api/projects/p",
    "FOUNDRY_MODEL": "gpt-5.4-mini",
}

ALL_PLANNER_ENV = (
    "COPILOT_PLANNER_MODE",
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_MODEL",
    "AZURE_AI_PROJECT_ENDPOINT",
    "AZURE_AI_MODEL_DEPLOYMENT",
)


@pytest.fixture(autouse=True)
def _clean_planner_env(monkeypatch):
    """No ambient configuration leaks in: every test states its own world."""
    for name in ALL_PLANNER_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def foundry_importable(monkeypatch):
    monkeypatch.setattr(planner_loop, "AGENT_FRAMEWORK_AVAILABLE", True)


def test_foundry_is_the_default_when_fully_configured(monkeypatch, foundry_importable):
    for key, value in FOUNDRY_ENV.items():
        monkeypatch.setenv(key, value)

    assert planner_mode() == "foundry"


def test_deterministic_requires_someone_to_have_typed_it(monkeypatch):
    """The only route to a model-less planner is an explicit request for one."""
    monkeypatch.setenv("COPILOT_PLANNER_MODE", "deterministic")

    # Deliberately no endpoint, no model, no package. None of it is consulted: the mode was
    # asked for, not inferred from what happens to be missing.
    monkeypatch.setattr(planner_loop, "AGENT_FRAMEWORK_AVAILABLE", False)

    assert planner_mode() == "deterministic"


@pytest.mark.parametrize(
    "missing_var, expected_phrase",
    [
        ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_PROJECT_ENDPOINT is unset"),
        ("FOUNDRY_MODEL", "FOUNDRY_MODEL is unset"),
    ],
)
def test_missing_config_raises_and_names_the_missing_part(
    monkeypatch, foundry_importable, missing_var, expected_phrase
):
    """Not merely "it raised" — it must say which part is absent.

    An error that reports only "planner misconfigured" sends the next person to read this
    file. The point of failing closed is to shorten that, not to relocate it.
    """
    for key, value in FOUNDRY_ENV.items():
        if key != missing_var:
            monkeypatch.setenv(key, value)

    with pytest.raises(ConfigurationError) as excinfo:
        planner_mode()

    assert expected_phrase in str(excinfo.value)


def test_missing_package_raises_rather_than_degrading(monkeypatch):
    """A build that dropped the Foundry extra is an image defect, not a runtime mode."""
    for key, value in FOUNDRY_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(planner_loop, "AGENT_FRAMEWORK_AVAILABLE", False)

    with pytest.raises(ConfigurationError) as excinfo:
        planner_mode()

    assert "agent_framework_foundry" in str(excinfo.value)


def test_every_missing_part_is_reported_together(monkeypatch):
    """Fixing one cause at a time, one redeploy at a time, is the slow way to learn all three."""
    monkeypatch.setattr(planner_loop, "AGENT_FRAMEWORK_AVAILABLE", False)

    with pytest.raises(ConfigurationError) as excinfo:
        planner_mode()

    message = str(excinfo.value)
    assert "agent_framework_foundry" in message
    assert "FOUNDRY_PROJECT_ENDPOINT is unset" in message
    assert "FOUNDRY_MODEL is unset" in message


def test_unrecognised_mode_raises_instead_of_guessing(monkeypatch, foundry_importable):
    """`COPILOT_PLANNER_MODE=determinstic` must not quietly become foundry."""
    for key, value in FOUNDRY_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("COPILOT_PLANNER_MODE", "determinstic")

    with pytest.raises(ConfigurationError) as excinfo:
        planner_mode()

    assert "determinstic" in str(excinfo.value)


def test_legacy_azure_ai_names_still_satisfy_foundry(monkeypatch, foundry_importable):
    """The rename is still in flight; deployments on the old names must not start failing."""
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", FOUNDRY_ENV["FOUNDRY_PROJECT_ENDPOINT"])
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT", FOUNDRY_ENV["FOUNDRY_MODEL"])

    assert planner_mode() == "foundry"


def test_whitespace_only_endpoint_counts_as_unset(monkeypatch, foundry_importable):
    """A ConfigMap key present but blank is the same absence, and must fail the same way."""
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "   ")
    monkeypatch.setenv("FOUNDRY_MODEL", FOUNDRY_ENV["FOUNDRY_MODEL"])

    with pytest.raises(ConfigurationError) as excinfo:
        planner_mode()

    assert "FOUNDRY_PROJECT_ENDPOINT is unset" in str(excinfo.value)
