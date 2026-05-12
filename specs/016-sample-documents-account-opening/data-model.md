# Data Model: Sample Documents for Account Opening

**Feature**: #16 — Generate sample documents for account opening
**Date**: 2025-07-25

## Entities

### 1. ApplicantProfile

Defines a test applicant's complete identity for document generation and application submission.

```python
@dataclass
class ApplicantProfile:
    first_name: str           # "John"
    last_name: str            # "Smith"
    date_of_birth: str        # "1988-03-15" (ISO format)
    street: str               # "742 Evergreen Terrace"
    city: str                 # "Springfield"
    state: str                # "IL"
    zip_code: str             # "62704"
    country: str              # "US"
    email: str                # "john.smith@example.com"
    phone: str | None         # "+12175551234"
    ssn_last4: str            # "5678"
    employer: str             # "Contoso Technologies"
    job_title: str            # "IT Engineer"
    annual_income: float      # 125000.0
    account_type: str         # "checking"
```

**Validation rules**:
- `date_of_birth`: Must be valid ISO date, applicant must be 18+
- `ssn_last4`: Exactly 4 digits
- `account_type`: One of `checking`, `savings`, `both`
- `state`: 2-letter US state code
- `zip_code`: 5-digit US ZIP

### 2. DocumentSpec

Defines document-specific fields beyond the applicant profile.

```python
@dataclass
class PhotoIdSpec:
    document_number: str      # "D-1234-5678-9012"
    expiry_date: str          # "2029-03-15" (ISO format)
    issuing_state: str        # "Illinois"
    document_class: str       # "D" (regular driver)

@dataclass
class ProofOfAddressSpec:
    provider_name: str        # "Springfield Electric Utility"
    account_number: str       # "ACCT-78901234"
    bill_date: str            # Recent date (within 90 days)
    amount_due: float         # 127.43
```

### 3. ApplicationFormData

Maps to `ApplicationCreate` model in the account-opening-service. Output as JSON for E2E test consumption.

```json
{
  "firstName": "John",
  "lastName": "Smith",
  "email": "john.smith@example.com",
  "phone": "+12175551234",
  "dateOfBirth": "1988-03-15",
  "address": {
    "street": "742 Evergreen Terrace",
    "city": "Springfield",
    "state": "IL",
    "zip": "62704",
    "country": "US"
  },
  "employment": {
    "employer": "Contoso Technologies",
    "title": "IT Engineer",
    "annualIncome": 125000.0
  },
  "annualIncome": 125000.0,
  "accountType": "checking",
  "ssn": "5678"
}
```

## Relationships

```
ApplicantProfile 1 ──── 1 ApplicationFormData
       │
       ├──── 1 PhotoIdSpec ──── 1 photo_id.pdf
       └──── 1 ProofOfAddressSpec ──── 1 proof_of_address.pdf
```

- `ApplicantProfile` is the single source of truth for identity fields
- `ApplicationFormData` is derived from `ApplicantProfile` (same name, DOB, address)
- Both document PDFs are generated from `ApplicantProfile` + their respective `DocumentSpec`
- Identity verification compares `ApplicationFormData` fields against extracted document fields → fields MUST be consistent

## Field Mapping: Document → Extraction → Verification

| Document PDF Field Label | Extraction Normalized Key | Verification Comparison |
|--------------------------|---------------------------|------------------------|
| `Name` or `Full Name`   | `name`                    | vs `firstName` + `lastName` |
| `Date of Birth`         | `dateOfBirth`             | vs `dateOfBirth` |
| `Address`               | `address`                 | vs `address` (street/city/state) |
| `License Number`        | `documentNumber`          | stored, not compared |
| `Expiry Date`           | `expiryDate`              | stored, not compared |

## State Transitions

N/A — This feature generates static artifacts, no runtime state machine involved.

## Output File Structure

```
tests/fixtures/sample-documents/
├── generate.py                      # Generation script
├── applicants/
│   └── john-smith.json              # Applicant profile + form data
└── john-smith/
    ├── photo_id.pdf                 # Driver's license PDF
    └── proof_of_address.pdf         # Utility bill PDF
```
