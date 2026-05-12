"""Tests for account-opening-service data models (Pydantic).

Validates model schemas, enums, and validation rules defined in the spec:
- ApplicationCreate: required fields, format validation
- ApplicationStatus: 7-state enum
- AgentResult: confidence range
- DocumentMetadata: type constraints
- AuditEntry: serialization
"""
import pytest
from pydantic import ValidationError


class TestApplicationStatus:
    """Verify the ApplicationStatus enum contains all 7 pipeline states."""

    def test_enum_has_exactly_seven_values(self):
        """ApplicationStatus must define exactly 7 states per the spec."""
        from app.models import ApplicationStatus

        assert len(ApplicationStatus) == 7

    def test_all_expected_states_exist(self):
        """Every state from the spec must be present in the enum."""
        from app.models import ApplicationStatus

        expected = {
            "submitted",
            "document_extraction",
            "identity_verification",
            "compliance_check",
            "approved",
            "rejected",
            "pending_review",
        }
        actual = {s.value for s in ApplicationStatus}
        assert actual == expected, f"Missing or extra states: {actual.symmetric_difference(expected)}"


class TestApplicationCreate:
    """Validation rules for the application submission model."""

    def test_valid_application_accepted(self, sample_application):
        """A complete, valid application should parse without error."""
        from app.models import ApplicationCreate

        app = ApplicationCreate(**sample_application)
        assert app.firstName == "John"
        assert app.lastName == "Doe"
        assert app.email == "john.doe@example.com"

    def test_missing_first_name_rejected(self, sample_application):
        """firstName is required — omitting it must raise ValidationError."""
        from app.models import ApplicationCreate

        del sample_application["firstName"]
        with pytest.raises(ValidationError):
            ApplicationCreate(**sample_application)

    def test_missing_last_name_rejected(self, sample_application):
        """lastName is required — omitting it must raise ValidationError."""
        from app.models import ApplicationCreate

        del sample_application["lastName"]
        with pytest.raises(ValidationError):
            ApplicationCreate(**sample_application)

    def test_missing_email_rejected(self, sample_application):
        """email is required — omitting it must raise ValidationError."""
        from app.models import ApplicationCreate

        del sample_application["email"]
        with pytest.raises(ValidationError):
            ApplicationCreate(**sample_application)

    def test_invalid_email_format_rejected(self, sample_application):
        """email must be a valid email format."""
        from app.models import ApplicationCreate

        sample_application["email"] = "not-an-email"
        with pytest.raises(ValidationError):
            ApplicationCreate(**sample_application)

    def test_missing_date_of_birth_rejected(self, sample_application):
        """dateOfBirth is required."""
        from app.models import ApplicationCreate

        del sample_application["dateOfBirth"]
        with pytest.raises(ValidationError):
            ApplicationCreate(**sample_application)

    def test_ssn_must_be_four_digits(self, sample_application):
        """SSN (last 4) must be exactly 4 digits."""
        from app.models import ApplicationCreate

        sample_application["ssn"] = "123"
        with pytest.raises(ValidationError):
            ApplicationCreate(**sample_application)

    def test_ssn_rejects_non_numeric(self, sample_application):
        """SSN must be numeric digits only."""
        from app.models import ApplicationCreate

        sample_application["ssn"] = "abcd"
        with pytest.raises(ValidationError):
            ApplicationCreate(**sample_application)

    def test_missing_account_type_rejected(self, sample_application):
        """accountType is required."""
        from app.models import ApplicationCreate

        del sample_application["accountType"]
        with pytest.raises(ValidationError):
            ApplicationCreate(**sample_application)


class TestAgentResult:
    """Validate AgentResult confidence score constraints."""

    def test_confidence_within_range(self):
        """Confidence must be between 0.0 and 1.0."""
        from app.models import AgentResult

        result = AgentResult(
            status="completed",
            confidence=0.85,
            details={"verified": True},
        )
        assert 0.0 <= result.confidence <= 1.0

    def test_confidence_at_zero(self):
        """Confidence of 0.0 is valid (minimum)."""
        from app.models import AgentResult

        result = AgentResult(status="completed", confidence=0.0, details={})
        assert result.confidence == 0.0

    def test_confidence_at_one(self):
        """Confidence of 1.0 is valid (maximum)."""
        from app.models import AgentResult

        result = AgentResult(status="completed", confidence=1.0, details={})
        assert result.confidence == 1.0

    def test_confidence_above_one_rejected(self):
        """Confidence > 1.0 must be rejected."""
        from app.models import AgentResult

        with pytest.raises(ValidationError):
            AgentResult(status="completed", confidence=1.5, details={})

    def test_confidence_below_zero_rejected(self):
        """Confidence < 0.0 must be rejected."""
        from app.models import AgentResult

        with pytest.raises(ValidationError):
            AgentResult(status="completed", confidence=-0.1, details={})


class TestDocumentMetadata:
    """Validate document type constraints."""

    def test_photo_id_type_accepted(self):
        """'photo_id' is a valid document type."""
        from app.models import DocumentMetadata

        doc = DocumentMetadata(type="photo_id", blobUrl="https://example.com/id.jpg")
        assert doc.type == "photo_id"

    def test_proof_of_address_type_accepted(self):
        """'proof_of_address' is a valid document type."""
        from app.models import DocumentMetadata

        doc = DocumentMetadata(type="proof_of_address", blobUrl="https://example.com/bill.pdf")
        assert doc.type == "proof_of_address"

    def test_invalid_type_rejected(self):
        """Only 'photo_id' and 'proof_of_address' are allowed."""
        from app.models import DocumentMetadata

        with pytest.raises(ValidationError):
            DocumentMetadata(type="passport_scan", blobUrl="https://example.com/x.jpg")


class TestAuditEntry:
    """Validate audit trail entry structure and serialization."""

    def test_audit_entry_has_required_fields(self):
        """AuditEntry must contain timestamp, agent, action, previousState, newState."""
        from app.models import AuditEntry

        entry = AuditEntry(
            timestamp="2026-05-11T10:00:00Z",
            agent="document-extraction",
            action="extracted",
            previousState="submitted",
            newState="document_extraction",
        )
        assert entry.timestamp is not None
        assert entry.agent == "document-extraction"
        assert entry.action == "extracted"
        assert entry.previousState == "submitted"
        assert entry.newState == "document_extraction"

    def test_audit_entry_serializes_to_dict(self):
        """AuditEntry must be serializable (for Cosmos DB storage)."""
        from app.models import AuditEntry

        entry = AuditEntry(
            timestamp="2026-05-11T10:00:00Z",
            agent="identity-verification",
            action="verified",
            previousState="document_extraction",
            newState="identity_verification",
        )
        data = entry.model_dump()
        assert isinstance(data, dict)
        assert "timestamp" in data
        assert "agent" in data
        assert "previousState" in data
        assert "newState" in data
