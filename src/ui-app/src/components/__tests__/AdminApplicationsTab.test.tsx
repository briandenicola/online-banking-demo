import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminApplicationsTab, { Application } from '../AdminApplicationsTab';

describe('AdminApplicationsTab', () => {
  const mockFetchApplications = jest.fn();
  const mockApprove = jest.fn();
  const mockReject = jest.fn();

  const mockApplications: Application[] = [
    {
      id: 'app-1',
      status: 'pending_review',
      createdAt: '2026-05-11T10:00:00Z',
      formData: {
        firstName: 'John',
        lastName: 'Doe',
        email: 'john@example.com',
        phone: '+12345678901',
        accountType: 'checking',
      },
    },
    {
      id: 'app-2',
      status: 'approved',
      createdAt: '2026-05-10T09:00:00Z',
      formData: {
        firstName: 'Jane',
        lastName: 'Smith',
        email: 'jane@example.com',
        phone: '+19876543210',
        accountType: 'savings',
      },
    },
    {
      id: 'app-3',
      status: 'rejected',
      createdAt: '2026-05-09T14:30:00Z',
      formData: {
        firstName: 'Bob',
        lastName: 'Johnson',
        email: 'bob@example.com',
        phone: '+15555555555',
        accountType: 'business',
      },
    },
  ];

  beforeEach(() => {
    mockFetchApplications.mockClear();
    mockApprove.mockClear();
    mockReject.mockClear();
    mockFetchApplications.mockResolvedValue(mockApplications);
  });

  describe('Happy Path', () => {
    it('renders applications table', async () => {
      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      expect(screen.getByText('Account Applications')).toBeInTheDocument();
      expect(screen.getByText('app-1')).toBeInTheDocument();
      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.getByText('john@example.com')).toBeInTheDocument();
    });

    it('displays all applications with correct data', () => {
      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.getByText('Jane Smith')).toBeInTheDocument();
      expect(screen.getByText('Bob Johnson')).toBeInTheDocument();
    });

    it('shows action buttons for each application', () => {
      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      const viewButtons = screen.getAllByRole('button', { name: /view/i });
      expect(viewButtons.length).toBeGreaterThan(0);
    });

    it('shows approve and reject buttons for pending review applications', () => {
      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument();
    });

    it('does not show approve/reject buttons for already processed applications', () => {
      const processedApps = mockApplications.filter((app) => app.status !== 'pending_review');

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={processedApps}
        />
      );

      expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument();
    });
  });

  describe('View Details', () => {
    it('opens details dialog when view button is clicked', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      const viewButtons = screen.getAllByRole('button', { name: /view/i });
      await user.click(viewButtons[0]);

      expect(await screen.findByText('Application Details')).toBeInTheDocument();
      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.getByText('john@example.com')).toBeInTheDocument();
    });

    it('closes details dialog when close button is clicked', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      const viewButtons = screen.getAllByRole('button', { name: /view/i });
      await user.click(viewButtons[0]);

      const closeButton = screen.getByRole('button', { name: /close/i });
      await user.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByText('Application Details')).not.toBeInTheDocument();
      });
    });

    it('displays personal information in details dialog', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      const viewButtons = screen.getAllByRole('button', { name: /view/i });
      await user.click(viewButtons[0]);

      expect(await screen.findByText('Personal Information')).toBeInTheDocument();
      expect(screen.getByText('+12345678901')).toBeInTheDocument();
      expect(screen.getByText('checking')).toBeInTheDocument();
    });
  });

  describe('Approve Application', () => {
    it('opens approve dialog when approve button is clicked', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onApproveApplication={mockApprove}
          applications={mockApplications}
        />
      );

      const approveButton = screen.getByRole('button', { name: /approve/i });
      await user.click(approveButton);

      expect(await screen.findByText('Approve Application')).toBeInTheDocument();
      expect(screen.getByLabelText(/review notes/i)).toBeInTheDocument();
    });

    it('submits approval with notes', async () => {
      const user = userEvent.setup();
      mockApprove.mockResolvedValue(undefined);

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onApproveApplication={mockApprove}
          applications={mockApplications}
        />
      );

      const approveButton = screen.getByRole('button', { name: /^approve$/i });
      await user.click(approveButton);

      const notesInput = screen.getByLabelText(/review notes/i);
      await user.type(notesInput, 'Application looks good');

      const submitButton = screen.getAllByRole('button', { name: /approve/i })[1];
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockApprove).toHaveBeenCalledWith('app-1', 'Application looks good');
      });
    });

    it('allows approving without notes', async () => {
      const user = userEvent.setup();
      mockApprove.mockResolvedValue(undefined);

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onApproveApplication={mockApprove}
          applications={mockApplications}
        />
      );

      const approveButton = screen.getByRole('button', { name: /^approve$/i });
      await user.click(approveButton);

      const submitButton = screen.getAllByRole('button', { name: /approve/i })[1];
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockApprove).toHaveBeenCalledWith('app-1', '');
      });
    });

    it('closes dialog after successful approval', async () => {
      const user = userEvent.setup();
      mockApprove.mockResolvedValue(undefined);

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onApproveApplication={mockApprove}
          applications={mockApplications}
        />
      );

      const approveButton = screen.getByRole('button', { name: /^approve$/i });
      await user.click(approveButton);

      const submitButton = screen.getAllByRole('button', { name: /approve/i })[1];
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.queryByText('Approve Application')).not.toBeInTheDocument();
      });
    });

    it('reloads applications after approval', async () => {
      const user = userEvent.setup();
      mockApprove.mockResolvedValue(undefined);

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onApproveApplication={mockApprove}
          applications={mockApplications}
        />
      );

      const approveButton = screen.getByRole('button', { name: /^approve$/i });
      await user.click(approveButton);

      const submitButton = screen.getAllByRole('button', { name: /approve/i })[1];
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFetchApplications).toHaveBeenCalled();
      });
    });
  });

  describe('Reject Application', () => {
    it('opens reject dialog when reject button is clicked', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onRejectApplication={mockReject}
          applications={mockApplications}
        />
      );

      const rejectButton = screen.getByRole('button', { name: /reject/i });
      await user.click(rejectButton);

      expect(await screen.findByText('Reject Application')).toBeInTheDocument();
    });

    it('requires notes for rejection', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onRejectApplication={mockReject}
          applications={mockApplications}
        />
      );

      const rejectButton = screen.getByRole('button', { name: /^reject$/i });
      await user.click(rejectButton);

      const submitButton = screen.getAllByRole('button', { name: /reject/i })[1];
      expect(submitButton).toBeDisabled();
    });

    it('submits rejection with notes', async () => {
      const user = userEvent.setup();
      mockReject.mockResolvedValue(undefined);

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onRejectApplication={mockReject}
          applications={mockApplications}
        />
      );

      const rejectButton = screen.getByRole('button', { name: /^reject$/i });
      await user.click(rejectButton);

      const notesInput = screen.getByLabelText(/review notes/i);
      await user.type(notesInput, 'Insufficient documentation');

      const submitButton = screen.getAllByRole('button', { name: /reject/i })[1];
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockReject).toHaveBeenCalledWith('app-1', 'Insufficient documentation');
      });
    });

    it('enables submit button when notes are provided', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onRejectApplication={mockReject}
          applications={mockApplications}
        />
      );

      const rejectButton = screen.getByRole('button', { name: /^reject$/i });
      await user.click(rejectButton);

      const notesInput = screen.getByLabelText(/review notes/i);
      await user.type(notesInput, 'Reason for rejection');

      const submitButton = screen.getAllByRole('button', { name: /reject/i })[1];
      expect(submitButton).not.toBeDisabled();
    });
  });

  describe('Filter Tabs', () => {
    it('renders filter tabs', () => {
      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      expect(screen.getByText('All')).toBeInTheDocument();
      expect(screen.getByText('Pending Review')).toBeInTheDocument();
      expect(screen.getByText('Approved')).toBeInTheDocument();
      expect(screen.getByText('Rejected')).toBeInTheDocument();
    });

    it('filters applications by status', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      const pendingTab = screen.getByText('Pending Review');
      await user.click(pendingTab);

      await waitFor(() => {
        expect(screen.getByText('John Doe')).toBeInTheDocument();
        expect(screen.queryByText('Jane Smith')).not.toBeInTheDocument();
        expect(screen.queryByText('Bob Johnson')).not.toBeInTheDocument();
      });
    });

    it('shows all applications when All tab is selected', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      const allTab = screen.getByText('All');
      await user.click(allTab);

      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.getByText('Jane Smith')).toBeInTheDocument();
      expect(screen.getByText('Bob Johnson')).toBeInTheDocument();
    });
  });

  describe('Loading State', () => {
    it('shows loading indicator when fetching applications', () => {
      render(<AdminApplicationsTab onFetchApplications={mockFetchApplications} />);

      expect(screen.getByRole('progressbar')).toBeInTheDocument();
    });

    it('hides loading indicator after applications load', async () => {
      const { rerender } = render(
        <AdminApplicationsTab onFetchApplications={mockFetchApplications} />
      );

      rerender(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      await waitFor(() => {
        expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('displays error message when fetch fails', async () => {
      const errorMessage = 'Failed to load applications';
      mockFetchApplications.mockRejectedValue(new Error(errorMessage));

      render(<AdminApplicationsTab onFetchApplications={mockFetchApplications} />);

      expect(await screen.findByText(errorMessage)).toBeInTheDocument();
    });

    it('displays error when approval fails', async () => {
      const user = userEvent.setup();
      const errorMessage = 'Approval failed';
      mockApprove.mockRejectedValue(new Error(errorMessage));

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onApproveApplication={mockApprove}
          applications={mockApplications}
        />
      );

      const approveButton = screen.getByRole('button', { name: /^approve$/i });
      await user.click(approveButton);

      const submitButton = screen.getAllByRole('button', { name: /approve/i })[1];
      await user.click(submitButton);

      expect(await screen.findByText(errorMessage)).toBeInTheDocument();
    });

    it('displays error when rejection fails', async () => {
      const user = userEvent.setup();
      const errorMessage = 'Rejection failed';
      mockReject.mockRejectedValue(new Error(errorMessage));

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onRejectApplication={mockReject}
          applications={mockApplications}
        />
      );

      const rejectButton = screen.getByRole('button', { name: /^reject$/i });
      await user.click(rejectButton);

      const notesInput = screen.getByLabelText(/review notes/i);
      await user.type(notesInput, 'Reason');

      const submitButton = screen.getAllByRole('button', { name: /reject/i })[1];
      await user.click(submitButton);

      expect(await screen.findByText(errorMessage)).toBeInTheDocument();
    });

    it('allows dismissing error message', async () => {
      const user = userEvent.setup();
      const errorMessage = 'Failed to load applications';
      mockFetchApplications.mockRejectedValue(new Error(errorMessage));

      render(<AdminApplicationsTab onFetchApplications={mockFetchApplications} />);

      const errorAlert = await screen.findByText(errorMessage);
      expect(errorAlert).toBeInTheDocument();

      const closeButton = screen.getByRole('button', { name: /close/i });
      await user.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByText(errorMessage)).not.toBeInTheDocument();
      });
    });
  });

  describe('Empty State', () => {
    it('shows message when no applications found', () => {
      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={[]}
        />
      );

      expect(screen.getByText('No applications found')).toBeInTheDocument();
    });
  });

  describe('Status Colors', () => {
    it('displays correct chip colors for different statuses', () => {
      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          applications={mockApplications}
        />
      );

      const pendingChip = screen.getByText('pending_review');
      const approvedChip = screen.getByText('approved');
      const rejectedChip = screen.getByText('rejected');

      expect(pendingChip).toBeInTheDocument();
      expect(approvedChip).toBeInTheDocument();
      expect(rejectedChip).toBeInTheDocument();
    });
  });

  describe('Dialog Cancellation', () => {
    it('cancels approve dialog', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onApproveApplication={mockApprove}
          applications={mockApplications}
        />
      );

      const approveButton = screen.getByRole('button', { name: /^approve$/i });
      await user.click(approveButton);

      const cancelButton = screen.getByRole('button', { name: /cancel/i });
      await user.click(cancelButton);

      await waitFor(() => {
        expect(screen.queryByText('Approve Application')).not.toBeInTheDocument();
      });

      expect(mockApprove).not.toHaveBeenCalled();
    });

    it('cancels reject dialog', async () => {
      const user = userEvent.setup();

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onRejectApplication={mockReject}
          applications={mockApplications}
        />
      );

      const rejectButton = screen.getByRole('button', { name: /^reject$/i });
      await user.click(rejectButton);

      const cancelButton = screen.getByRole('button', { name: /cancel/i });
      await user.click(cancelButton);

      await waitFor(() => {
        expect(screen.queryByText('Reject Application')).not.toBeInTheDocument();
      });

      expect(mockReject).not.toHaveBeenCalled();
    });
  });

  describe('Loading State in Review Dialog', () => {
    it('disables buttons while submitting approval', async () => {
      const user = userEvent.setup();
      mockApprove.mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 1000))
      );

      render(
        <AdminApplicationsTab
          onFetchApplications={mockFetchApplications}
          onApproveApplication={mockApprove}
          applications={mockApplications}
        />
      );

      const approveButton = screen.getByRole('button', { name: /^approve$/i });
      await user.click(approveButton);

      const submitButton = screen.getAllByRole('button', { name: /approve/i })[1];
      await user.click(submitButton);

      await waitFor(() => {
        expect(submitButton).toBeDisabled();
      });
    });
  });
});
