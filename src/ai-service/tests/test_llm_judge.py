from app.routes.api import (
    _build_judge_instructions,
    _build_judge_user_prompt,
    _evaluator_description,
    _parse_judge_scores,
)


def test_build_judge_instructions_lists_all_criteria():
    text = _build_judge_instructions(["coherence", "relevance"])
    assert "coherence" in text
    assert "relevance" in text
    assert "1-5" in text
    assert "passing threshold" in text.lower()


def test_evaluator_description_handles_builtin_prefix():
    plain = _evaluator_description("coherence")
    prefixed = _evaluator_description("builtin.coherence")
    assert plain == prefixed


def test_evaluator_description_unknown_evaluator_returns_default():
    desc = _evaluator_description("nonexistent_evaluator_name")
    assert "1-5" in desc


def test_build_judge_user_prompt_includes_all_sections():
    prompt = _build_judge_user_prompt(
        system_prompt="be helpful",
        user_prompt="assess transaction",
        assistant_text='{"risk":0.5}',
        evaluators=["coherence", "fluency"],
    )
    assert "be helpful" in prompt
    assert "assess transaction" in prompt
    assert '{"risk":0.5}' in prompt
    assert '"coherence"' in prompt
    assert '"fluency"' in prompt


def test_parse_judge_scores_plain_json():
    raw = (
        '{"coherence": {"score": 4, "passed": true, "reason": "clear"}, '
        '"fluency": {"score": 2, "passed": false, "reason": "rough"}}'
    )
    out = _parse_judge_scores(raw, ["coherence", "fluency"])
    assert out["coherence"]["score"] == 4.0
    assert out["coherence"]["passed"] is True
    assert out["coherence"]["reason"] == "clear"
    assert out["fluency"]["passed"] is False


def test_parse_judge_scores_strips_markdown_fence():
    raw = '```json\n{"coherence": {"score": 5, "passed": true, "reason": "ok"}}\n```'
    out = _parse_judge_scores(raw, ["coherence"])
    assert out["coherence"]["score"] == 5.0
    assert out["coherence"]["passed"] is True


def test_parse_judge_scores_handles_prose_around_json():
    raw = (
        "Here is the evaluation:\n"
        '{"coherence": {"score": 3, "passed": true, "reason": "acceptable"}}\n'
        "End."
    )
    out = _parse_judge_scores(raw, ["coherence"])
    assert out["coherence"]["score"] == 3.0
    assert out["coherence"]["passed"] is True


def test_parse_judge_scores_infers_passed_from_score_threshold():
    raw = '{"coherence": {"score": 4, "reason": "good"}}'
    out = _parse_judge_scores(raw, ["coherence"])
    assert out["coherence"]["score"] == 4.0
    assert out["coherence"]["passed"] is True


def test_parse_judge_scores_infers_failed_from_low_score():
    raw = '{"coherence": {"score": 1, "reason": "bad"}}'
    out = _parse_judge_scores(raw, ["coherence"])
    assert out["coherence"]["score"] == 1.0
    assert out["coherence"]["passed"] is False


def test_parse_judge_scores_returns_empty_on_invalid_json():
    out = _parse_judge_scores("not json at all", ["coherence"])
    assert out == {}


def test_parse_judge_scores_returns_empty_on_blank_input():
    out = _parse_judge_scores("", ["coherence"])
    assert out == {}


def test_parse_judge_scores_resolves_builtin_prefix():
    raw = '{"coherence": {"score": 5, "passed": true, "reason": "ok"}}'
    out = _parse_judge_scores(raw, ["builtin.coherence"])
    assert out["builtin.coherence"]["score"] == 5.0
