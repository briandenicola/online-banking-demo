"""Tests for the anomaly detection service v2.0 (Foundry-based)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import AdminStats, FlaggedTransaction, RiskAssessment, ScoredTransaction
from app.services.anomaly_service import AnalyzerPipeline, FoundryRiskAnalyzer, FLAGGING_THRESHOLD
from tests.conftest import FakeAnalyzer


class TestHealthEndpoints:
    def test_health_returns_healthy(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_healthz_returns_service_info(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ai-service"
        assert data["version"] == "2.0.0"
        assert "timestamp" in data


class TestAnalyzerPipeline:
    """Test the extensible analyzer pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_no_analyzers_returns_zero_score(self):
        pipeline = AnalyzerPipeline()
        result = await pipeline.assess({"amount": 100})
        assert result.riskScore == 0.0
        assert "no_analyzers" in result.flags

    @pytest.mark.asyncio
    async def test_pipeline_single_analyzer(self, sample_transaction):
        pipeline = AnalyzerPipeline()
        pipeline.register(FakeAnalyzer("test", 0.3, "Slightly risky"))
        result = await pipeline.assess(sample_transaction)
        assert result.riskScore == 0.3
        assert result.explanation == "Slightly risky"

    @pytest.mark.asyncio
    async def test_pipeline_returns_highest_risk(self, sample_transaction):
        pipeline = AnalyzerPipeline()
        pipeline.register(FakeAnalyzer("low", 0.1, "Low risk"))
        pipeline.register(FakeAnalyzer("high", 0.8, "High risk", ["suspicious"]))
        result = await pipeline.assess(sample_transaction)
        assert result.riskScore == 0.8
        assert result.explanation == "High risk"
        assert "suspicious" in result.flags

    @pytest.mark.asyncio
    async def test_pipeline_skips_disabled_analyzers(self, sample_transaction):
        pipeline = AnalyzerPipeline()
        pipeline.register(FakeAnalyzer("disabled", 0.9, "Should skip", enabled=False))
        pipeline.register(FakeAnalyzer("enabled", 0.2, "Normal"))
        result = await pipeline.assess(sample_transaction)
        assert result.riskScore == 0.2

    @pytest.mark.asyncio
    async def test_pipeline_handles_analyzer_exception(self, sample_transaction):
        """If one analyzer throws, others still run."""
        pipeline = AnalyzerPipeline()

        class BrokenAnalyzer(FakeAnalyzer):
            async def analyze(self, transaction):
                raise RuntimeError("Analyzer crashed")

        pipeline.register(BrokenAnalyzer("broken", 0.9))
        pipeline.register(FakeAnalyzer("fallback", 0.2, "Fallback"))
        result = await pipeline.assess(sample_transaction)
        assert result.riskScore == 0.2

    @pytest.mark.asyncio
    async def test_pipeline_register_adds_analyzer(self):
        pipeline = AnalyzerPipeline()
        assert len(pipeline.analyzers) == 0
        pipeline.register(FakeAnalyzer("a", 0.1))
        assert len(pipeline.analyzers) == 1
        assert pipeline.analyzers[0].name == "a"


class TestFoundryRiskAnalyzer:
    """Test the Foundry-based risk analyzer."""

    def test_not_enabled_without_initialization(self):
        analyzer = FoundryRiskAnalyzer()
        assert analyzer.enabled is False
        assert analyzer.name == "foundry-risk"

    def test_enabled_after_initialization(self):
        analyzer = FoundryRiskAnalyzer()
        mock_agent = MagicMock()
        analyzer.initialize(mock_agent)
        assert analyzer.enabled is True

    def test_parse_valid_json_response(self):
        analyzer = FoundryRiskAnalyzer()
        response = '{"riskScore": 0.75, "explanation": "Large transfer", "flags": ["large_amount"]}'
        result = analyzer._parse_response(response)
        assert result.riskScore == 0.75
        assert result.explanation == "Large transfer"
        assert "large_amount" in result.flags

    def test_parse_json_with_markdown_fences(self):
        analyzer = FoundryRiskAnalyzer()
        response = '```json\n{"riskScore": 0.4, "explanation": "Moderate", "flags": []}\n```'
        result = analyzer._parse_response(response)
        assert result.riskScore == 0.4

    def test_parse_invalid_json_returns_fallback(self):
        analyzer = FoundryRiskAnalyzer()
        result = analyzer._parse_response("not json at all")
        assert result.riskScore == 0.5
        assert "parse_error" in result.flags

    def test_parse_clamps_risk_score(self):
        analyzer = FoundryRiskAnalyzer()
        result = analyzer._parse_response('{"riskScore": 1.5, "explanation": "Over", "flags": []}')
        assert result.riskScore == 1.0
        result = analyzer._parse_response('{"riskScore": -0.5, "explanation": "Under", "flags": []}')
        assert result.riskScore == 0.0


