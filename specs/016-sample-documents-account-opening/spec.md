# Feature Spec: Generate Sample Documents for Account Opening

**Issue**: #16
**Branch**: `016-sample-documents-account-opening`
**Date**: 2025-07-25

## Problem Statement

The account opening workflow requires document uploads (`photo_id`, `proof_of_address`) that are processed by Azure AI Content Understanding for field extraction and then verified against application form data. Currently there are no sample documents or test fixtures, making it impossible to run E2E tests or demos of the full account opening pipeline.

## Requirements

### Functional Requirements

1. **FR-1**: Generate a `photo_id` document (driver's license style) for test applicant John Smith containing extractable fields: name, dateOfBirth, address, documentNumber, expiryDate
2. **FR-2**: Generate a `proof_of_address` document (utility bill style) for test applicant John Smith containing extractable fields: name, address
3. **FR-3**: Documents must contain data consistent with the application form data so identity verification passes (name, DOB, address must match)
4. **FR-4**: Provide a Python generation script that can produce documents for arbitrary applicant profiles
5. **FR-5**: Store generated documents in `tests/fixtures/sample-documents/` for use by E2E tests and demos
6. **FR-6**: Provide a companion JSON file defining John Smith's complete application form data matching the documents

### Non-Functional Requirements

1. **NFR-1**: Documents must be PDF format (processable by Azure AI Content Understanding `prebuilt-documentSearch` analyzer)
2. **NFR-2**: Generation script must run without Azure dependencies (offline, local-only)
3. **NFR-3**: No real PII — all data is clearly fictional
4. **NFR-4**: Script must be reproducible (same inputs → same outputs)

## Test Applicant Profile

- **Name**: John Smith
- **Date of Birth**: 1988-03-15
- **Address**: 742 Evergreen Terrace, Springfield, IL 62704
- **Occupation**: IT Engineer
- **Employer**: Contoso Technologies
- **Annual Salary**: $125,000
- **SSN (last 4)**: 5678
- **Email**: john.smith@example.com
- **Account Type**: checking

## Document Specifications

### Photo ID (Driver's License)
- Full name: John Smith
- Date of birth: 03/15/1988
- Address: 742 Evergreen Terrace, Springfield, IL 62704
- Document number: D-1234-5678-9012
- Expiry date: 03/15/2029
- Issuing state: Illinois

### Proof of Address (Utility Bill)
- Account holder: John Smith
- Service address: 742 Evergreen Terrace, Springfield, IL 62704
- Bill date: recent (within last 90 days)
- Provider: Springfield Electric Utility

## Out of Scope

- Actual image-based documents with photos/barcodes
- Integration with Azure AI Content Understanding (that's the existing service's job)
- Modifying the account-opening-service code
- E2E test implementation (separate issue)
