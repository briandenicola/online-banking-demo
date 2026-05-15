from app.routes.api import _resolve_positive_float_env


def test_resolve_positive_float_env_uses_default_when_missing(monkeypatch):
    monkeypatch.delenv("FOUNDRY_EVAL_TIMEOUT_SECONDS", raising=False)
    assert _resolve_positive_float_env("FOUNDRY_EVAL_TIMEOUT_SECONDS", 12.5) == 12.5


def test_resolve_positive_float_env_uses_default_when_invalid(monkeypatch):
    monkeypatch.setenv("FOUNDRY_EVAL_TIMEOUT_SECONDS", "not-a-number")
    assert _resolve_positive_float_env("FOUNDRY_EVAL_TIMEOUT_SECONDS", 22.0) == 22.0


def test_resolve_positive_float_env_uses_default_when_non_positive(monkeypatch):
    monkeypatch.setenv("FOUNDRY_EVAL_TIMEOUT_SECONDS", "0")
    assert _resolve_positive_float_env("FOUNDRY_EVAL_TIMEOUT_SECONDS", 33.0) == 33.0


def test_resolve_positive_float_env_uses_value_when_positive(monkeypatch):
    monkeypatch.setenv("FOUNDRY_EVAL_TIMEOUT_SECONDS", "420")
    assert _resolve_positive_float_env("FOUNDRY_EVAL_TIMEOUT_SECONDS", 10.0) == 420.0