class TestRiskAssessmentModel:
    """Test the RiskAssessment Pydantic model."""

    def test_valid_risk_assessment(self):
        ra = RiskAssessment(riskScore=0.5, explanation="Test", flags=["flag1"])
        assert ra.riskScore == 0.5
        assert ra.flags == ["flag1"]

    def test_risk_score_bounds(self):
        with pytest.raises(Exception):
            RiskAssessment(riskScore=1.5, explanation="Too high", flags=[])
        with pytest.raises(Exception):
            RiskAssessment(riskScore=-0.1, explanation="Too low", flags=[])

    def test_default_flags_empty(self):
        ra = RiskAssessment(riskScore=0.1, explanation="Normal")
        assert ra.flags == []


class TestDetectEndpoint:
    """Test the synchronous /detect endpoint."""

    def test_detect_returns_503_without_pipeline(self, client_with_auth):
        """Without lifespan (no pipeline), detect returns 503."""
        response = client_with_auth.post(
            "/detect",
            json={
                "transactionId": "txn-001",
                "accountId": "acc-001",
                "amount": 100,
                "type": "Purchase",
                "description": "Coffee",
            },
        )
        assert response.status_code == 503


class TestFlaggingThreshold:
    """Test the flagging threshold constant."""

    def test_threshold_is_0_7(self):
        assert FLAGGING_THRESHOLD == 0.7


class TestAiCallsCounter:
    """Counter must live in Redis (cross-pod), not in-process. Issue #130."""

    @pytest.mark.asyncio
    async def test_increment_uses_utc_day_bucketed_key_and_sets_ttl_on_create(self):
        from app.services import anomaly_service

        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)  # first writer
        fake_redis.expire = AsyncMock()

        await anomaly_service._increment_ai_calls_counter(fake_redis)

        from datetime import datetime, timezone
        expected_key = f"ai:metrics:calls:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        fake_redis.incr.assert_awaited_once_with(expected_key)
        fake_redis.expire.assert_awaited_once_with(expected_key, 36 * 60 * 60)

    @pytest.mark.asyncio
    async def test_increment_does_not_reset_ttl_on_subsequent_calls(self):
        from app.services import anomaly_service

        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=42)  # key already existed
        fake_redis.expire = AsyncMock()

        await anomaly_service._increment_ai_calls_counter(fake_redis)

        fake_redis.expire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_increment_swallows_redis_errors(self):
        """Redis being down must NOT crash the AI request path."""
        from app.services import anomaly_service

        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(side_effect=ConnectionError("redis down"))

        # Must not raise
        await anomaly_service._increment_ai_calls_counter(fake_redis)

    @pytest.mark.asyncio
    async def test_get_returns_zero_when_redis_unavailable(self):
        from app.services import anomaly_service

        assert await anomaly_service.get_ai_calls_today_from_redis(None) == 0

        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        assert await anomaly_service.get_ai_calls_today_from_redis(fake_redis) == 0

    @pytest.mark.asyncio
    async def test_get_returns_int_from_redis_value(self):
        from app.services import anomaly_service

        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value=b"17")
        assert await anomaly_service.get_ai_calls_today_from_redis(fake_redis) == 17

    def test_no_in_memory_counter_attribute_on_pipeline(self):
        """Guard against regression: no module/class-level counter state."""
        from app.services import anomaly_service

        pipeline = anomaly_service.AnalyzerPipeline()
        for attr in ("ai_calls_today", "_ai_calls_today", "calls_today", "_calls_today"):
            assert not hasattr(pipeline, attr), f"in-memory counter {attr!r} must not exist"
            assert not hasattr(anomaly_service, attr), f"module-level counter {attr!r} must not exist"


