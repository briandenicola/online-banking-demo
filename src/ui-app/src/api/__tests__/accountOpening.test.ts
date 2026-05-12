import apiClient from '../client';
import accountOpeningApi, {
  ApplicationFormData,
  ApplicationResponse,
  DocumentUploadResponse,
  ReviewRequest,
} from '../accountOpening';

jest.mock('../client');
const mockedApiClient = apiClient as jest.Mocked<typeof apiClient>;

describe('Account Opening API', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  const mockFormData: ApplicationFormData = {
    firstName: 'John',
    lastName: 'Doe',
    dateOfBirth: '1990-01-01',
    email: 'john@example.com',
    phone: '+12345678901',
    address: '123 Main St',
    city: 'New York',
    state: 'NY',
    zipCode: '10001',
    employment: 'Software Engineer',
    annualIncome: 75000,
    accountType: 'checking',
  };

  const mockApplicationResponse: ApplicationResponse = {
    id: 'app-123',
    status: 'submitted',
    createdAt: '2026-05-11T10:00:00Z',
    updatedAt: '2026-05-11T10:00:00Z',
    formData: mockFormData,
  };

  describe('submitApplication', () => {
    it('submits application successfully', async () => {
      mockedApiClient.post.mockResolvedValue({ data: mockApplicationResponse });

      const result = await accountOpeningApi.submitApplication(mockFormData);

      expect(mockedApiClient.post).toHaveBeenCalledWith('/account-opening/applications', {
        formData: mockFormData,
      });
      expect(result).toEqual(mockApplicationResponse);
    });

    it('throws error when submission fails', async () => {
      const error = new Error('Network error');
      mockedApiClient.post.mockRejectedValue(error);

      await expect(accountOpeningApi.submitApplication(mockFormData)).rejects.toThrow('Network error');
    });

    it('sends correct request format', async () => {
      mockedApiClient.post.mockResolvedValue({ data: mockApplicationResponse });

      await accountOpeningApi.submitApplication(mockFormData);

      expect(mockedApiClient.post).toHaveBeenCalledWith(
        '/account-opening/applications',
        expect.objectContaining({
          formData: expect.objectContaining({
            firstName: 'John',
            lastName: 'Doe',
            email: 'john@example.com',
          }),
        })
      );
    });
  });

  describe('uploadDocument', () => {
    it('uploads photo ID successfully', async () => {
      const file = new File(['photo'], 'id.jpg', { type: 'image/jpeg' });
      const mockResponse: DocumentUploadResponse = {
        id: 'doc-123',
        type: 'photo_id',
        blobUrl: 'https://example.com/doc-123',
        uploadedAt: '2026-05-11T10:05:00Z',
      };

      mockedApiClient.post.mockResolvedValue({ data: mockResponse });

      const result = await accountOpeningApi.uploadDocument('app-123', file, 'photo_id');

      expect(mockedApiClient.post).toHaveBeenCalledWith(
        '/account-opening/applications/app-123/documents',
        expect.any(FormData),
        expect.objectContaining({
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      );
      expect(result).toEqual(mockResponse);
    });

    it('uploads proof of address successfully', async () => {
      const file = new File(['proof'], 'bill.pdf', { type: 'application/pdf' });
      const mockResponse: DocumentUploadResponse = {
        id: 'doc-456',
        type: 'proof_of_address',
        blobUrl: 'https://example.com/doc-456',
        uploadedAt: '2026-05-11T10:10:00Z',
      };

      mockedApiClient.post.mockResolvedValue({ data: mockResponse });

      const result = await accountOpeningApi.uploadDocument('app-123', file, 'proof_of_address');

      expect(result).toEqual(mockResponse);
      expect(result.type).toBe('proof_of_address');
    });

    it('sends file as FormData', async () => {
      const file = new File(['content'], 'test.jpg', { type: 'image/jpeg' });
      mockedApiClient.post.mockResolvedValue({ data: {} });

      await accountOpeningApi.uploadDocument('app-123', file, 'photo_id');

      const callArgs = mockedApiClient.post.mock.calls[0];
      expect(callArgs[1]).toBeInstanceOf(FormData);
    });

    it('throws error when upload fails', async () => {
      const file = new File(['photo'], 'id.jpg', { type: 'image/jpeg' });
      const error = new Error('Upload failed');
      mockedApiClient.post.mockRejectedValue(error);

      await expect(
        accountOpeningApi.uploadDocument('app-123', file, 'photo_id')
      ).rejects.toThrow('Upload failed');
    });
  });

  describe('getApplicationStatus', () => {
    it('fetches application status successfully', async () => {
      const mockStatus: ApplicationResponse = {
        ...mockApplicationResponse,
        status: 'identity_verification',
        updatedAt: '2026-05-11T10:15:00Z',
        agentResults: {
          documentExtraction: { status: 'completed' },
        },
      };

      mockedApiClient.get.mockResolvedValue({ data: mockStatus });

      const result = await accountOpeningApi.getApplicationStatus('app-123');

      expect(mockedApiClient.get).toHaveBeenCalledWith('/account-opening/applications/app-123');
      expect(result).toEqual(mockStatus);
    });

    it('throws error when fetch fails', async () => {
      const error = new Error('Not found');
      mockedApiClient.get.mockRejectedValue(error);

      await expect(accountOpeningApi.getApplicationStatus('app-999')).rejects.toThrow('Not found');
    });

    it('returns application with agent results', async () => {
      const mockStatusWithResults: ApplicationResponse = {
        ...mockApplicationResponse,
        agentResults: {
          documentExtraction: { status: 'completed', timestamp: '2026-05-11T10:05:00Z' },
          identityVerification: { verified: true, confidence: 0.95 },
          complianceCheck: { kycStatus: 'approved', riskTier: 'low' },
        },
      };

      mockedApiClient.get.mockResolvedValue({ data: mockStatusWithResults });

      const result = await accountOpeningApi.getApplicationStatus('app-123');

      expect(result.agentResults).toBeDefined();
      expect(result.agentResults?.identityVerification?.verified).toBe(true);
    });
  });

  describe('getApplicationAudit', () => {
    it('fetches audit trail successfully', async () => {
      const mockAudit = {
        auditTrail: [
          { timestamp: '2026-05-11T10:00:00Z', agent: 'document-extraction', action: 'started' },
          { timestamp: '2026-05-11T10:05:00Z', agent: 'document-extraction', action: 'completed' },
        ],
      };

      mockedApiClient.get.mockResolvedValue({ data: mockAudit });

      const result = await accountOpeningApi.getApplicationAudit('app-123');

      expect(mockedApiClient.get).toHaveBeenCalledWith('/account-opening/applications/app-123/audit');
      expect(result).toEqual(mockAudit);
    });

    it('throws error when fetch fails', async () => {
      const error = new Error('Unauthorized');
      mockedApiClient.get.mockRejectedValue(error);

      await expect(accountOpeningApi.getApplicationAudit('app-123')).rejects.toThrow('Unauthorized');
    });
  });

  describe('listApplications', () => {
    it('fetches all applications without filter', async () => {
      const mockApplications: ApplicationResponse[] = [
        mockApplicationResponse,
        { ...mockApplicationResponse, id: 'app-456', status: 'approved' },
      ];

      mockedApiClient.get.mockResolvedValue({ data: mockApplications });

      const result = await accountOpeningApi.listApplications();

      expect(mockedApiClient.get).toHaveBeenCalledWith('/account-opening/applications', {
        params: {},
      });
      expect(result).toEqual(mockApplications);
      expect(result).toHaveLength(2);
    });

    it('fetches applications with status filter', async () => {
      const mockFilteredApplications: ApplicationResponse[] = [
        { ...mockApplicationResponse, status: 'pending_review' },
      ];

      mockedApiClient.get.mockResolvedValue({ data: mockFilteredApplications });

      const result = await accountOpeningApi.listApplications('pending_review');

      expect(mockedApiClient.get).toHaveBeenCalledWith('/account-opening/applications', {
        params: { status: 'pending_review' },
      });
      expect(result).toEqual(mockFilteredApplications);
    });

    it('fetches applications with approved filter', async () => {
      const mockApprovedApplications: ApplicationResponse[] = [
        { ...mockApplicationResponse, status: 'approved', userId: 'user-123', accountId: 'acc-456' },
      ];

      mockedApiClient.get.mockResolvedValue({ data: mockApprovedApplications });

      const result = await accountOpeningApi.listApplications('approved');

      expect(mockedApiClient.get).toHaveBeenCalledWith('/account-opening/applications', {
        params: { status: 'approved' },
      });
      expect(result[0].status).toBe('approved');
    });

    it('throws error when fetch fails', async () => {
      const error = new Error('Server error');
      mockedApiClient.get.mockRejectedValue(error);

      await expect(accountOpeningApi.listApplications()).rejects.toThrow('Server error');
    });
  });

  describe('reviewApplication', () => {
    it('approves application successfully', async () => {
      const review: ReviewRequest = {
        action: 'approve',
        notes: 'Application looks good',
      };

      const mockApprovedResponse: ApplicationResponse = {
        ...mockApplicationResponse,
        status: 'approved',
        userId: 'user-123',
        accountId: 'acc-456',
      };

      mockedApiClient.patch.mockResolvedValue({ data: mockApprovedResponse });

      const result = await accountOpeningApi.reviewApplication('app-123', review);

      expect(mockedApiClient.patch).toHaveBeenCalledWith(
        '/account-opening/applications/app-123/review',
        review
      );
      expect(result).toEqual(mockApprovedResponse);
      expect(result.status).toBe('approved');
    });

    it('rejects application successfully', async () => {
      const review: ReviewRequest = {
        action: 'reject',
        notes: 'Insufficient documentation',
      };

      const mockRejectedResponse: ApplicationResponse = {
        ...mockApplicationResponse,
        status: 'rejected',
      };

      mockedApiClient.patch.mockResolvedValue({ data: mockRejectedResponse });

      const result = await accountOpeningApi.reviewApplication('app-123', review);

      expect(mockedApiClient.patch).toHaveBeenCalledWith(
        '/account-opening/applications/app-123/review',
        review
      );
      expect(result.status).toBe('rejected');
    });

    it('sends review with notes', async () => {
      const review: ReviewRequest = {
        action: 'approve',
        notes: 'Manually verified documents',
      };

      mockedApiClient.patch.mockResolvedValue({ data: mockApplicationResponse });

      await accountOpeningApi.reviewApplication('app-123', review);

      const callArgs = mockedApiClient.patch.mock.calls[0];
      expect(callArgs[1]).toEqual(review);
      expect(callArgs[1].notes).toBe('Manually verified documents');
    });

    it('throws error when review fails', async () => {
      const review: ReviewRequest = {
        action: 'approve',
        notes: 'Approved',
      };

      const error = new Error('Forbidden');
      mockedApiClient.patch.mockRejectedValue(error);

      await expect(accountOpeningApi.reviewApplication('app-123', review)).rejects.toThrow('Forbidden');
    });
  });

  describe('API Client Integration', () => {
    it('uses correct base URL from client', async () => {
      mockedApiClient.post.mockResolvedValue({ data: mockApplicationResponse });

      await accountOpeningApi.submitApplication(mockFormData);

      expect(mockedApiClient.post).toHaveBeenCalledWith(
        expect.stringContaining('/account-opening/applications'),
        expect.any(Object)
      );
    });

    it('handles network errors gracefully', async () => {
      const networkError = new Error('Network Error');
      mockedApiClient.get.mockRejectedValue(networkError);

      await expect(accountOpeningApi.getApplicationStatus('app-123')).rejects.toThrow('Network Error');
    });

    it('handles HTTP error responses', async () => {
      const httpError = {
        response: {
          status: 400,
          data: { message: 'Invalid request' },
        },
      };
      mockedApiClient.post.mockRejectedValue(httpError);

      await expect(accountOpeningApi.submitApplication(mockFormData)).rejects.toEqual(httpError);
    });
  });

  describe('TypeScript Type Safety', () => {
    it('enforces correct account type values', async () => {
      const validFormData: ApplicationFormData = {
        ...mockFormData,
        accountType: 'checking', // Valid value
      };

      mockedApiClient.post.mockResolvedValue({ data: mockApplicationResponse });

      await accountOpeningApi.submitApplication(validFormData);

      expect(mockedApiClient.post).toHaveBeenCalled();
    });

    it('enforces correct document type values', async () => {
      const file = new File(['test'], 'test.jpg', { type: 'image/jpeg' });
      mockedApiClient.post.mockResolvedValue({ data: {} });

      // These should compile without errors
      await accountOpeningApi.uploadDocument('app-123', file, 'photo_id');
      await accountOpeningApi.uploadDocument('app-123', file, 'proof_of_address');

      expect(mockedApiClient.post).toHaveBeenCalledTimes(2);
    });

    it('enforces correct review action values', async () => {
      mockedApiClient.patch.mockResolvedValue({ data: mockApplicationResponse });

      // These should compile without errors
      await accountOpeningApi.reviewApplication('app-123', {
        action: 'approve',
        notes: 'OK',
      });

      await accountOpeningApi.reviewApplication('app-123', {
        action: 'reject',
        notes: 'Not OK',
      });

      expect(mockedApiClient.patch).toHaveBeenCalledTimes(2);
    });
  });

  describe('Edge Cases', () => {
    it('handles empty application list', async () => {
      mockedApiClient.get.mockResolvedValue({ data: [] });

      const result = await accountOpeningApi.listApplications();

      expect(result).toEqual([]);
      expect(result).toHaveLength(0);
    });

    it('handles application without optional fields', async () => {
      const minimalResponse: ApplicationResponse = {
        id: 'app-123',
        status: 'submitted',
        createdAt: '2026-05-11T10:00:00Z',
        updatedAt: '2026-05-11T10:00:00Z',
        formData: mockFormData,
      };

      mockedApiClient.get.mockResolvedValue({ data: minimalResponse });

      const result = await accountOpeningApi.getApplicationStatus('app-123');

      expect(result.userId).toBeUndefined();
      expect(result.accountId).toBeUndefined();
      expect(result.agentResults).toBeUndefined();
    });

    it('handles large file upload', async () => {
      const largeContent = 'x'.repeat(10 * 1024 * 1024); // 10MB
      const largeFile = new File([largeContent], 'large.jpg', { type: 'image/jpeg' });

      mockedApiClient.post.mockResolvedValue({
        data: {
          id: 'doc-123',
          type: 'photo_id',
          blobUrl: 'https://example.com/doc-123',
          uploadedAt: '2026-05-11T10:05:00Z',
        },
      });

      const result = await accountOpeningApi.uploadDocument('app-123', largeFile, 'photo_id');

      expect(result).toBeDefined();
      expect(mockedApiClient.post).toHaveBeenCalled();
    });

    it('handles special characters in form data', async () => {
      const specialCharsData: ApplicationFormData = {
        ...mockFormData,
        firstName: "O'Brien",
        lastName: 'Müller',
        address: '123 Main St., Apt. #5',
      };

      mockedApiClient.post.mockResolvedValue({ data: mockApplicationResponse });

      await accountOpeningApi.submitApplication(specialCharsData);

      expect(mockedApiClient.post).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          formData: expect.objectContaining({
            firstName: "O'Brien",
            lastName: 'Müller',
          }),
        })
      );
    });
  });
});
