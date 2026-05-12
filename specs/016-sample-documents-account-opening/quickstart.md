# Quickstart: Sample Documents for Account Opening

**Feature**: #16 — Generate sample documents for account opening

## Prerequisites

- Python 3.11+
- `fpdf2` library (`pip install fpdf2`)

## Generate Sample Documents

```bash
# From repo root
cd tests/fixtures/sample-documents
pip install fpdf2
python generate.py
```

This produces:
```
john-smith/
├── photo_id.pdf          # Driver's license
└── proof_of_address.pdf  # Utility bill
```

## Generate for a Custom Applicant

```bash
python generate.py --profile applicants/john-smith.json
```

Or create a new profile JSON (see `applicants/john-smith.json` for the schema) and pass it.

## Use in E2E Tests

The companion application form data is at `applicants/john-smith.json`. Use it to:

1. POST to `/api/account-opening/applications` (the `applicationForm` key)
2. Upload `john-smith/photo_id.pdf` as `documentType=photo_id`
3. Upload `john-smith/proof_of_address.pdf` as `documentType=proof_of_address`

```typescript
// Playwright example
const formData = require('../fixtures/sample-documents/applicants/john-smith.json');
const app = await api.post('/api/account-opening/applications', { data: formData.applicationForm });
const appId = app.id;

await api.post(`/api/account-opening/applications/${appId}/documents`, {
  multipart: {
    documentType: 'photo_id',
    file: fs.createReadStream('../fixtures/sample-documents/john-smith/photo_id.pdf'),
  },
});
```

## Verify Documents Locally

Open the generated PDFs in any PDF viewer. Verify that:
- Text is selectable (not an image) — required for Azure AI Content Understanding
- Field labels match the normalization mapping: `Name`, `Date of Birth`, `Address`, `License Number`, `Expiry Date`
- Data matches the applicant profile JSON exactly
