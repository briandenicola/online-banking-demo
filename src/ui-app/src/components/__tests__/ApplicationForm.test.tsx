import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ApplicationForm, { ApplicationFormData } from '../../components/account-opening/ApplicationForm';

describe('ApplicationForm', () => {
  const mockSubmit = jest.fn();
  const mockCancel = jest.fn();

  const validFormData: ApplicationFormData = {
    firstName: 'John',
    lastName: 'Doe',
    dateOfBirth: '1990-01-01',
    email: 'john.doe@example.com',
    phone: '+12345678901',
    address: '123 Main St',
    city: 'New York',
    state: 'NY',
    zipCode: '10001',
    employment: 'Software Engineer',
    annualIncome: 75000,
    accountType: 'checking',
  };

  beforeEach(() => {
    mockSubmit.mockClear();
    mockCancel.mockClear();
  });

  describe('Happy Path', () => {
    it('renders the form with step 1 (Personal Information)', () => {
      render(<ApplicationForm onSubmit={mockSubmit} />);
      
      expect(screen.getByText('Account Opening Application')).toBeInTheDocument();
      expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/last name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/date of birth/i)).toBeInTheDocument();
    });

    it('completes all steps and submits form successfully', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      // Step 1: Personal Information
      await user.type(screen.getByLabelText(/first name/i), validFormData.firstName);
      await user.type(screen.getByLabelText(/last name/i), validFormData.lastName);
      await user.type(screen.getByLabelText(/date of birth/i), validFormData.dateOfBirth);
      
      await user.click(screen.getByRole('button', { name: /next/i }));

      // Step 2: Contact Details
      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), validFormData.email);
      await user.type(screen.getByLabelText(/phone/i), validFormData.phone);
      await user.type(screen.getByLabelText(/address/i), validFormData.address);
      await user.type(screen.getByLabelText(/city/i), validFormData.city);
      await user.type(screen.getByLabelText(/state/i), validFormData.state);
      await user.type(screen.getByLabelText(/zip code/i), validFormData.zipCode);

      await user.click(screen.getByRole('button', { name: /next/i }));

      // Step 3: Financial Information
      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/employment/i), validFormData.employment);
      await user.type(screen.getByLabelText(/annual income/i), validFormData.annualIncome.toString());

      await user.click(screen.getByRole('button', { name: /submit/i }));

      await waitFor(() => {
        expect(mockSubmit).toHaveBeenCalledWith(validFormData);
      });
    });

    it('navigates between steps using Back button', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      // Fill step 1 and go to step 2
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      // Go back to step 1
      await user.click(screen.getByRole('button', { name: /back/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/first name/i)).toHaveValue('John');
      });
    });

    it('renders with initial data', () => {
      render(<ApplicationForm onSubmit={mockSubmit} initialData={validFormData} />);

      expect(screen.getByLabelText(/first name/i)).toHaveValue(validFormData.firstName);
      expect(screen.getByLabelText(/last name/i)).toHaveValue(validFormData.lastName);
    });
  });

  describe('Validation', () => {
    it('shows error when first name is empty', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      expect(await screen.findByText(/first name is required/i)).toBeInTheDocument();
      expect(mockSubmit).not.toHaveBeenCalled();
    });

    it('shows error when user is under 18', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      const futureDate = new Date();
      futureDate.setFullYear(futureDate.getFullYear() - 10);
      const dateString = futureDate.toISOString().split('T')[0];

      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), dateString);
      await user.click(screen.getByRole('button', { name: /next/i }));

      expect(await screen.findByText(/must be at least 18 years old/i)).toBeInTheDocument();
    });

    it('validates email format', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      // Complete step 1
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'invalid-email');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      expect(await screen.findByText(/invalid email format/i)).toBeInTheDocument();
    });

    it('validates phone format', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      // Complete step 1
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/phone/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '123');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001');
      await user.click(screen.getByRole('button', { name: /next/i }));

      expect(await screen.findByText(/invalid phone format/i)).toBeInTheDocument();
    });

    it('validates ZIP code format', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      // Complete step 1
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/zip code/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), 'invalid');
      await user.click(screen.getByRole('button', { name: /next/i }));

      expect(await screen.findByText(/invalid zip code format/i)).toBeInTheDocument();
    });

    it('validates annual income is greater than 0', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      // Complete steps 1 and 2
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
      await user.type(screen.getByLabelText(/annual income/i), '0');
      await user.click(screen.getByRole('button', { name: /submit/i }));

      expect(await screen.findByText(/annual income must be greater than 0/i)).toBeInTheDocument();
    });

    it('clears error when field is corrected', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      expect(await screen.findByText(/first name is required/i)).toBeInTheDocument();

      await user.type(screen.getByLabelText(/first name/i), 'John');

      expect(screen.queryByText(/first name is required/i)).not.toBeInTheDocument();
    });
  });

  describe('Cancel', () => {
    it('calls onCancel when cancel button is clicked', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} onCancel={mockCancel} />);

      await user.click(screen.getByRole('button', { name: /cancel/i }));

      expect(mockCancel).toHaveBeenCalled();
    });

    it('does not render cancel button if onCancel is not provided', () => {
      render(<ApplicationForm onSubmit={mockSubmit} />);

      expect(screen.queryByRole('button', { name: /cancel/i })).not.toBeInTheDocument();
    });
  });

  describe('Account Type Selection', () => {
    it('allows selecting different account types', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      // Navigate to step 3
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
        expect(screen.getByLabelText(/account type/i)).toBeInTheDocument();
      });

      const accountTypeSelect = screen.getByLabelText(/account type/i);
      expect(accountTypeSelect).toHaveValue('checking');
    });
  });

  describe('Edge Cases', () => {
    it('handles valid ZIP code with extension', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      // Complete step 1
      await user.type(screen.getByLabelText(/first name/i), 'John');
      await user.type(screen.getByLabelText(/last name/i), 'Doe');
      await user.type(screen.getByLabelText(/date of birth/i), '1990-01-01');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/zip code/i)).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/email/i), 'john@example.com');
      await user.type(screen.getByLabelText(/phone/i), '+12345678901');
      await user.type(screen.getByLabelText(/address/i), '123 Main St');
      await user.type(screen.getByLabelText(/city/i), 'New York');
      await user.type(screen.getByLabelText(/state/i), 'NY');
      await user.type(screen.getByLabelText(/zip code/i), '10001-1234');
      await user.click(screen.getByRole('button', { name: /next/i }));

      await waitFor(() => {
        expect(screen.getByLabelText(/employment/i)).toBeInTheDocument();
      });
    });

    it('validates all required fields on each step', async () => {
      const user = userEvent.setup();
      render(<ApplicationForm onSubmit={mockSubmit} />);

      // Try to proceed without filling anything
      await user.click(screen.getByRole('button', { name: /next/i }));

      expect(await screen.findByText(/first name is required/i)).toBeInTheDocument();
      expect(await screen.findByText(/last name is required/i)).toBeInTheDocument();
      expect(await screen.findByText(/date of birth is required/i)).toBeInTheDocument();
    });
  });
});
