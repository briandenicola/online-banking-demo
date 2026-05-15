from app.eval_debug import (
    _build_eval_prompt,
    _parse_positive_float,
    _parse_evaluators,
    _parse_transaction_json,
    _resolve_cli_or_env_positive_float,
    _resolve_positive_float_env,
)


def test_build_eval_prompt_masks_account_suffix():
    prompt = _build_eval_prompt(
        {
            "amount": 1234.5,
            "type": "TRANSFER",
            "description": "Test transfer",
            "category": "Transfer",
            "accountId": "acct-1234567890",
        }
    )
    assert "****7890" in prompt
    assert "$1,234.50" in prompt


def test_parse_transaction_json_requires_object():
    try:
        _parse_transaction_json('["not-an-object"]')
    except ValueError as exc:
        assert "must be an object" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-object JSON")


def test_parse_evaluators_trims_and_validates():
    assert _parse_evaluators(" coherence, fluency ,relevance ") == [
        "coherence",
        "fluency",
        "relevance",
    ]


def test_parse_evaluators_rejects_empty():
    try:
        _parse_evaluators("  ,   ")
    except ValueError as exc:
        assert "at least one evaluator" in str(exc)
    else:
        raise AssertionError("Expected ValueError when evaluators are empty")


def test_resolve_positive_float_env_defaults(monkeypatch):
    monkeypatch.delenv("EVAL_DEBUG_FLOAT", raising=False)
    assert _resolve_positive_float_env("EVAL_DEBUG_FLOAT", 7.0) == 7.0

    monkeypatch.setenv("EVAL_DEBUG_FLOAT", "invalid")
    assert _resolve_positive_float_env("EVAL_DEBUG_FLOAT", 7.0) == 7.0

    monkeypatch.setenv("EVAL_DEBUG_FLOAT", "-5")
    assert _resolve_positive_float_env("EVAL_DEBUG_FLOAT", 7.0) == 7.0

    monkeypatch.setenv("EVAL_DEBUG_FLOAT", "9.5")
    assert _resolve_positive_float_env("EVAL_DEBUG_FLOAT", 7.0) == 9.5


def test_parse_positive_float():
    assert _parse_positive_float("3.5", "x") == 3.5

    try:
        _parse_positive_float("abc", "x")
    except ValueError as exc:
        assert "must be a number" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-numeric input")

    try:
        _parse_positive_float("0", "x")
    except ValueError as exc:
        assert "must be > 0" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-positive input")


def test_resolve_cli_or_env_positive_float(monkeypatch):
    monkeypatch.setenv("DEBUG_VALUE", "8")
    assert _resolve_cli_or_env_positive_float(None, "DEBUG_VALUE", 2.0) == 8.0
    assert _resolve_cli_or_env_positive_float(4.0, "DEBUG_VALUE", 2.0) == 4.0
    assert _resolve_cli_or_env_positive_float(-1.0, "DEBUG_VALUE", 2.0) == 2.0
