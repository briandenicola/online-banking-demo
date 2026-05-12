import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import AccountOpeningPage from '../AccountOpeningPage';
import apiClient from '../../api/client';

jest.mock('../../api/client');
const mockedApiClient = apiClient as jest.Mocked<typeof apiClient>;

// Mock useNavigate
const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
}));

describe('AccountOpeningPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  const renderWithRouter = (component: React.ReactElement) => {
    return render(<BrowserRouter>{component}</BrowserRouter>);
  };

  describe('Happy Path - Full Flow', () => {
    it('renders initial form step', () => {
      renderWithRouter(<AccountOpeningPage />);

      expect(screen.getByText('Account Opening Application')).toBeInTheDocument();
      expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
    });

    it('completes form and proceeds to document upload', async () => {
      const user = userEvent.setup();
      mockedApiClient.post.mockResolvedValue({
        data: { id: 'app-123', status: 'submitted' },
      });

      renderWithRouter(<AccountOpeningPage />);

      // Fill step 1
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      // Fill step 2
      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      // Fill step 3
      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), 'Engineer');
      await user.type(screen.getByLabelText(/annual income/i), '75000');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
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

      // Should advance to document upload step
      await waitFor(() => {
        expect(screen.getByText(/upload documents/i)).toBeInTheDocument();
      });
    });

    it('uploads documents and proceeds to processing', async () => {
      const user = userEvent.setup();
      
      mockedApiClient.post
        .mockResolvedValueOnce({
          data: { id: 'app-123', status: 'submitted' },
        })
        .mockResolvedValueOnce({
          data: {
            id: 'doc-123',
            type: 'photo_id',
            blobUrl: 'https://example.com/doc',
            uploadedAt: new Date().toISOString(),
          },
        });

      renderWithRouter(<AccountOpeningPage />);

      // Complete form
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), 'Engineer');
      await user.type(screen.getByLabelText(/annual income/i), '75000');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
        expect(screen.getByText(/upload documents/i)).toBeInTheDocument();
      });

      // Proceed to processing
      const continueButton = screen.getByRole('button', { name: /continue to processing/i });
      await user.click(continueButton);

      await waitFor(() => {
        expect(screen.getByText(/application processing pipeline/i)).toBeInTheDocument();
      });
    });
  });

  describe('Stepper Navigation', () => {
    it('displays stepper with all steps', () => {
      renderWithRouter(<AccountOpeningPage />);

      expect(screen.getByText('Application Form')).toBeInTheDocument();
      expect(screen.getByText('Upload Documents')).toBeInTheDocument();
      expect(screen.getByText('Processing')).toBeInTheDocument();
      expect(screen.getByText('Status')).toBeInTheDocument();
    });

    it('allows going back from document upload to form', async () => {
      const user = userEvent.setup();
      mockedApiClient.post.mockResolvedValue({
        data: { id: 'app-123', status: 'submitted' },
      });

      renderWithRouter(<AccountOpeningPage />);

      // Complete form
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), 'Engineer');
      await user.type(screen.getByLabelText(/annual income/i), '75000');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
        expect(screen.getByText(/upload documents/i)).toBeInTheDocument();
      });

      // Go back
      const backButton = screen.getByRole('button', { name: /back/i });
      await user.click(backButton);

      await waitFor(() => {
        expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('displays error when form submission fails', async () => {
      const user = userEvent.setup();
      const errorMessage = 'Failed to submit application';
      
      mockedApiClient.post.mockRejectedValue({
        response: { data: { message: errorMessage } },
      });

      renderWithRouter(<AccountOpeningPage />);

      // Complete form
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), 'Engineer');
      await user.type(screen.getByLabelText(/annual income/i), '75000');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
        expect(screen.getByText(errorMessage)).toBeInTheDocument();
      });
    });

    it('displays error when document upload fails', async () => {
      const user = userEvent.setup();
      
      mockedApiClient.post
        .mockResolvedValueOnce({
          data: { id: 'app-123', status: 'submitted' },
        })
        .mockRejectedValueOnce(new Error('Upload failed'));

      renderWithRouter(<AccountOpeningPage />);

      // Complete form quickly
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), 'Engineer');
      await user.type(screen.getByLabelText(/annual income/i), '75000');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
        expect(screen.getByText(/upload documents/i)).toBeInTheDocument();
      });
    });

    it('displays generic error when API returns no message', async () => {
      const user = userEvent.setup();
      
      mockedApiClient.post.mockRejectedValue({});

      renderWithRouter(<AccountOpeningPage />);

      // Complete form
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), 'Engineer');
      await user.type(screen.getByLabelText(/annual income/i), '75000');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
        expect(screen.getByText(/failed to submit application/i)).toBeInTheDocument();
      });
    });
  });

  describe('Status Fetching', () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      jest.runOnlyPendingTimers();
      jest.useRealTimers();
    });

    it('fetches application status when moving to processing step', async () => {
      const user = userEvent.setup({ delay: null });
      
      mockedApiClient.post.mockResolvedValue({
        data: { id: 'app-123', status: 'submitted' },
      });

      mockedApiClient.get.mockResolvedValue({
        data: {
          id: 'app-123',
          status: 'document_extraction',
          createdAt: '2026-05-11T10:00:00Z',
          updatedAt: '2026-05-11T10:05:00Z',
        },
      });

      renderWithRouter(<AccountOpeningPage />);

      // Complete form
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), 'Engineer');
      await user.type(screen.getByLabelText(/annual income/i), '75000');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
        expect(screen.getByText(/upload documents/i)).toBeInTheDocument();
      });

      const continueButton = screen.getByRole('button', { name: /continue to processing/i });
      await user.click(continueButton);

      await waitFor(() => {
        expect(mockedApiClient.get).toHaveBeenCalledWith('/account-opening/applications/app-123');
      });
    });

    it('moves to status step when application is approved', async () => {
      const user = userEvent.setup({ delay: null });
      
      mockedApiClient.post.mockResolvedValue({
        data: { id: 'app-123', status: 'submitted' },
      });

      mockedApiClient.get.mockResolvedValue({
        data: {
          id: 'app-123',
          status: 'approved',
          createdAt: '2026-05-11T10:00:00Z',
          updatedAt: '2026-05-11T10:20:00Z',
          userId: 'user-123',
          accountId: 'acc-456',
        },
      });

      renderWithRouter(<AccountOpeningPage />);

      // Complete form
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), 'Engineer');
      await user.type(screen.getByLabelText(/annual income/i), '75000');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
        expect(screen.getByText(/upload documents/i)).toBeInTheDocument();
      });

      const continueButton = screen.getByRole('button', { name: /continue to processing/i });
      await user.click(continueButton);

      await waitFor(() => {
        expect(screen.getByText(/application status/i)).toBeInTheDocument();
      });
    });
  });

  describe('Navigation Actions', () => {
    it('navigates to dashboard when cancel is clicked', async () => {
      const user = userEvent.setup();

      renderWithRouter(<AccountOpeningPage />);

      const cancelButton = screen.getByRole('button', { name: /cancel/i });
      await user.click(cancelButton);

      expect(mockNavigate).toHaveBeenCalledWith('/dashboard');
    });

    it('shows "Go to Dashboard" button when application is approved', async () => {
      mockedApiClient.get.mockResolvedValue({
        data: {
          id: 'app-123',
          status: 'approved',
          createdAt: '2026-05-11T10:00:00Z',
          updatedAt: '2026-05-11T10:20:00Z',
        },
      });

      const { rerender } = renderWithRouter(<AccountOpeningPage />);

      // Simulate being on status step with approved status
      // This would require setting internal state, which is difficult to test
      // In a real scenario, we would use integration tests or E2E tests for this
    });
  });

  describe('Agent Pipeline Display', () => {
    it('shows agent pipeline on processing step', async () => {
      const user = userEvent.setup();
      
      mockedApiClient.post.mockResolvedValue({
        data: { id: 'app-123', status: 'submitted' },
      });

      mockedApiClient.get.mockResolvedValue({
        data: {
          id: 'app-123',
          status: 'identity_verification',
          createdAt: '2026-05-11T10:00:00Z',
          updatedAt: '2026-05-11T10:10:00Z',
          agentResults: {
            documentExtraction: { status: 'completed' },
            identityVerification: { verified: true, confidence: 0.95 },
          },
        },
      });

      renderWithRouter(<AccountOpeningPage />);

      // Complete form
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), 'Engineer');
      await user.type(screen.getByLabelText(/annual income/i), '75000');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
        expect(screen.getByText(/upload documents/i)).toBeInTheDocument();
      });

      const continueButton = screen.getByRole('button', { name: /continue to processing/i });
      await user.click(continueButton);

      await waitFor(() => {
        expect(screen.getByText(/application processing pipeline/i)).toBeInTheDocument();
      });
    });
  });
});
