import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import ApplicationForm from './ApplicationForm';
import { AuthProvider } from '../../contexts/AuthContext';

// Mock the account opening API module
jest.mock('../../api/accountOpening', () => ({
  createApplication: jest.fn(),
}));

// Mock the API client (needed for auth interceptor)
jest.mock('../../api/client', () => ({
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

import { createApplication } from '../../api/accountOpening';

const mockCreateApplication = createApplication as jest.MockedFunction<typeof createApplication>;

const renderForm = (props = {}) => {
  return render(
    <AuthProvider>
      <ApplicationForm
        onSubmit={jest.fn()}
        onApplicationCreated={jest.fn()}
        {...props}
      />
    </AuthProvider>
  );
};

describe('ApplicationForm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Step 1: Personal Info', () => {
    test('renders step 1 initially with personal info fields', () => {
      renderForm();

      expect(screen.getByLabelText(/First Name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Last Name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Date of Birth/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Email/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Phone/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/SSN.*Last 4/i)).toBeInTheDocument();
    });

    test('shows step indicator on step 1', () => {
      renderForm();

      expect(screen.getByText(/Personal Info/i)).toBeInTheDocument();
    });

    test('does not allow advancing with empty required fields', async () => {
      renderForm();

      const nextButton = screen.getByRole('button', { name: /Next/i });
      fireEvent.click(nextButton);

      await waitFor(() => {
        // Should still be on step 1 — validation prevents advancing
        expect(screen.getByLabelText(/First Name/i)).toBeInTheDocument();
      });
    });

    test('validates required fields before advancing', async () => {
      renderForm();

      const nextButton = screen.getByRole('button', { name: /Next/i });
      fireEvent.click(nextButton);

      await waitFor(() => {
        // Expect validation errors or still on step 1
        expect(screen.getByLabelText(/First Name/i)).toBeInTheDocument();
      });
    });
  });

  describe('Step navigation', () => {
    const fillStep1 = () => {
      fireEvent.change(screen.getByLabelText(/First Name/i), { target: { value: 'Jane' } });
      fireEvent.change(screen.getByLabelText(/Last Name/i), { target: { value: 'Doe' } });
      fireEvent.change(screen.getByLabelText(/Date of Birth/i), { target: { value: '1990-01-15' } });
      fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: 'jane@example.com' } });
      fireEvent.change(screen.getByLabelText(/Phone/i), { target: { value: '555-0100' } });
      fireEvent.change(screen.getByLabelText(/SSN.*Last 4/i), { target: { value: '1234' } });
    };

    const fillStep2 = () => {
      fireEvent.change(screen.getByLabelText(/Street/i), { target: { value: '123 Main St' } });
      fireEvent.change(screen.getByLabelText(/City/i), { target: { value: 'Springfield' } });
      fireEvent.change(screen.getByLabelText(/State/i), { target: { value: 'IL' } });
      fireEvent.change(screen.getByLabelText(/Zip/i), { target: { value: '62701' } });
    };

    const fillStep3 = () => {
      fireEvent.change(screen.getByLabelText(/Employer/i), { target: { value: 'Acme Corp' } });
      fireEvent.change(screen.getByLabelText(/Title/i), { target: { value: 'Engineer' } });
      fireEvent.change(screen.getByLabelText(/Annual Income/i), { target: { value: '85000' } });
      // Employment status may be a select or text field
      const statusField = screen.getByLabelText(/Employment Status/i);
      fireEvent.change(statusField, { target: { value: 'employed' } });
    };

    const fillStep4 = () => {
      const accountTypeField = screen.getByLabelText(/Account Type/i);
      fireEvent.change(accountTypeField, { target: { value: 'checking' } });
      fireEvent.change(screen.getByLabelText(/Initial Deposit/i), { target: { value: '500' } });
    };

    test('can advance from step 1 to step 2 after filling required fields', async () => {
      renderForm();
      fillStep1();

      const nextButton = screen.getByRole('button', { name: /Next/i });
      fireEvent.click(nextButton);

      await waitFor(() => {
        expect(screen.getByLabelText(/Street/i)).toBeInTheDocument();
      });
    });

    test('can navigate back from step 2 to step 1', async () => {
      renderForm();
      fillStep1();

      fireEvent.click(screen.getByRole('button', { name: /Next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/Street/i)).toBeInTheDocument();
      });

      const backButton = screen.getByRole('button', { name: /Back/i });
      fireEvent.click(backButton);

      await waitFor(() => {
        expect(screen.getByLabelText(/First Name/i)).toBeInTheDocument();
      });
    });

    test('preserves data when navigating back', async () => {
      renderForm();
      fillStep1();

      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => {
        expect(screen.getByLabelText(/Street/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /Back/i }));
      await waitFor(() => {
        const firstNameInput = screen.getByLabelText(/First Name/i) as HTMLInputElement;
        expect(firstNameInput.value).toBe('Jane');
      });
    });

    test('step 2 shows address fields', async () => {
      renderForm();
      fillStep1();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/Street/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/City/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/State/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/Zip/i)).toBeInTheDocument();
      });
    });

    test('step 3 shows employment fields', async () => {
      renderForm();
      fillStep1();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Street/i)).toBeInTheDocument());

      fillStep2();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/Employer/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/Annual Income/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/Employment Status/i)).toBeInTheDocument();
      });
    });

    test('step 4 shows account preferences', async () => {
      renderForm();
      fillStep1();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Street/i)).toBeInTheDocument());

      fillStep2();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Employer/i)).toBeInTheDocument());

      fillStep3();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/Account Type/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/Initial Deposit/i)).toBeInTheDocument();
      });
    });

    test('step 5 shows review with entered data', async () => {
      renderForm();
      fillStep1();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Street/i)).toBeInTheDocument());

      fillStep2();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Employer/i)).toBeInTheDocument());

      fillStep3();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Account Type/i)).toBeInTheDocument());

      fillStep4();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));

      await waitFor(() => {
        // Review step should display entered data
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
        expect(screen.getByText(/Doe/)).toBeInTheDocument();
        expect(screen.getByText(/jane@example.com/)).toBeInTheDocument();
        expect(screen.getByText(/123 Main St/)).toBeInTheDocument();
        expect(screen.getByText(/Acme Corp/)).toBeInTheDocument();
      });
    });

    test('step 5 has a Submit button instead of Next', async () => {
      renderForm();
      fillStep1();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Street/i)).toBeInTheDocument());

      fillStep2();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Employer/i)).toBeInTheDocument());

      fillStep3();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Account Type/i)).toBeInTheDocument());

      fillStep4();
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Submit/i })).toBeInTheDocument();
      });
    });
  });

  describe('Form submission', () => {
    const navigateToReview = async () => {
      fireEvent.change(screen.getByLabelText(/First Name/i), { target: { value: 'Jane' } });
      fireEvent.change(screen.getByLabelText(/Last Name/i), { target: { value: 'Doe' } });
      fireEvent.change(screen.getByLabelText(/Date of Birth/i), { target: { value: '1990-01-15' } });
      fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: 'jane@example.com' } });
      fireEvent.change(screen.getByLabelText(/Phone/i), { target: { value: '555-0100' } });
      fireEvent.change(screen.getByLabelText(/SSN.*Last 4/i), { target: { value: '1234' } });
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Street/i)).toBeInTheDocument());

      fireEvent.change(screen.getByLabelText(/Street/i), { target: { value: '123 Main St' } });
      fireEvent.change(screen.getByLabelText(/City/i), { target: { value: 'Springfield' } });
      fireEvent.change(screen.getByLabelText(/State/i), { target: { value: 'IL' } });
      fireEvent.change(screen.getByLabelText(/Zip/i), { target: { value: '62701' } });
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Employer/i)).toBeInTheDocument());

      fireEvent.change(screen.getByLabelText(/Employer/i), { target: { value: 'Acme Corp' } });
      fireEvent.change(screen.getByLabelText(/Title/i), { target: { value: 'Engineer' } });
      fireEvent.change(screen.getByLabelText(/Annual Income/i), { target: { value: '85000' } });
      fireEvent.change(screen.getByLabelText(/Employment Status/i), { target: { value: 'employed' } });
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByLabelText(/Account Type/i)).toBeInTheDocument());

      fireEvent.change(screen.getByLabelText(/Account Type/i), { target: { value: 'checking' } });
      fireEvent.change(screen.getByLabelText(/Initial Deposit/i), { target: { value: '500' } });
      fireEvent.click(screen.getByRole('button', { name: /Next/i }));
      await waitFor(() => expect(screen.getByRole('button', { name: /Submit/i })).toBeInTheDocument());
    };

    test('calls createApplication API on submit', async () => {
      const onApplicationCreated = jest.fn();
      mockCreateApplication.mockResolvedValueOnce({ id: 'app-1', status: 'submitted' as const, createdAt: '2026-05-01T10:00:00Z' });

      render(
        <AuthProvider>
          <ApplicationForm
            onSubmit={jest.fn()}
            onApplicationCreated={onApplicationCreated}
          />
        </AuthProvider>
      );

      await navigateToReview();
      fireEvent.click(screen.getByRole('button', { name: /Submit/i }));

      await waitFor(() => {
        expect(mockCreateApplication).toHaveBeenCalledTimes(1);
        expect(mockCreateApplication).toHaveBeenCalledWith(
          expect.objectContaining({
            firstName: 'Jane',
            lastName: 'Doe',
            email: 'jane@example.com',
          })
        );
      });
    });

    test('calls onApplicationCreated callback on success', async () => {
      const onApplicationCreated = jest.fn();
      mockCreateApplication.mockResolvedValueOnce({ id: 'app-1', status: 'submitted' as const, createdAt: '2026-05-01T10:00:00Z' });

      render(
        <AuthProvider>
          <ApplicationForm
            onSubmit={jest.fn()}
            onApplicationCreated={onApplicationCreated}
          />
        </AuthProvider>
      );

      await navigateToReview();
      fireEvent.click(screen.getByRole('button', { name: /Submit/i }));

      await waitFor(() => {
        expect(onApplicationCreated).toHaveBeenCalledWith(
          expect.objectContaining({ id: 'app-1' })
        );
      });
    });

    test('shows error message on API failure', async () => {
      mockCreateApplication.mockRejectedValueOnce({
        response: { status: 500, data: { detail: 'Internal server error' } },
      });

      render(
        <AuthProvider>
          <ApplicationForm
            onSubmit={jest.fn()}
            onApplicationCreated={jest.fn()}
          />
        </AuthProvider>
      );

      await navigateToReview();
      fireEvent.click(screen.getByRole('button', { name: /Submit/i }));

      await waitFor(() => {
        expect(
          screen.getByText(/error|failed|try again/i)
        ).toBeInTheDocument();
      });
    });
  });
});
