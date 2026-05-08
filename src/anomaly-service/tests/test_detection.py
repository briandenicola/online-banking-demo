"""Tests for the anomaly detection service v2.0 (Foundry-based)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import (
    RiskAssessment,
    FoundryRiskAnalyzer,
    AnalyzerPipeline,
    ScoredTransaction,
    FlaggedTransaction,
    AdminStats,
    FLAGGING_THRESHOLD,
)
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
        assert data["service"] == "anomaly-service"
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
        mock_client = MagicMock()
        analyzer.initialize(mock_client, "gpt-5.4-mini")
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

    def test_detect_returns_503_without_pipeline(self, client):
        """Without lifespan (no pipeline), detect returns 503."""
        response = client.post("/detect", json={"amount": 100, "type": "Purchase"})
        assert response.status_code == 503


class TestFlaggingThreshold:
    """Test the flagging threshold constant."""

    def test_threshold_is_0_7(self):
        assert FLAGGING_THRESHOLD == 0.7

