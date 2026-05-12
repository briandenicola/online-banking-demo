# Implementation Plan: Generate Sample Documents for Account Opening

**Branch**: `016-sample-documents-account-opening` | **Date**: 2025-07-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/016-sample-documents-account-opening/spec.md` + GitHub Issue #16

## Summary

Generate realistic PDF sample documents (`photo_id` and `proof_of_address`) for test applicant John Smith, along with a Python generation script using `fpdf2` and a companion JSON profile. Documents must contain text-based fields that Azure AI Content Understanding's `prebuilt-documentSearch` analyzer can extract, with field values matching the application form data so identity verification passes.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: `fpdf2` (PDF generation — pure Python, LGPL v3, no system deps)  
**Storage**: File system — static PDFs + JSON committed to `tests/fixtures/sample-documents/`  
**Testing**: Manual verification (PDF readability) + existing pytest suite (no modifications needed)  
**Target Platform**: Cross-platform (developer workstations, CI runners)  
**Project Type**: Test fixture generator (CLI script)  
**Performance Goals**: N/A (one-time generation)  
**Constraints**: Offline-capable, no Azure dependencies, reproducible output  
**Scale/Scope**: 2 document types, 1 test applicant (extensible to more via JSON profiles)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Security by Design | ✅ PASS | No real PII — all data is clearly fictional. No secrets in generated files. |
| II. Private Networking | ✅ N/A | No network communication involved. |
| III. Entra ID Auth | ✅ N/A | No Azure services called during generation. |
| IV. Coding Best Practices | ✅ PASS | Python script follows PEP 8, uses type hints, structured data classes. |
| V. Convention over Configuration | ✅ PASS | Applicant data driven by JSON profile, not hardcoded. Generation script is parameterized. |
| VI. Observability | ✅ N/A | Offline test utility — no telemetry needed. |

**Post-Phase 1 re-check**: All gates still pass. No infrastructure, networking, or auth changes introduced.

## Project Structure

### Documentation (this feature)

```text
specs/016-sample-documents-account-opening/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # PDF library research + decisions
├── data-model.md        # Entity definitions + field mappings
└── quickstart.md        # Usage guide
```

### Source Code (repository root)

```text
tests/fixtures/sample-documents/
├── generate.py                      # PDF generation script (fpdf2)
├── applicants/
│   └── john-smith.json              # Applicant profile + application form data
└── john-smith/
    ├── photo_id.pdf                 # Generated driver's license PDF
    └── proof_of_address.pdf         # Generated utility bill PDF
```

**Structure Decision**: This feature adds test fixtures only — no changes to `src/`. The `tests/fixtures/` directory is new (no existing fixtures directory). The structure supports multiple applicant profiles by convention: each applicant gets a JSON profile in `applicants/` and a named output directory.

## Design Decisions

### D1: Text-Based PDFs (Not Image-Based)

Generated PDFs contain native text (not images of text). This ensures Azure AI Content Understanding can extract fields without OCR, maximizing extraction accuracy. Field labels use names from the document extraction agent's normalization mapping.

### D2: Field Labels Match Normalization Mapping

The `_normalize_field_name()` function in `document_extraction.py` maps raw field names to canonical keys. Documents use labels that map to these canonical keys:

| PDF Field Label | → Normalized Key | Used By |
|-----------------|-------------------|---------|
| `Name` | `name` | Identity verification |
| `Date of Birth` | `dateOfBirth` | Identity verification |
| `Address` | `address` | Identity verification |
| `License Number` | `documentNumber` | Stored in extraction results |
| `Expiry Date` | `expiryDate` | Stored in extraction results |

### D3: Applicant Profile as Single Source of Truth

One JSON file defines both the document content AND the application form data. The generation script reads this file and produces consistent PDFs + form data. This eliminates the risk of field mismatches between documents and application submission.

### D4: Pre-Generated PDFs Committed to Repo

Generated PDFs are committed to the repository (not `.gitignore`d). This allows E2E tests and demos to use them directly without running the generation script first. The script exists for regeneration and extensibility.

## Complexity Tracking

No constitution violations — table not needed.
