import apiClient from './client';

// Mock the API client
jest.mock('./client', () => ({
  __esModule: true,
  default: {
    post: jest.fn(),
    get: jest.fn(),
    patch: jest.fn(),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() },
    },
  },
}));

// Import after mock so we get the mocked version
import {
  createApplication,
  getApplication,
  listApplications,
  uploadDocuments,
  reviewApplication,
  getAuditTrail,
} from './accountOpening';

const mockClient = apiClient as jest.Mocked<typeof apiClient>;

describe('Account Opening API', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.setItem('auth_token', 'test-jwt-token');
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe('createApplication', () => {
    const applicationData = {
      firstName: 'Jane',
      lastName: 'Doe',
      dateOfBirth: '1990-01-15',
      email: 'jane@example.com',
      phone: '555-0100',
      ssn: '1234',
      address: {
        street: '123 Main St',
        city: 'Springfield',
        state: 'IL',
        zip: '62701',
        country: 'US',
      },
      employment: {
        employer: 'Acme Corp',
        title: 'Engineer',
        annualIncome: 85000,
      },
      accountType: 'checking' as const,
    };

    test('calls POST /account-opening/applications with application data', async () => {
      const mockResponse = { data: { id: 'app-1', status: 'submitted', ...applicationData } };
      mockClient.post.mockResolvedValueOnce(mockResponse);

      const result = await createApplication(applicationData);

      expect(mockClient.post).toHaveBeenCalledWith(
        '/account-opening/applications',
        applicationData
      );
      expect(result).toEqual(mockResponse.data);
    });

    test('propagates API errors', async () => {
      const error = { response: { status: 422, data: { detail: 'Validation failed' } } };
      mockClient.post.mockRejectedValueOnce(error);

      await expect(createApplication(applicationData)).rejects.toEqual(error);
    });
  });

  describe('getApplication', () => {
    test('calls GET /account-opening/applications/:id', async () => {
      const mockApp = { data: { id: 'app-1', status: 'submitted' } };
      mockClient.get.mockResolvedValueOnce(mockApp);

      const result = await getApplication('app-1');

      expect(mockClient.get).toHaveBeenCalledWith('/account-opening/applications/app-1');
      expect(result).toEqual(mockApp.data);
    });

    test('propagates 404 errors', async () => {
      const error = { response: { status: 404, data: { detail: 'Not found' } } };
      mockClient.get.mockRejectedValueOnce(error);

      await expect(getApplication('nonexistent')).rejects.toEqual(error);
    });
  });

  describe('listApplications', () => {
    test('calls GET /account-opening/applications with no params', async () => {
      const mockList = { data: { items: [], total: 0 } };
      mockClient.get.mockResolvedValueOnce(mockList);

      const result = await listApplications();

      expect(mockClient.get).toHaveBeenCalledWith('/account-opening/applications', {
        params: undefined,
      });
      expect(result).toEqual(mockList.data);
    });

    test('passes filter params when provided', async () => {
      const mockList = { data: { items: [{ id: 'app-1' }], total: 1 } };
      mockClient.get.mockResolvedValueOnce(mockList);

      const params = { status: 'pending_review', sort: 'date', order: 'desc' };
      const result = await listApplications(params);

      expect(mockClient.get).toHaveBeenCalledWith('/account-opening/applications', {
        params,
      });
      expect(result).toEqual(mockList.data);
    });
  });

  describe('uploadDocuments', () => {
    test('calls POST /account-opening/applications/:id/documents with FormData', async () => {
      const mockResponse = { data: { documentIds: ['doc-1'] } };
      mockClient.post.mockResolvedValueOnce(mockResponse);

      const file = new File(['content'], 'id.jpg', { type: 'image/jpeg' });
      const result = await uploadDocuments('app-1', [file], 'photo_id');

      expect(mockClient.post).toHaveBeenCalledWith(
        '/account-opening/applications/app-1/documents',
        expect.any(FormData),
        expect.objectContaining({
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      );
      expect(result).toEqual(mockResponse.data);
    });

    test('propagates upload errors', async () => {
      const error = { response: { status: 413, data: { detail: 'File too large' } } };
      mockClient.post.mockRejectedValueOnce(error);

      const file = new File(['x'.repeat(11 * 1024 * 1024)], 'huge.pdf', { type: 'application/pdf' });
      await expect(uploadDocuments('app-1', [file], 'photo_id')).rejects.toEqual(error);
    });
  });

  describe('reviewApplication', () => {
    test('calls PATCH /account-opening/applications/:id/review for approval', async () => {
      const mockResponse = { data: { id: 'app-1', status: 'approved' } };
      mockClient.patch.mockResolvedValueOnce(mockResponse);

      const result = await reviewApplication('app-1', {
        decision: 'approved',
        notes: 'Looks good',
      });

      expect(mockClient.patch).toHaveBeenCalledWith(
        '/account-opening/applications/app-1/review',
        { decision: 'approved', notes: 'Looks good' }
      );
      expect(result).toEqual(mockResponse.data);
    });

    test('calls PATCH for rejection with notes', async () => {
      const mockResponse = { data: { id: 'app-1', status: 'rejected' } };
      mockClient.patch.mockResolvedValueOnce(mockResponse);

      const result = await reviewApplication('app-1', {
        decision: 'rejected',
        notes: 'Fraudulent documents',
      });

      expect(mockClient.patch).toHaveBeenCalledWith(
        '/account-opening/applications/app-1/review',
        { decision: 'rejected', notes: 'Fraudulent documents' }
      );
      expect(result).toEqual(mockResponse.data);
    });

    test('propagates 403 for non-admin users', async () => {
      const error = { response: { status: 403, data: { detail: 'Admin required' } } };
      mockClient.patch.mockRejectedValueOnce(error);

      await expect(
        reviewApplication('app-1', { decision: 'approved' })
      ).rejects.toEqual(error);
    });
  });

  describe('getAuditTrail', () => {
    test('calls GET /account-opening/applications/:id/audit', async () => {
      const mockAudit = {
        data: {
          entries: [
            { timestamp: '2026-01-01T00:00:00Z', action: 'submitted', agent: 'user' },
          ],
        },
      };
      mockClient.get.mockResolvedValueOnce(mockAudit);

      const result = await getAuditTrail('app-1');

      expect(mockClient.get).toHaveBeenCalledWith(
        '/account-opening/applications/app-1/audit'
      );
      expect(result).toEqual(mockAudit.data);
    });

    test('propagates errors for unauthorized access', async () => {
      const error = { response: { status: 403, data: { detail: 'Admin required' } } };
      mockClient.get.mockRejectedValueOnce(error);

      await expect(getAuditTrail('app-1')).rejects.toEqual(error);
    });
  });
});
