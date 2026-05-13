"""Projection helpers that derive UI-facing fields from the raw application record.

The persisted `ApplicationResponse` stores agent outputs in `agentResults` and the
risk tier inside `agentResults[].findings.riskTier`. The admin UI, however, expects
top-level `stages[]` and `riskTier` fields. This module bridges that gap on the
response side without changing the storage schema.
"""
from __future__ import annotations

from typing import Any

from ..models import ApplicationResponse, ApplicationStatus

# Canonical pipeline order. Names match the `agentName` strings emitted by the
# four agent consumers (document_extraction.py, identity_verification.py,
# compliance_check.py, provisioning.py).
PIPELINE_STAGES: list[tuple[str, str]] = [
    ("document-extraction", "Document Extraction"),
    ("identity-verification", "Identity Verification"),
    ("compliance-check", "Compliance Check"),
    ("provisioning", "Provisioning"),
]

# Maps the application status to the agent that owns that status.
_STATUS_TO_AGENT: dict[str, str] = {
    ApplicationStatus.document_extraction.value: "document-extraction",
    ApplicationStatus.identity_verification.value: "identity-verification",
    ApplicationStatus.compliance_check.value: "compliance-check",
}


def _normalize_stage_status(raw: str | None) -> str:
    if not raw:
        return "pending"
    value = str(raw).lower().strip()
    if value in {"completed", "complete", "success", "succeeded", "done"}:
        return "completed"
    if value in {"failed", "error", "rejected"}:
        return "failed"
    if value in {"in_progress", "running", "started"}:
        return "in_progress"
    return "pending"


def _latest_result_by_agent(agent_results: list[Any]) -> dict[str, dict[str, Any]]:
    """Return the most recent agentResults entry per agentName as plain dicts."""
    latest: dict[str, dict[str, Any]] = {}
    for entry in agent_results or []:
        data = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
        name = data.get("agentName")
        if not name:
            continue
        previous = latest.get(name)
        if previous is None:
            latest[name] = data
            continue
        # Prefer the entry with a later timestamp; fall back to last-write.
        prev_ts = previous.get("timestamp")
        new_ts = data.get("timestamp")
        if new_ts and (not prev_ts or str(new_ts) >= str(prev_ts)):
            latest[name] = data
    return latest


def derive_stages(application: ApplicationResponse) -> list[dict[str, Any]]:
    """Build the UI's `stages[]` array from the application's agentResults."""
    by_agent = _latest_result_by_agent(application.agentResults)
    in_progress_agent = _STATUS_TO_AGENT.get(application.status.value)

    stages: list[dict[str, Any]] = []
    for agent_name, display_name in PIPELINE_STAGES:
        result = by_agent.get(agent_name)
        if result:
            findings = result.get("findings") or {}
            stage_status = _normalize_stage_status(result.get("status"))
            stage: dict[str, Any] = {
                "name": display_name,
                "status": stage_status,
                "confidence": result.get("confidence"),
                "reasoning": result.get("reasoning"),
            }
            timestamp = result.get("timestamp")
            if timestamp is not None:
                stage["timestamp"] = timestamp
            details_bits: list[str] = []
            if "kycStatus" in findings:
                details_bits.append(f"KYC: {findings['kycStatus']}")
            if "riskTier" in findings:
                details_bits.append(f"Risk: {findings['riskTier']}")
            if findings.get("flags"):
                flags = findings["flags"]
                if isinstance(flags, list) and flags:
                    details_bits.append(f"Flags: {', '.join(str(f) for f in flags[:3])}")
            if details_bits:
                stage["details"] = " · ".join(details_bits)
        else:
            status = "in_progress" if agent_name == in_progress_agent else "pending"
            stage = {"name": display_name, "status": status}
        stages.append(stage)
    return stages


def derive_risk_tier(application: ApplicationResponse) -> str | None:
    """Pull the risk tier from the latest compliance-check agent result."""
    by_agent = _latest_result_by_agent(application.agentResults)
    compliance = by_agent.get("compliance-check")
    if not compliance:
        return None
    findings = compliance.get("findings") or {}
    risk_tier = findings.get("riskTier")
    return str(risk_tier) if risk_tier else None


def project_application(application: ApplicationResponse) -> dict[str, Any]:
    """Serialize an application with `stages[]` and `riskTier` projected for the UI."""
    payload = application.model_dump(mode="json")
    payload["stages"] = derive_stages(application)
    risk_tier = derive_risk_tier(application)
    if risk_tier is not None:
        payload["riskTier"] = risk_tier
    # Mirror form-data convenience fields onto the top level so the admin table
    # renders names without having to drill into formData.
    form_data = payload.get("formData") or {}
    for key in ("firstName", "lastName", "email"):
        if key not in payload and form_data.get(key):
            payload[key] = form_data[key]
    return payload


def project_applications(applications: list[ApplicationResponse]) -> list[dict[str, Any]]:
    return [project_application(app) for app in applications]
