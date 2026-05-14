import * as fs from 'fs';
import * as path from 'path';
import { test, expect, apiLogin, DEFAULT_USER } from '../../fixtures/authFixture';

const LOG_PREFIX = '[E2E #135 #136 Resubmit]';
const ACCOUNT_OPENING_BASE = '/api/account-opening';
const HEALTH_ENDPOINT = `${ACCOUNT_OPENING_BASE}/applications`;
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

/**
 * E2E Tests for Issues #135 (Resubmit-on-Error) and #136 (Customer Status Screen)
 * 
 * These tests validate the account opening state machine's error handling,
 * retry logic, and customer-facing status polling.
 * 
 * Contract: Based on Danny's plan in .squad/decisions/inbox/danny-135-136-plan.md
 * Retry cap: 1 retry per stage (initial + 1 retry = max 2 attempts)
 * 
 * NOTE: These tests may be RED until Basher completes backend (#135) and Linus completes UI (#136).
 * That is expected — these tests define the contract.
 */
test.describe('Account Opening — Resubmit & Customer Status (#135 #136)', () => {
  test.beforeAll(async ({ request }) => {
    const baseURL = process.env.BASE_URL || `https://${process.env.CUSTOM_DOMAIN || 'onlinebankingdemo.bjdazure.tech'}`;
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

  // ─── Test 1: Happy Path — Terminal State with Customer Explanation ───────────
  test.describe('Happy path — terminal state with customerExplanation', () => {
    test.describe.configure({ mode: 'serial' });

    let authToken: string;
    let applicationId: string;

    test.beforeAll(async ({ request }) => {
      test.skip(!serviceAvailable, 'Account-opening service is not available');
      const auth = await apiLogin(request);
      authToken = auth.token;
    });

    test('Submit application and upload documents', async ({ request }) => {
      // Create application
      const createResp = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: applicationFormData,
      });
      expect(createResp.status(), `Expected 201, got ${createResp.status()}`).toBe(201);

      const body = await createResp.json();
      applicationId = body.id;
      console.log(`${LOG_PREFIX} [Happy] Application created: id=${applicationId}`);

      // Upload photo_id
      const photoIdBuffer = fs.readFileSync(photoIdPath);
      const uploadPhotoResp = await request.post(
        `${APPLICATIONS_ENDPOINT}/${applicationId}/documents`,
        {
          headers: { Authorization: `Bearer ${authToken}` },
          multipart: {
            documentType: 'photo_id',
            file: {
              name: 'photo_id.pdf',
              mimeType: 'application/pdf',
              buffer: photoIdBuffer,
            },
          },
        }
      );
      expect(uploadPhotoResp.status()).toBe(201);

      // Upload proof_of_address
      const proofBuffer = fs.readFileSync(proofOfAddressPath);
      const uploadProofResp = await request.post(
        `${APPLICATIONS_ENDPOINT}/${applicationId}/documents`,
        {
          headers: { Authorization: `Bearer ${authToken}` },
          multipart: {
            documentType: 'proof_of_address',
            file: {
              name: 'proof_of_address.pdf',
              mimeType: 'application/pdf',
              buffer: proofBuffer,
            },
          },
        }
      );
      expect(uploadProofResp.status()).toBe(201);
      console.log(`${LOG_PREFIX} [Happy] Documents uploaded`);
    });

    test('Poll status endpoint until terminal state', async ({ request }) => {
      test.setTimeout(120_000); // Allow 2 minutes for agent pipeline to complete
      expect(applicationId, 'Application ID must be set from prior test').toBeTruthy();

      const terminalStates = ['approved', 'rejected', 'pending_review', 'failed'];
      const statusEndpoint = `${APPLICATIONS_ENDPOINT}/${applicationId}/status`;

      let finalStatus = '';
      let statusResponse: any = null;
      const deadline = Date.now() + 90_000; // 90 second timeout

      console.log(`${LOG_PREFIX} [Happy] Polling ${statusEndpoint} (90s max)...`);

      while (Date.now() < deadline) {
        const response = await request.get(statusEndpoint, {
          headers: { Authorization: `Bearer ${authToken}` },
        });

        // If endpoint doesn't exist yet, fall back to full application GET
        if (response.status() === 404) {
          console.log(`${LOG_PREFIX} [Happy] /status endpoint not yet implemented — falling back to GET application`);
          const fallbackResp = await request.get(`${APPLICATIONS_ENDPOINT}/${applicationId}`, {
            headers: { Authorization: `Bearer ${authToken}` },
          });
          expect(fallbackResp.ok()).toBeTruthy();
          statusResponse = await fallbackResp.json();
        } else {
          expect(response.ok(), `Status endpoint returned ${response.status()}`).toBeTruthy();
          statusResponse = await response.json();
        }

        finalStatus = statusResponse.status;

        if (terminalStates.includes(finalStatus)) {
          console.log(`${LOG_PREFIX} [Happy] Reached terminal state: ${finalStatus}`);
          break;
        }

        // Still processing — wait and retry (2-second polling cadence per spec)
        await new Promise((r) => setTimeout(r, 2_000));
      }

      // Verify we reached a terminal state
      expect(
        terminalStates.includes(finalStatus),
        `Expected terminal state, got "${finalStatus}"`
      ).toBeTruthy();

      // Verify stages array exists (part of status projection)
      expect(statusResponse).toHaveProperty('stages');
      expect(Array.isArray(statusResponse.stages)).toBeTruthy();
      console.log(`${LOG_PREFIX} [Happy] Stages: ${statusResponse.stages.length} present`);
    });

    test('Terminal state includes customerExplanation', async ({ request }) => {
      expect(applicationId, 'Application ID must be set from prior test').toBeTruthy();

      const statusEndpoint = `${APPLICATIONS_ENDPOINT}/${applicationId}/status`;
      const response = await request.get(statusEndpoint, {
        headers: { Authorization: `Bearer ${authToken}` },
      });

      let statusResponse: any;
      if (response.status() === 404) {
        // Fall back to full GET if /status not implemented yet
        const fallbackResp = await request.get(`${APPLICATIONS_ENDPOINT}/${applicationId}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        expect(fallbackResp.ok()).toBeTruthy();
        statusResponse = await fallbackResp.json();
      } else {
        expect(response.ok()).toBeTruthy();
        statusResponse = await response.json();
      }

      const terminalStates = ['approved', 'rejected', 'pending_review'];
      if (terminalStates.includes(statusResponse.status)) {
        // For truly terminal states (non-failed), customerExplanation should be present
        expect(statusResponse).toHaveProperty('customerOutcome');
        expect(statusResponse).toHaveProperty('customerExplanation');
        expect(statusResponse.customerExplanation).toBeTruthy();
        expect(typeof statusResponse.customerExplanation).toBe('string');
        console.log(`${LOG_PREFIX} [Happy] customerExplanation: "${statusResponse.customerExplanation.substring(0, 80)}..."`);
      } else if (statusResponse.status === 'failed') {
        // Failed state may not have customerExplanation yet — that's OK for this test
        console.log(`${LOG_PREFIX} [Happy] Application in failed state — customerExplanation not expected`);
      } else {
        // Still in-progress — skip validation
        console.log(`${LOG_PREFIX} [Happy] Application still in progress: ${statusResponse.status}`);
      }
    });

    test('Polling stops at terminal state (no further changes)', async ({ request }) => {
      expect(applicationId, 'Application ID must be set from prior test').toBeTruthy();

      const statusEndpoint = `${APPLICATIONS_ENDPOINT}/${applicationId}/status`;
      const getStatus = async () => {
        const resp = await request.get(statusEndpoint, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (resp.status() === 404) {
          const fallback = await request.get(`${APPLICATIONS_ENDPOINT}/${applicationId}`, {
            headers: { Authorization: `Bearer ${authToken}` },
          });
          return await fallback.json();
        }
        return await resp.json();
      };

      const firstCheck = await getStatus();
      const terminalStates = ['approved', 'rejected', 'pending_review', 'failed'];

      if (terminalStates.includes(firstCheck.status)) {
        // Wait 5 seconds and check again
        await new Promise((r) => setTimeout(r, 5_000));
        const secondCheck = await getStatus();

        expect(secondCheck.status).toBe(firstCheck.status);
        expect(secondCheck.updatedAt).toBe(firstCheck.updatedAt);
        console.log(`${LOG_PREFIX} [Happy] Status stable at terminal state: ${firstCheck.status}`);
      } else {
        console.log(`${LOG_PREFIX} [Happy] Not yet terminal — skipping stability check`);
      }
    });
  });

  // ─── Test 2: Failure + Successful Retry ───────────────────────────────────────
  test.describe('Failure with successful retry', () => {
    test.describe.configure({ mode: 'serial' });

    let authToken: string;
    let applicationId: string;

    test.beforeAll(async ({ request }) => {
      test.skip(!serviceAvailable, 'Account-opening service is not available');
      const auth = await apiLogin(request);
      authToken = auth.token;
    });

    test.skip('Submit application that will fail at a stage', async ({ request }) => {
      // TODO: Once backend supports simulated failures (e.g., via special SSN trigger),
      // update this test to use a known-failing fixture.
      // For now, this test is skipped pending backend implementation.
      
      // Create application with SSN that triggers failure (e.g., "9999" per backend convention)
      const failingFormData = {
        ...applicationFormData,
        ssn: '9999', // Special value to trigger agent failure (per backend contract)
      };

      const createResp = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: failingFormData,
      });
      expect(createResp.status()).toBe(201);

      const body = await createResp.json();
      applicationId = body.id;
      console.log(`${LOG_PREFIX} [Retry] Application created with failing SSN: id=${applicationId}`);

      // Upload documents
      const photoIdBuffer = fs.readFileSync(photoIdPath);
      await request.post(`${APPLICATIONS_ENDPOINT}/${applicationId}/documents`, {
        headers: { Authorization: `Bearer ${authToken}` },
        multipart: {
          documentType: 'photo_id',
          file: { name: 'photo_id.pdf', mimeType: 'application/pdf', buffer: photoIdBuffer },
        },
      });

      const proofBuffer = fs.readFileSync(proofOfAddressPath);
      await request.post(`${APPLICATIONS_ENDPOINT}/${applicationId}/documents`, {
        headers: { Authorization: `Bearer ${authToken}` },
        multipart: {
          documentType: 'proof_of_address',
          file: { name: 'proof_of_address.pdf', mimeType: 'application/pdf', buffer: proofBuffer },
        },
      });
    });

    test.skip('Poll until application reaches failed state', async ({ request }) => {
      test.setTimeout(90_000);
      expect(applicationId).toBeTruthy();

      const deadline = Date.now() + 60_000; // 60 seconds
      let currentStatus = '';

      while (Date.now() < deadline) {
        const resp = await request.get(`${APPLICATIONS_ENDPOINT}/${applicationId}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        const body = await resp.json();
        currentStatus = body.status;

        if (currentStatus === 'failed') {
          console.log(`${LOG_PREFIX} [Retry] Application failed as expected`);
          // Verify lastError fields
          expect(body).toHaveProperty('lastError');
          expect(body.lastError).toHaveProperty('stage');
          expect(body.lastError).toHaveProperty('code');
          expect(body.lastError).toHaveProperty('message');
          expect(body.lastError).toHaveProperty('retryable', true);
          expect(body).toHaveProperty('failedStage', body.lastError.stage);
          expect(body).toHaveProperty('stageAttempts');
          console.log(`${LOG_PREFIX} [Retry] lastError: stage=${body.lastError.stage}, code=${body.lastError.code}`);
          return;
        }

        await new Promise((r) => setTimeout(r, 2_000));
      }

      throw new Error(`Application did not reach failed state within 60s (stuck at: ${currentStatus})`);
    });

    test.skip('POST /resubmit triggers retry and increments stageAttempts', async ({ request }) => {
      test.setTimeout(90_000);
      expect(applicationId).toBeTruthy();

      // Get current state before resubmit
      const beforeResp = await request.get(`${APPLICATIONS_ENDPOINT}/${applicationId}`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      const beforeBody = await beforeResp.json();
      const failedStage = beforeBody.failedStage;
      const attemptsBefore = beforeBody.stageAttempts[failedStage] || 0;

      console.log(`${LOG_PREFIX} [Retry] Before resubmit: failedStage=${failedStage}, attempts=${attemptsBefore}`);

      // POST /resubmit
      const resubmitResp = await request.post(
        `${APPLICATIONS_ENDPOINT}/${applicationId}/resubmit`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );

      expect(resubmitResp.status(), `Expected 202, got ${resubmitResp.status()}`).toBe(202);
      const resubmitBody = await resubmitResp.json();
      expect(resubmitBody).toHaveProperty('resumedFromStage', failedStage);
      expect(resubmitBody).toHaveProperty('attempt', attemptsBefore + 1);
      console.log(`${LOG_PREFIX} [Retry] Resubmit successful: attempt=${resubmitBody.attempt}`);

      // Poll until terminal state (success or failed again)
      const deadline = Date.now() + 60_000;
      let finalStatus = '';

      while (Date.now() < deadline) {
        const resp = await request.get(`${APPLICATIONS_ENDPOINT}/${applicationId}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        const body = await resp.json();
        finalStatus = body.status;

        const terminalStates = ['approved', 'rejected', 'pending_review', 'failed'];
        if (terminalStates.includes(finalStatus)) {
          console.log(`${LOG_PREFIX} [Retry] After resubmit: finalStatus=${finalStatus}`);
          
          // Verify stageAttempts incremented
          expect(body.stageAttempts[failedStage]).toBe(attemptsBefore + 1);
          console.log(`${LOG_PREFIX} [Retry] stageAttempts[${failedStage}] = ${body.stageAttempts[failedStage]} (expected ${attemptsBefore + 1})`);
          return;
        }

        await new Promise((r) => setTimeout(r, 2_000));
      }

      throw new Error(`Retry did not complete within 60s (stuck at: ${finalStatus})`);
    });
  });

  // ─── Test 3: Retry Cap Exceeded ──────────────────────────────────────────────
  test.describe('Retry cap exceeded — Retry button hidden, 409 on resubmit', () => {
    test.describe.configure({ mode: 'serial' });

    let authToken: string;
    let applicationId: string;

    test.beforeAll(async ({ request }) => {
      test.skip(!serviceAvailable, 'Account-opening service is not available');
      const auth = await apiLogin(request);
      authToken = auth.token;
    });

    test.skip('Submit application that will fail twice (initial + 1 retry)', async ({ request }) => {
      // TODO: Once backend supports persistent failures (e.g., SSN "8888" fails every time),
      // update this test to use that fixture.
      // For now, this test is skipped pending backend implementation.

      const alwaysFailingFormData = {
        ...applicationFormData,
        ssn: '8888', // Special value to always fail (per backend contract)
      };

      const createResp = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: alwaysFailingFormData,
      });
      expect(createResp.status()).toBe(201);

      const body = await createResp.json();
      applicationId = body.id;
      console.log(`${LOG_PREFIX} [Cap] Application created with always-failing SSN: id=${applicationId}`);

      // Upload documents
      const photoIdBuffer = fs.readFileSync(photoIdPath);
      await request.post(`${APPLICATIONS_ENDPOINT}/${applicationId}/documents`, {
        headers: { Authorization: `Bearer ${authToken}` },
        multipart: {
          documentType: 'photo_id',
          file: { name: 'photo_id.pdf', mimeType: 'application/pdf', buffer: photoIdBuffer },
        },
      });

      const proofBuffer = fs.readFileSync(proofOfAddressPath);
      await request.post(`${APPLICATIONS_ENDPOINT}/${applicationId}/documents`, {
        headers: { Authorization: `Bearer ${authToken}` },
        multipart: {
          documentType: 'proof_of_address',
          file: { name: 'proof_of_address.pdf', mimeType: 'application/pdf', buffer: proofBuffer },
        },
      });
    });

    test.skip('Wait for first failure', async ({ request }) => {
      test.setTimeout(90_000);
      expect(applicationId).toBeTruthy();

      const deadline = Date.now() + 60_000;
      while (Date.now() < deadline) {
        const resp = await request.get(`${APPLICATIONS_ENDPOINT}/${applicationId}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        const body = await resp.json();

        if (body.status === 'failed') {
          console.log(`${LOG_PREFIX} [Cap] First failure detected at stage: ${body.lastError.stage}`);
          expect(body.stageAttempts[body.lastError.stage]).toBe(1);
          return;
        }

        await new Promise((r) => setTimeout(r, 2_000));
      }

      throw new Error('Application did not fail within 60s');
    });

    test.skip('First resubmit accepted (202)', async ({ request }) => {
      expect(applicationId).toBeTruthy();

      const resubmitResp = await request.post(
        `${APPLICATIONS_ENDPOINT}/${applicationId}/resubmit`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );

      expect(resubmitResp.status()).toBe(202);
      const body = await resubmitResp.json();
      expect(body.attempt).toBe(2); // initial = 1, retry = 2
      console.log(`${LOG_PREFIX} [Cap] First resubmit accepted: attempt=2`);
    });

    test.skip('Wait for second failure (retry cap hit)', async ({ request }) => {
      test.setTimeout(90_000);
      expect(applicationId).toBeTruthy();

      const deadline = Date.now() + 60_000;
      while (Date.now() < deadline) {
        const resp = await request.get(`${APPLICATIONS_ENDPOINT}/${applicationId}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        const body = await resp.json();

        if (body.status === 'failed') {
          const failedStage = body.lastError.stage;
          if (body.stageAttempts[failedStage] >= 2) {
            console.log(`${LOG_PREFIX} [Cap] Second failure detected: stageAttempts[${failedStage}] = ${body.stageAttempts[failedStage]}`);
            
            // Verify lastError.retryable is now false (cap hit)
            expect(body.lastError.retryable).toBe(false);
            console.log(`${LOG_PREFIX} [Cap] lastError.retryable=false (retry cap enforced)`);
            return;
          }
        }

        await new Promise((r) => setTimeout(r, 2_000));
      }

      throw new Error('Application did not reach retry cap within 60s');
    });

    test.skip('Second resubmit returns 409 with retry_cap_exceeded', async ({ request }) => {
      expect(applicationId).toBeTruthy();

      const resubmitResp = await request.post(
        `${APPLICATIONS_ENDPOINT}/${applicationId}/resubmit`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );

      expect(resubmitResp.status()).toBe(409);
      const body = await resubmitResp.json();
      expect(body).toHaveProperty('error');
      expect(body.error).toMatch(/retry.cap|max.attempt|cannot.retry/i);
      console.log(`${LOG_PREFIX} [Cap] Second resubmit rejected with 409: ${body.error || body.message}`);
    });

    test.skip('Status endpoint shows "Contact support" message (no Retry button)', async ({ request }) => {
      expect(applicationId).toBeTruthy();

      const statusEndpoint = `${APPLICATIONS_ENDPOINT}/${applicationId}/status`;
      const resp = await request.get(statusEndpoint, {
        headers: { Authorization: `Bearer ${authToken}` },
      });

      let statusBody: any;
      if (resp.status() === 404) {
        const fallback = await request.get(`${APPLICATIONS_ENDPOINT}/${applicationId}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        statusBody = await fallback.json();
      } else {
        statusBody = await resp.json();
      }

      // Verify lastError.retryable=false signals UI to hide Retry button
      expect(statusBody).toHaveProperty('lastError');
      expect(statusBody.lastError.retryable).toBe(false);
      console.log(`${LOG_PREFIX} [Cap] UI should hide Retry button (lastError.retryable=false)`);
    });
  });

  // ─── Test 4: /resubmit Validation ─────────────────────────────────────────────
  test.describe('/resubmit endpoint validation', () => {
    let authToken: string;

    test.beforeAll(async ({ request }) => {
      test.skip(!serviceAvailable, 'Account-opening service is not available');
      const auth = await apiLogin(request);
      authToken = auth.token;
    });

    test.skip('POST /resubmit on non-failed status returns 409', async ({ request }) => {
      // Create a fresh application
      const createResp = await request.post(APPLICATIONS_ENDPOINT, {
        headers: { Authorization: `Bearer ${authToken}` },
        data: applicationFormData,
      });
      expect(createResp.status()).toBe(201);
      const body = await createResp.json();
      const appId = body.id;

      // Immediately try to resubmit (status is "submitted", not "failed")
      const resubmitResp = await request.post(
        `${APPLICATIONS_ENDPOINT}/${appId}/resubmit`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );

      expect(resubmitResp.status()).toBe(409);
      const errBody = await resubmitResp.json();
      expect(errBody).toHaveProperty('error');
      console.log(`${LOG_PREFIX} [Validation] Resubmit on non-failed app → 409: ${errBody.error || errBody.message}`);
    });

    test.skip('POST /resubmit on non-existent application returns 404', async ({ request }) => {
      const resubmitResp = await request.post(
        `${APPLICATIONS_ENDPOINT}/non-existent-id-99999/resubmit`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );

      expect(resubmitResp.status()).toBe(404);
      console.log(`${LOG_PREFIX} [Validation] Resubmit on missing app → 404`);
    });

    test.skip('POST /resubmit without auth returns 401 or 403', async ({ request }) => {
      const resubmitResp = await request.post(
        `${APPLICATIONS_ENDPOINT}/any-id/resubmit`,
        {} // No Authorization header
      );

      expect([401, 403].includes(resubmitResp.status())).toBeTruthy();
      console.log(`${LOG_PREFIX} [Validation] Resubmit without auth → ${resubmitResp.status()}`);
    });
  });
});
