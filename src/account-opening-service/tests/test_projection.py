"""Unit tests for the application response projection (issue #124).

The admin UI expects top-level `stages[]` and `riskTier` fields, but the
persisted document stores agent outputs in `agentResults`. These tests cover
the projection that bridges the two without changing storage.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import (
    AgentResult,
    ApplicationResponse,
    ApplicationStatus,
)
from app.services.projection import (
    PIPELINE_STAGES,
    derive_risk_tier,
    derive_stages,
    project_application,
)


def _make_app(status: ApplicationStatus, agent_results: list[AgentResult] | None = None) -> ApplicationResponse:
    now = datetime.now(timezone.utc)
    return ApplicationResponse(
        id="app-1",
        status=status,
        createdAt=now,
        updatedAt=now,
        formData={"firstName": "Jane", "lastName": "Doe", "email": "jane@example.com"},
        documents=[],
        agentResults=agent_results or [],
        auditTrail=[],
    )


class TestDeriveStages:
    def test_pending_when_no_agent_results(self):
        app = _make_app(ApplicationStatus.submitted)
        stages = derive_stages(app)
        assert [s["name"] for s in stages] == [name for _, name in PIPELINE_STAGES]
        assert all(s["status"] == "pending" for s in stages)

    def test_in_progress_marker_matches_status(self):
        app = _make_app(ApplicationStatus.identity_verification)
        stages = derive_stages(app)
        by_name = {s["name"]: s for s in stages}
        assert by_name["Identity Verification"]["status"] == "in_progress"
        assert by_name["Document Extraction"]["status"] == "pending"

    def test_completed_stage_uses_agent_result(self):
        app = _make_app(
            ApplicationStatus.document_extraction,
            agent_results=[
                AgentResult(
                    agentName="document-extraction",
                    status="completed",
                    confidence=0.92,
                    findings={"documentType": "photo_id"},
                    reasoning="extracted ok",
                    timestamp=datetime.now(timezone.utc),
                )
            ],
        )
        stages = derive_stages(app)
        doc_stage = next(s for s in stages if s["name"] == "Document Extraction")
        assert doc_stage["status"] == "completed"
        assert doc_stage["confidence"] == 0.92
        assert doc_stage["reasoning"] == "extracted ok"


class TestDeriveRiskTier:
    def test_returns_none_without_compliance_check(self):
        app = _make_app(ApplicationStatus.identity_verification)
        assert derive_risk_tier(app) is None

    def test_extracts_risk_tier_from_compliance_findings(self):
        app = _make_app(
            ApplicationStatus.compliance_check,
            agent_results=[
                AgentResult(
                    agentName="compliance-check",
                    status="completed",
                    confidence=0.88,
                    findings={"kycStatus": "approved", "riskTier": "low", "flags": []},
                    reasoning="policy result summary",
                    timestamp=datetime.now(timezone.utc),
                )
            ],
        )
        assert derive_risk_tier(app) == "low"


class TestProjectApplication:
    def test_payload_includes_stages_and_risk_tier(self):
        app = _make_app(
            ApplicationStatus.compliance_check,
            agent_results=[
                AgentResult(
                    agentName="compliance-check",
                    status="completed",
                    confidence=0.7,
                    findings={"kycStatus": "review", "riskTier": "medium", "flags": ["a"]},
                    reasoning="needs review",
                    timestamp=datetime.now(timezone.utc),
                )
            ],
        )
        payload = project_application(app)
        assert payload["riskTier"] == "medium"
        assert isinstance(payload["stages"], list)
        assert len(payload["stages"]) == len(PIPELINE_STAGES)
        # Convenience top-level applicant fields mirrored from formData
        assert payload["firstName"] == "Jane"
        assert payload["lastName"] == "Doe"