class TestFoundryAgentSignatureContract:
    """Pin the FoundryAgent constructor contract for our pinned SDK version.

    Issue #137 + #130: agent-framework-foundry 1.2.x removed ``model=`` from
    ``FoundryAgent.__init__`` and requires the model deployment name to flow
    via ``default_options={"model": ...}``. Omitting it causes the underlying
    ``responses.create()`` call to 400 with "Missing required parameter:
    'model'", which surfaces as eval failures (#137) and a stuck "AI Calls
    Today" counter (#130, downstream).

    These tests fail loudly on local pytest if either:
      - any FoundryAgent call site reintroduces ``model=`` (rejected kwarg), or
      - any FoundryAgent call site forgets ``default_options={"model": ...}``
        (causes runtime 400).
    """

    def _agent_kwargs(self):
        import inspect
        from agent_framework_foundry import FoundryAgent
        return set(inspect.signature(FoundryAgent.__init__).parameters.keys())

    @pytest.mark.parametrize(
        "module_path",
        [
            "app/services/anomaly_service.py",
            "app/routes/api.py",
        ],
    )
    def test_foundry_agent_call_sites_use_default_options_for_model(self, module_path):
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / module_path).read_text()
        sdk_kwargs = self._agent_kwargs()

        # Strip Python line comments (so prose like `model=` inside a
        # `# ...` comment is not mistaken for a kwarg).
        src_no_comments = re.sub(r"(?m)#.*$", "", src)

        # Match every FoundryAgent(...) call (multi-line, balanced enough for
        # our codebase — no nested FoundryAgent constructions).
        for m in re.finditer(r"FoundryAgent\(([^)]*)\)", src_no_comments, re.DOTALL):
            body = m.group(1)
            # Only top-level kwargs: a name followed by '=' that is NOT '=='.
            used_kwargs = set(re.findall(r"\b(\w+)\s*=(?!=)", body))
            # Drop names that appear inside a dict literal (e.g. {"model": ...}).
            dict_inner_keys = set(re.findall(r"\{[^{}]*\}", body))
            for inner in re.findall(r"\{([^{}]*)\}", body):
                # Anything between { and } is a dict literal — kwargs there
                # are not constructor kwargs.
                inner_kwargs = set(re.findall(r"\b(\w+)\s*=(?!=)", inner))
                used_kwargs -= inner_kwargs

            unsupported = used_kwargs - sdk_kwargs
            assert not unsupported, (
                f"{module_path}: FoundryAgent() kwargs not in SDK signature: "
                f"{unsupported}. Supported: {sorted(sdk_kwargs)}"
            )
            assert "model" not in used_kwargs, (
                f"{module_path}: must not pass model= to FoundryAgent — "
                f"use default_options={{'model': ...}} instead (#137)"
            )
            assert "default_options" in used_kwargs, (
                f"{module_path}: FoundryAgent() must pass "
                f"default_options={{'model': ...}} so responses.create() "
                f"receives the model deployment name (#137 / #130)"
            )
            assert re.search(r"default_options\s*=\s*\{[^{}]*['\"]extra_body['\"]\s*:\s*\{[^{}]*['\"]model['\"]", body), (
                f"{module_path}: default_options must wrap model under extra_body — "
                f"FoundryAgent's underlying _FoundryAgentChatClient does not propagate "
                f"top-level `model` to responses.create(); use "
                f"default_options={{'extra_body': {{'model': ...}}}} (#137 / #130)"
            )
