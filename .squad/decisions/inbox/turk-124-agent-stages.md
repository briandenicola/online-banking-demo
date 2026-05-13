# Decision: Account-Opening Agent Stages — API Projection (Issue #124)

**Status:** ✅ Implemented & verified in cloud
**Date:** 2026-05-13
**Author:** Turk (Backend)
**Issue:** #124
**Branch/Commit:** squad/p2-wave-3 / 4dc6762

## Context

Admin dashboard expanded application rows showed:
- `Risk Tier: —`
- `Agent Stages: "No stage data available."`

…for **every** account-opening application — including ones that had successfully completed the full Foundry agent pipeline (document extraction → identity verification → compliance → provisioning).

## Investigation

Hypotheses from the issue:
- (a) workflow never ran
- (b) workflow ran but stages not persisted
- (c) persisted but not exposed in API
- (d) exposed but UI field-name mismatch

Direct Cosmos query confirmed:
- The persisted `account-applications` documents store agent outputs in `agentResults[]` (`agentName`, `status`, `confidence`, `findings`, `reasoning`, `timestamp`).
- `riskTier` is nested inside the compliance-check entry's `findings` dict.
- The Pydantic `ApplicationResponse` model has no `stages` or `riskTier` fields at all — they are never serialized.
- The admin UI (`AdminApplicationsTab.tsx`) reads top-level `application.stages[]` and `application.riskTier`.

**Verdict: option (d) — API/UI contract mismatch.** Even fully completed applications looked broken in the UI. (Hypothesis (a) is also true for the *specific* John Smith 5/13 record, but that's because no documents were uploaded — Document Extraction is gated on the `document_uploaded` event. That's expected, not a bug.)

## Decision

Add a thin **outbound projection** in `app/services/projection.py`:

- `project_application(app)` returns the model dump augmented with:
  - `stages[]` — four canonical pipeline stages, each `{name, status, confidence?, reasoning?, timestamp?, details?}`. Completed stages mirror the matching `agentResults` entry; the agent matching the application's current status is marked `in_progress`; everything else is `pending`.
  - `riskTier` — from the compliance-check entry's `findings.riskTier`, when present.
  - Convenience `firstName`/`lastName`/`email` mirrored from `formData` so the admin table doesn't have to drill into nested form data.
- Wired into all four application-returning endpoints: `POST /applications`, `GET /applications/{id}`, `GET /applications`, `PATCH /applications/{id}/review`.

**The persistence schema is unchanged.** No Cosmos migration. No model rewrites. Writers continue to append to `agentResults[]` exactly as before.

## Why a projection (not a model change)

- Keeps Pydantic `ApplicationResponse` aligned with Cosmos storage (no drift between `model_dump()` for writes vs. reads).
- Lets the UI evolve its preferred shape without forcing a data migration.
- Single seam to test (`tests/test_projection.py`) instead of mutating four agent consumers.

## Verification

In-cluster Python against live Cosmos:

```
=== WITH-AGENTS ===
id: 88b88e5f-…  status: rejected  riskTier: high
stages:
  - Document Extraction   completed conf=0.9
  - Identity Verification completed conf=0.98 details="Flags: missing_required_identity_fields"
  - Compliance Check      completed conf=0.98 details="KYC: rejected · Risk: high · Flags: …"
  - Provisioning          completed conf=0.99

=== SUBMITTED ===
id: 066619cf-…  status: submitted  riskTier: None
stages: 4× pending
```

Tests: 6 new (`test_projection.py`) + 14 existing (`test_api.py`) all pass.

## Follow-ups (not in scope)

- The agent display names (`Document Extraction`, `Identity Verification`, `Compliance Check`, `Provisioning`) are hard-coded in `projection.py:PIPELINE_STAGES`. If the pipeline ever grows a stage, that constant needs to be updated. Consider deriving from `app/agents/__init__.py` if/when consumers are reordered.
- Some legacy applications have `agentResults` entries with `reasoning: null`. Harmless — the UI optional-handles it.
- Workflow advancement for applications stuck at `submitted` is **not** a bug. If we want auto-advance even without documents, that's a product decision (defer to Danny).
