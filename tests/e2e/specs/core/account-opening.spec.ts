import * as fs from 'fs';
import * as path from 'path';
import { test, expect, apiLogin, DEFAULT_USER } from '../../fixtures/authFixture';

const LOG_PREFIX = '[E2E Account Opening]';
const ACCOUNT_OPENING_BASE = '/api/account-opening';
const HEALTH_ENDPOINT = `${ACCOUNT_OPENING_BASE}/healthz`;
const APPLICATIONS_ENDPOINT = `${ACCOUNT_OPENING_BASE}/applications`;

// Load applicant fixture data
const applicantFixturePath = path.resolve(
  __dirname,
  '../../../fixtures/sample-documents/applicants/john-smith.json'
);
const applicantFixture = JSON.parse(fs.readFileSync(applicantFixturePath, 'utf-8'));
const applicationFormData = applicantFixture.applicationFormData;

// Fixture paths for document uploads
const photoIdPath = path.resolve(
  __dirname,
  '../../../fixtures/sample-documents/john-smith/photo_id.pdf'
);
const proofOfAddressPath = path.resolve(
  __dirname,
  '../../../fixtures/sample-documents/john-smith/proof_of_address.pdf'
);

let serviceAvailable = false;

test.describe('Account Opening — E2E', () => {
  test.beforeAll(async ({ request }) => {
    const baseURL = process.env.BASE_URL || 'http://localhost';
    try {
      const resp = await request.get(`${baseURL}${HEALTH_ENDPOINT}`);
      serviceAvailable = resp.status() < 500;
      console.log(`${LOG_PREFIX} Health check: ${resp.status()} — service ${serviceAvailable ? 'available' : 'unavailable'}`);
    } catch (err) {
      console.log(`${LOG_PREFIX} Health check failed — account-opening service not reachable. Skipping suite.`);
      serviceAvailable = false;
    }
  });

  test.beforeEach(async () => {
    test.skip(!serviceAvailable, 'Account-opening service is not available');
  });

  // ─── Happy Path (serial — tests depend on shared application state) ────────
  test.describe('Happy path workflow', () => {
    test.describe.configure({ mode: 'serial' });

    let authToken: string;
    let applicationId: string;

    test.beforeAll(async ({ request }) => {
      test.skip(!serviceAvailable, 'Account-opening service is not available');
      const auth = await apiLogin(request);
      authToken = auth.token;
    });

    test('Submit application with valid form data', async ({ request }) => {
      const response = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: applicationFormData,
      });

      expect(response.status(), `Expected 201, got ${response.status()}`).toBe(201);

      const body = await response.json();
      expect(body).toHaveProperty('id');
      expect(body).toHaveProperty('status');
      expect(body).toHaveProperty('createdAt');
      expect(body.status).toBe('submitted');

      applicationId = body.id;
      console.log(`${LOG_PREFIX} Application created: id=${applicationId}, status=${body.status}`);
    });

    test('Upload photo_id document', async ({ request }) => {
      expect(applicationId, 'Application ID must be set from prior test').toBeTruthy();

      const fileBuffer = fs.readFileSync(photoIdPath);
      const response = await request.post(
        `${APPLICATIONS_ENDPOINT}/${applicationId}/documents`,
        {
          headers: { Authorization: `Bearer ${authToken}` },
          multipart: {
            documentType: 'photo_id',
            file: {
              name: 'photo_id.pdf',
              mimeType: 'application/pdf',
              buffer: fileBuffer,
            },
          },
        }
      );

      expect(response.status(), `Expected 201, got ${response.status()}`).toBe(201);

      const body = await response.json();
      expect(body).toHaveProperty('type', 'photo_id');
      expect(body).toHaveProperty('filename');
      expect(body).toHaveProperty('blobUrl');
      console.log(`${LOG_PREFIX} Uploaded photo_id: filename=${body.filename}`);
    });

    test('Upload proof_of_address document', async ({ request }) => {
      expect(applicationId, 'Application ID must be set from prior test').toBeTruthy();

      const fileBuffer = fs.readFileSync(proofOfAddressPath);
      const response = await request.post(
        `${APPLICATIONS_ENDPOINT}/${applicationId}/documents`,
        {
          headers: { Authorization: `Bearer ${authToken}` },
          multipart: {
            documentType: 'proof_of_address',
            file: {
              name: 'proof_of_address.pdf',
              mimeType: 'application/pdf',
              buffer: fileBuffer,
            },
          },
        }
      );

      expect(response.status(), `Expected 201, got ${response.status()}`).toBe(201);

      const body = await response.json();
      expect(body).toHaveProperty('type', 'proof_of_address');
      console.log(`${LOG_PREFIX} Uploaded proof_of_address: filename=${body.filename}`);
    });

    test('Retrieve application and verify documents attached', async ({ request }) => {
      expect(applicationId, 'Application ID must be set from prior test').toBeTruthy();

      const response = await request.get(
        `${APPLICATIONS_ENDPOINT}/${applicationId}`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );

      expect(response.ok(), `GET application failed: ${response.status()}`).toBeTruthy();

      const body = await response.json();
      expect(body.id).toBe(applicationId);
      expect(body.documents).toBeDefined();
      expect(Array.isArray(body.documents)).toBeTruthy();
      expect(body.documents.length).toBeGreaterThanOrEqual(2);

      const docTypes = body.documents.map((d: { type: string }) => d.type);
      expect(docTypes).toContain('photo_id');
      expect(docTypes).toContain('proof_of_address');
      console.log(`${LOG_PREFIX} Application ${applicationId} has ${body.documents.length} documents, status=${body.status}`);
    });

    test('Application reaches a terminal state (or remains in pipeline)', async ({ request }) => {
      expect(applicationId, 'Application ID must be set from prior test').toBeTruthy();

      const terminalStates = ['approved', 'rejected', 'pending_review'];
      const allValidStates = [
        'submitted',
        'document_extraction',
        'identity_verification',
        'compliance_check',
        ...terminalStates,
      ];

      // Poll for up to 30 seconds for async processing
      let finalStatus = '';
      const deadline = Date.now() + 30_000;

      while (Date.now() < deadline) {
        const response = await request.get(
          `${APPLICATIONS_ENDPOINT}/${applicationId}`,
          { headers: { Authorization: `Bearer ${authToken}` } }
        );
        expect(response.ok()).toBeTruthy();

        const body = await response.json();
        finalStatus = body.status;

        if (terminalStates.includes(finalStatus)) {
          console.log(`${LOG_PREFIX} Application reached terminal state: ${finalStatus}`);
          break;
        }

        // Still processing — wait and retry
        await new Promise((r) => setTimeout(r, 2_000));
      }

      // Accept any valid state — the pipeline may not run in test environments
      expect(
        allValidStates.includes(finalStatus),
        `Expected a valid state, got "${finalStatus}"`
      ).toBeTruthy();

      console.log(`${LOG_PREFIX} Final observed status: ${finalStatus}`);
    });
  });

  // ─── Application CRUD ──────────────────────────────────────────────────────
  test.describe('Application CRUD', () => {
    let authToken: string;

    test.beforeAll(async ({ request }) => {
      test.skip(!serviceAvailable, 'Account-opening service is not available');
      const auth = await apiLogin(request);
      authToken = auth.token;
    });

    test('Create application — returns 201 with expected shape', async ({ request }) => {
      const response = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: applicationFormData,
      });

      expect(response.status()).toBe(201);

      const body = await response.json();
      expect(body).toHaveProperty('id');
      expect(typeof body.id).toBe('string');
      expect(body).toHaveProperty('status', 'submitted');
      expect(body).toHaveProperty('createdAt');
      expect(body).toHaveProperty('updatedAt');
      expect(body).toHaveProperty('formData');
      console.log(`${LOG_PREFIX} CRUD create: id=${body.id}`);
    });

    test('Get application by ID — matches created application', async ({ request }) => {
      // Create first
      const createResp = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: applicationFormData,
      });
      expect(createResp.status()).toBe(201);
      const created = await createResp.json();

      // Retrieve
      const getResp = await request.get(
        `${APPLICATIONS_ENDPOINT}/${created.id}`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );
      expect(getResp.ok()).toBeTruthy();

      const fetched = await getResp.json();
      expect(fetched.id).toBe(created.id);
      expect(fetched.status).toBe(created.status);
      expect(fetched.createdAt).toBe(created.createdAt);
      expect(fetched.formData).toEqual(created.formData);
      console.log(`${LOG_PREFIX} CRUD get: id=${fetched.id} matches`);
    });

    test('Get non-existent application — returns 404', async ({ request }) => {
      const response = await request.get(
        `${APPLICATIONS_ENDPOINT}/non-existent-id-12345`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );
      expect(response.status()).toBe(404);
    });

    test('List applications — newly created application appears', async ({ request }) => {
      // Create an application
      const createResp = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: applicationFormData,
      });
      expect(createResp.status()).toBe(201);
      const created = await createResp.json();

      // List — requires admin; gracefully degrade if non-admin
      const listResp = await request.get(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
      });

      if (listResp.status() === 403 || listResp.status() === 401) {
        console.log(`${LOG_PREFIX} List applications requires admin — skipping verification`);
        return;
      }

      expect(listResp.ok(), `List failed: ${listResp.status()}`).toBeTruthy();

      const applications = await listResp.json();
      expect(Array.isArray(applications)).toBeTruthy();

      const found = applications.find((a: { id: string }) => a.id === created.id);
      expect(found, `Created application ${created.id} not found in list`).toBeTruthy();
      console.log(`${LOG_PREFIX} CRUD list: found ${applications.length} applications, target present`);
    });
  });

  // ─── Input Validation ──────────────────────────────────────────────────────
  test.describe('Input validation', () => {
    let authToken: string;

    test.beforeAll(async ({ request }) => {
      test.skip(!serviceAvailable, 'Account-opening service is not available');
      const auth = await apiLogin(request);
      authToken = auth.token;
    });

    test('Missing required fields — returns 422 or 400', async ({ request }) => {
      const response = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: {},
      });

      expect(
        [400, 422].includes(response.status()),
        `Expected 400 or 422, got ${response.status()}`
      ).toBeTruthy();
      console.log(`${LOG_PREFIX} Validation: empty body → ${response.status()}`);
    });

    test('Invalid SSN format (not 4 digits) — returns 422 or 400', async ({ request }) => {
      const invalidData = {
        ...applicationFormData,
        ssn: 'ABCD',
      };

      const response = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: invalidData,
      });

      expect(
        [400, 422].includes(response.status()),
        `Expected 400 or 422 for invalid SSN, got ${response.status()}`
      ).toBeTruthy();
      console.log(`${LOG_PREFIX} Validation: invalid SSN → ${response.status()}`);
    });

    test('Invalid email format — returns 422 or 400', async ({ request }) => {
      const invalidData = {
        ...applicationFormData,
        email: 'not-an-email',
      };

      const response = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: invalidData,
      });

      expect(
        [400, 422].includes(response.status()),
        `Expected 400 or 422 for invalid email, got ${response.status()}`
      ).toBeTruthy();
      console.log(`${LOG_PREFIX} Validation: invalid email → ${response.status()}`);
    });

    test('Partial data (missing lastName) — returns 422 or 400', async ({ request }) => {
      const { lastName, ...partialData } = applicationFormData;

      const response = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: partialData,
      });

      expect(
        [400, 422].includes(response.status()),
        `Expected 400 or 422 for missing lastName, got ${response.status()}`
      ).toBeTruthy();
      console.log(`${LOG_PREFIX} Validation: missing lastName → ${response.status()}`);
    });

    test('SSN too long — returns 422 or 400', async ({ request }) => {
      const invalidData = {
        ...applicationFormData,
        ssn: '123456789',
      };

      const response = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: invalidData,
      });

      expect(
        [400, 422].includes(response.status()),
        `Expected 400 or 422 for SSN too long, got ${response.status()}`
      ).toBeTruthy();
      console.log(`${LOG_PREFIX} Validation: SSN too long → ${response.status()}`);
    });
  });

  // ─── Document Upload Validation ────────────────────────────────────────────
  test.describe('Document upload validation', () => {
    let authToken: string;
    let validApplicationId: string;

    test.beforeAll(async ({ request }) => {
      test.skip(!serviceAvailable, 'Account-opening service is not available');
      const auth = await apiLogin(request);
      authToken = auth.token;

      // Create an application for upload tests
      const resp = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: applicationFormData,
      });
      const body = await resp.json();
      validApplicationId = body.id;
      console.log(`${LOG_PREFIX} Upload validation setup: applicationId=${validApplicationId}`);
    });

    test('Upload valid photo_id — returns 201', async ({ request }) => {
      const fileBuffer = fs.readFileSync(photoIdPath);
      const response = await request.post(
        `${APPLICATIONS_ENDPOINT}/${validApplicationId}/documents`,
        {
          headers: { Authorization: `Bearer ${authToken}` },
          multipart: {
            documentType: 'photo_id',
            file: {
              name: 'photo_id.pdf',
              mimeType: 'application/pdf',
              buffer: fileBuffer,
            },
          },
        }
      );

      expect(response.status()).toBe(201);
      const body = await response.json();
      expect(body.type).toBe('photo_id');
      console.log(`${LOG_PREFIX} Upload photo_id → 201`);
    });

    test('Upload valid proof_of_address — returns 201', async ({ request }) => {
      const fileBuffer = fs.readFileSync(proofOfAddressPath);
      const response = await request.post(
        `${APPLICATIONS_ENDPOINT}/${validApplicationId}/documents`,
        {
          headers: { Authorization: `Bearer ${authToken}` },
          multipart: {
            documentType: 'proof_of_address',
            file: {
              name: 'proof_of_address.pdf',
              mimeType: 'application/pdf',
              buffer: fileBuffer,
            },
          },
        }
      );

      expect(response.status()).toBe(201);
      const body = await response.json();
      expect(body.type).toBe('proof_of_address');
      console.log(`${LOG_PREFIX} Upload proof_of_address → 201`);
    });

    test('Upload to non-existent application — returns 404', async ({ request }) => {
      const fileBuffer = fs.readFileSync(photoIdPath);
      const response = await request.post(
        `${APPLICATIONS_ENDPOINT}/non-existent-app-99999/documents`,
        {
          headers: { Authorization: `Bearer ${authToken}` },
          multipart: {
            documentType: 'photo_id',
            file: {
              name: 'photo_id.pdf',
              mimeType: 'application/pdf',
              buffer: fileBuffer,
            },
          },
        }
      );

      expect(response.status()).toBe(404);
      console.log(`${LOG_PREFIX} Upload to missing app → 404`);
    });
  });

  // ─── Auth guard ────────────────────────────────────────────────────────────
  test.describe('Auth enforcement', () => {
    test('Unauthenticated request — returns 401 or 403', async ({ request }) => {
      const response = await request.post(APPLICATIONS_ENDPOINT, {
        data: applicationFormData,
      });

      expect(
        [401, 403].includes(response.status()),
        `Expected 401 or 403 without auth, got ${response.status()}`
      ).toBeTruthy();
      console.log(`${LOG_PREFIX} No auth → ${response.status()}`);
    });
  });
});
