import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AccountOpeningPage from './AccountOpeningPage';
import { ACCOUNT_OPENING_STORAGE_KEY } from '../api/accountOpening';

const mockNavigate = jest.fn();

jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
}));

// Mock child components to isolate page orchestration logic
jest.mock('../components/account-opening/ApplicationForm', () => {
  return function MockApplicationForm({
    onApplicationCreated,
  }: {
    onSubmit?: () => void;
    onApplicationCreated: (app: any) => void;
  }) {
    return (
      <div data-testid="application-form">
        <button
          onClick={() =>
            onApplicationCreated({ id: 'app-1', status: 'submitted' })
          }
        >
          Mock Submit
        </button>
      </div>
    );
  };
});

jest.mock('../components/account-opening/DocumentUpload', () => {
  return function MockDocumentUpload({
    applicationId,
    onUploadComplete,
  }: {
    applicationId: string;
    onUploadComplete: () => void;
  }) {
    return (
      <div data-testid="document-upload">
        <span>Upload for {applicationId}</span>
        <button onClick={onUploadComplete}>Mock Upload Complete</button>
      </div>
    );
  };
});

jest.mock('../components/account-opening/ApplicationStatus', () => {
  return function MockApplicationStatus({
    applicationId,
  }: {
    applicationId: string;
  }) {
    return (
      <div data-testid="application-status">
        <span>Status for {applicationId}</span>
      </div>
    );
  };
});

jest.mock('../api/client', () => ({
  __esModule: true,
  default: {
    post: jest.fn(),
    get: jest.fn(),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() },
    },
  },
}));

const renderPage = () => {
  return render(<AccountOpeningPage />);
};

describe('AccountOpeningPage', () => {
  beforeEach(() => {
    localStorage.removeItem(ACCOUNT_OPENING_STORAGE_KEY);
    mockNavigate.mockClear();
  });

  describe('Initial state', () => {
    test('renders the application form initially', () => {
      renderPage();

      expect(screen.getByTestId('application-form')).toBeInTheDocument();
    });

    test('does not render document upload initially', () => {
      renderPage();

      expect(screen.queryByTestId('document-upload')).toBeNull();
    });

    test('does not render application status initially', () => {
      renderPage();

      expect(screen.queryByTestId('application-status')).toBeNull();
    });

    test('shows page heading', () => {
      renderPage();

      expect(
        screen.getByText(/Open.*Account|Account Opening|New Account/i)
      ).toBeInTheDocument();
    });
  });

  describe('Form → Document Upload transition', () => {
    test('transitions to document upload after form submission', async () => {
      renderPage();

      // Simulate form submission via mock
      fireEvent.click(screen.getByText('Mock Submit'));

      await waitFor(() => {
        expect(screen.getByTestId('document-upload')).toBeInTheDocument();
      });
    });

    test('passes application ID to document upload', async () => {
      renderPage();

      fireEvent.click(screen.getByText('Mock Submit'));

      await waitFor(() => {
        expect(screen.getByText('Upload for app-1')).toBeInTheDocument();
      });
    });

    test('hides form after submission', async () => {
      renderPage();

      fireEvent.click(screen.getByText('Mock Submit'));

      await waitFor(() => {
        expect(screen.queryByTestId('application-form')).toBeNull();
      });
    });
  });

  describe('Document Upload → Status Tracking transition', () => {
    test('navigates to status page after document upload', async () => {
      renderPage();

      // Step 1: Submit form
      fireEvent.click(screen.getByText('Mock Submit'));
      await waitFor(() => {
        expect(screen.getByTestId('document-upload')).toBeInTheDocument();
      });

      // Step 2: Complete upload
      fireEvent.click(screen.getByText('Mock Upload Complete'));

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/applications/app-1/status');
      });
    });

    test('passes application ID in status route', async () => {
      renderPage();

      fireEvent.click(screen.getByText('Mock Submit'));
      await waitFor(() => {
        expect(screen.getByTestId('document-upload')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Mock Upload Complete'));

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/applications/app-1/status');
      });
    });

    test('triggers navigation after upload complete', async () => {
      renderPage();

      fireEvent.click(screen.getByText('Mock Submit'));
      await waitFor(() => {
        expect(screen.getByTestId('document-upload')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Mock Upload Complete'));

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledTimes(1);
      });
    });
  });

  describe('Full flow', () => {
    test('completes full flow: Form → Upload → Status', async () => {
      renderPage();

      // Initially shows form
      expect(screen.getByTestId('application-form')).toBeInTheDocument();

      // Submit form → shows upload
      fireEvent.click(screen.getByText('Mock Submit'));
      await waitFor(() => {
        expect(screen.getByTestId('document-upload')).toBeInTheDocument();
        expect(screen.queryByTestId('application-form')).toBeNull();
      });

      // Complete upload → routes to status page
      fireEvent.click(screen.getByText('Mock Upload Complete'));
      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/applications/app-1/status');
      });
    });
  });
});
