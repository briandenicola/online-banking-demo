# Tasks: Generate Sample Documents for Account Opening

**Input**: Design documents from `/specs/016-sample-documents-account-opening/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: Not requested in the feature specification. No test tasks included.

**Organization**: Tasks are grouped by functional requirement (mapped to user stories) to enable independent implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## User Story Mapping

| Story | Spec Requirements | Description |
|-------|-------------------|-------------|
| US1 | FR-1, FR-4 | Photo ID (driver's license) PDF generation |
| US2 | FR-2, FR-4 | Proof of Address (utility bill) PDF generation |
| US3 | FR-4, FR-5 | CLI generation script with profile support |

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create directory structure and establish the project layout

- [ ] T001 Create directory structure: `tests/fixtures/sample-documents/`, `tests/fixtures/sample-documents/applicants/`, `tests/fixtures/sample-documents/john-smith/`
- [ ] T002 [P] Create `tests/fixtures/sample-documents/requirements.txt` with `fpdf2` dependency pinned

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define data models and the applicant profile JSON that ALL document generation depends on

**⚠️ CRITICAL**: No document generation can begin until the applicant profile and data models exist

- [ ] T003 Create applicant profile JSON at `tests/fixtures/sample-documents/applicants/john-smith.json` containing: ApplicantProfile fields (firstName, lastName, dateOfBirth, address, email, phone, ssn_last4, employer, jobTitle, annualIncome, accountType), PhotoIdSpec fields (documentNumber, expiryDate, issuingState, documentClass), ProofOfAddressSpec fields (providerName, accountNumber, billDate, amountDue), and ApplicationFormData object matching the `ApplicationCreate` model schema — all using values from spec.md Test Applicant Profile section
- [ ] T004 Create `tests/fixtures/sample-documents/models.py` defining Python dataclasses: `ApplicantProfile` (with validation: ISO date for dateOfBirth, 4-digit ssn_last4, 2-letter state code, 5-digit zip, accountType in checking/savings/both), `PhotoIdSpec`, `ProofOfAddressSpec`, and a `load_profile(path: str)` function that reads the JSON and returns typed instances — use field names from data-model.md

**Checkpoint**: Foundation ready — applicant profile JSON is the single source of truth for all subsequent tasks

---

## Phase 3: User Story 1 — Photo ID Document Generation (Priority: P1) 🎯 MVP

**Goal**: Generate a text-based PDF driver's license for John Smith with fields extractable by Azure AI Content Understanding

**Independent Test**: Open `tests/fixtures/sample-documents/john-smith/photo_id.pdf` in a PDF viewer; verify text is selectable, field labels are `Name`, `Date of Birth`, `Address`, `License Number`, `Expiry Date`, and all values match `applicants/john-smith.json`

### Implementation for User Story 1

- [ ] T005 [US1] Create `tests/fixtures/sample-documents/generate_photo_id.py` — implement `generate_photo_id(profile: ApplicantProfile, spec: PhotoIdSpec, output_path: str) -> None` function using `fpdf2`: create landscape A5-ish card layout with `set_xy()` + `cell()` positioning; include header "STATE OF ILLINOIS — DRIVER LICENSE"; render labeled fields: `Name: John Smith`, `Date of Birth: 03/15/1988`, `Address: 742 Evergreen Terrace, Springfield, IL 62704`, `License Number: D-1234-5678-9012`, `Expiry Date: 03/15/2029`, `Issuing State: Illinois`, `Class: D`; format dates as MM/DD/YYYY for display; use Helvetica font family; ensure all text is native PDF text (not images)
- [ ] T006 [US1] Generate the John Smith photo ID PDF by calling `generate_photo_id()` with data loaded from `applicants/john-smith.json`, writing output to `tests/fixtures/sample-documents/john-smith/photo_id.pdf`

**Checkpoint**: Photo ID PDF exists and is independently verifiable — field labels match the normalization mapping in plan.md Design Decision D2

---

## Phase 4: User Story 2 — Proof of Address Document Generation (Priority: P2)

**Goal**: Generate a text-based PDF utility bill for John Smith with extractable name and address fields

**Independent Test**: Open `tests/fixtures/sample-documents/john-smith/proof_of_address.pdf` in a PDF viewer; verify text is selectable, `Name` and `Address` fields are present with values matching `applicants/john-smith.json`, bill date is within 90 days of generation

### Implementation for User Story 2

- [ ] T007 [US2] Create `tests/fixtures/sample-documents/generate_proof_of_address.py` — implement `generate_proof_of_address(profile: ApplicantProfile, spec: ProofOfAddressSpec, output_path: str) -> None` function using `fpdf2`: create portrait A4 layout; include header "Springfield Electric Utility" with provider info; render account section with `Account Number: ACCT-78901234`; render billing details with `Bill Date` (from spec, within 90 days), `Amount Due: $127.43`; render service address section with labeled fields: `Name: John Smith`, `Address: 742 Evergreen Terrace, Springfield, IL 62704`; use `fpdf2` `table()` context manager for the billing breakdown section; ensure all text is native PDF text
- [ ] T008 [US2] Generate the John Smith proof of address PDF by calling `generate_proof_of_address()` with data loaded from `applicants/john-smith.json`, writing output to `tests/fixtures/sample-documents/john-smith/proof_of_address.pdf`

**Checkpoint**: Both document PDFs exist and are independently verifiable — identity verification fields (Name, Address) match across both documents and the applicant JSON

---

## Phase 5: User Story 3 — CLI Generation Script (Priority: P3)

**Goal**: Provide a unified CLI entry point that generates all documents for any applicant profile

**Independent Test**: Run `python generate.py` from `tests/fixtures/sample-documents/` — both PDFs are regenerated in `john-smith/`; run `python generate.py --profile applicants/john-smith.json` — same result; verify output matches manual generation from US1/US2

### Implementation for User Story 3

- [ ] T009 [US3] Create `tests/fixtures/sample-documents/generate.py` — unified CLI script using `argparse`: accept `--profile` argument (default: `applicants/john-smith.json`); load profile via `models.load_profile()`; import and call `generate_photo_id()` from `generate_photo_id.py` and `generate_proof_of_address()` from `generate_proof_of_address.py`; create output directory named `{first_name}-{last_name}` (lowercased, hyphenated) if it doesn't exist; print summary of generated files to stdout; ensure reproducible output (same inputs → same outputs per NFR-4); add `if __name__ == "__main__"` guard
- [ ] T010 [US3] Run `python generate.py` from `tests/fixtures/sample-documents/` to regenerate both PDFs via the CLI entry point, confirming the script works end-to-end and output matches individual module generation

**Checkpoint**: All three user stories complete — documents can be generated via CLI for any applicant profile

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, cleanup, and documentation alignment

- [ ] T011 [P] Add module-level docstrings and type hints to all Python files: `models.py`, `generate_photo_id.py`, `generate_proof_of_address.py`, `generate.py` in `tests/fixtures/sample-documents/`
- [ ] T012 [P] Validate field consistency: confirm that `Name`, `Date of Birth`, `Address` values in both generated PDFs exactly match the `applicationForm` object in `applicants/john-smith.json` — cross-reference against the field mapping table in data-model.md
- [ ] T013 Run quickstart.md validation: execute the exact commands from `specs/016-sample-documents-account-opening/quickstart.md` (`cd tests/fixtures/sample-documents && pip install fpdf2 && python generate.py`) and verify both PDFs are produced in `john-smith/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup (Phase 1) — directory structure must exist
- **US1 Photo ID (Phase 3)**: Depends on Foundational (Phase 2) — needs models.py and john-smith.json
- **US2 Proof of Address (Phase 4)**: Depends on Foundational (Phase 2) — needs models.py and john-smith.json
- **US3 CLI Script (Phase 5)**: Depends on US1 (Phase 3) AND US2 (Phase 4) — imports both generators
- **Polish (Phase 6)**: Depends on US3 (Phase 5) — all code must exist

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) — no dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) — no dependencies on other stories; **can run in parallel with US1**
- **User Story 3 (P3)**: Depends on US1 AND US2 completion — imports both generator modules

