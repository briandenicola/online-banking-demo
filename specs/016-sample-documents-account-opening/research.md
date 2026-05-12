# Research: Sample Documents for Account Opening

**Feature**: #16 — Generate sample documents for account opening
**Date**: 2025-07-25

## R1: PDF Generation Library

**Decision**: `fpdf2`

**Rationale**: Best fit for both document types. Provides `set_xy()` + `cell()` for precise card-layout positioning (driver's license) and a clean `table()` context manager for structured layouts (utility bill). Pure Python, no system dependencies, LGPL v3 license, Python 3.11+ compatible, actively maintained by the py-pdf org.

**Alternatives considered**:
- `reportlab`: Equally capable but requires two paradigms (Canvas vs Platypus) and has a more verbose table API
- `weasyprint`: Requires system-level Pango/GLib/HarfBuzz C libraries — violates lightweight/offline requirement
- `borb`: AGPL v3 license — requires source release for any usage, not suitable

**Install**: `pip install fpdf2` (deps: Pillow, defusedxml, fontTools — all pure Python)

## R2: Document Format for Azure AI Content Understanding

**Decision**: PDF with clear text-based layouts (not images of text)

**Rationale**: The `prebuilt-documentSearch` analyzer in Azure AI Content Understanding works with document text extraction. Text-based PDFs provide the highest extraction accuracy because text is natively embedded rather than requiring OCR. The analyzer extracts fields by name matching, and the document extraction agent normalizes field names via a known mapping (see `_normalize_field_name` in `document_extraction.py`).

**Key insight**: The field normalization mapping tells us exactly which field labels to use in our documents:
- `Full Name` or `Name` → `name`
- `Date of Birth` or `DOB` → `dateOfBirth`
- `Address` or `Home Address` → `address`
- `Document Number` or `License Number` or `ID Number` → `documentNumber`
- `Expiry Date` or `Expiration Date` → `expiryDate`

## R3: Identity Verification Matching Rules

**Decision**: Documents must exactly match application form data for name, DOB, and address

**Rationale**: The identity verifier (an LLM via Azure AI Foundry) compares extracted document fields against `_summarize_form_data()` output which includes: `firstName`, `lastName`, `dateOfBirth`, `address`. Verification rules:
- **Name**: First + last must match; minor typos/nicknames acceptable, significant variations rejected
- **DOB**: Any mismatch is rejected
- **Address**: Street/city/state must match; minor postal code discrepancies acceptable

**Implication**: The companion application JSON and document text must use identical values for these fields.

## R4: Document Storage Location

**Decision**: `tests/fixtures/sample-documents/` in repo root

**Rationale**: 
- `tests/fixtures/` follows the pattern expected by the issue requirements
- Separating from `src/` keeps test data out of service containers
- The generation script goes alongside as `tests/fixtures/sample-documents/generate.py`
- The companion application data JSON goes at `tests/fixtures/sample-documents/applicants/john-smith.json`

## R5: Document Upload Integration

**Decision**: Documents are uploaded via multipart POST to `/api/account-opening/applications/{id}/documents`

**Rationale**: From `routes.py:49-95`, the upload endpoint:
- Accepts `documentType` as a form field (`photo_id` or `proof_of_address`)
- Accepts `file` as an `UploadFile`
- Saves to `data/documents/{application_id}/` inside the service directory
- Sets `blobUrl` to the local file path (not a real blob URL in local mode)
- No file format validation — accepts any file type

**Implication**: The generated PDFs can be uploaded directly; no format conversion needed.