### Within Each User Story

- Generator module created before PDF generation call
- Each story produces independently verifiable output

### Parallel Opportunities

- T001 and T002 can run in parallel (Phase 1)
- T003 and T004 can run in parallel (Phase 2 — different files)
- **US1 (Phase 3) and US2 (Phase 4) can run in parallel** — they share only the models.py dependency from Phase 2 and write to different files
- T011 and T012 can run in parallel (Phase 6 — different concerns)

---

## Parallel Example: US1 + US2 (After Phase 2)

```bash
# These two story phases can run simultaneously after Foundational completes:

# Developer A — User Story 1 (Photo ID):
Task: "Create generate_photo_id.py in tests/fixtures/sample-documents/generate_photo_id.py"
Task: "Generate john-smith/photo_id.pdf"

# Developer B — User Story 2 (Proof of Address):
Task: "Create generate_proof_of_address.py in tests/fixtures/sample-documents/generate_proof_of_address.py"
Task: "Generate john-smith/proof_of_address.pdf"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (directory structure, requirements.txt)
2. Complete Phase 2: Foundational (models.py, john-smith.json)
3. Complete Phase 3: User Story 1 (photo_id.pdf)
4. **STOP and VALIDATE**: Open photo_id.pdf, verify text is selectable and field labels match normalization mapping
5. A working photo ID fixture is already useful for partial E2E testing

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 (Photo ID) → Verify independently → One document type available (MVP!)
3. Add US2 (Proof of Address) → Verify independently → Both document types available
4. Add US3 (CLI Script) → Verify end-to-end → Full generation pipeline
5. Each story adds value without breaking previous stories

---

## Notes

- All files are under `tests/fixtures/sample-documents/` — no changes to `src/`
- Generated PDFs MUST be committed to the repo (Design Decision D4 in plan.md)
- Use `fpdf2` library only — no other PDF libraries (Research Decision R1)
- Field labels MUST match the normalization mapping in plan.md D2: `Name`, `Date of Birth`, `Address`, `License Number`, `Expiry Date`
- All applicant data comes from `john-smith.json` — never hardcoded in generator modules (Design Decision D3)
- No real PII — all data is clearly fictional (NFR-3)
