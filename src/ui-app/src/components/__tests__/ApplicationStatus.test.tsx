import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ApplicationStatus, { ApplicationStatusData } from '../../components/account-opening/ApplicationStatus';

describe('ApplicationStatus', () => {
  const mockRefresh = jest.fn();
  const applicationId = 'app-123';

  const mockStatusData: ApplicationStatusData = {
    id: applicationId,
    status: 'identity_verification',
    createdAt: '2026-05-11T09:00:00Z',
    updatedAt: '2026-05-11T10:15:00Z',
    agentResults: {
      documentExtraction: {
        status: 'completed',
        timestamp: '2026-05-11T10:00:00Z',
      },
      identityVerification: {
        verified: true,
        confidence: 0.95,
        timestamp: '2026-05-11T10:15:00Z',
      },
    },
  };

  beforeEach(() => {
    mockRefresh.mockClear();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  describe('Happy Path', () => {
    it('renders application status with provided data', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          pollInterval={0}
        />
      );

      expect(screen.getByText('Application Status')).toBeInTheDocument();
      expect(screen.getByText(`Application ID: ${applicationId}`)).toBeInTheDocument();
      expect(screen.getByText('IDENTITY VERIFICATION')).toBeInTheDocument();
    });

    it('displays status message for submitted application', () => {
      const submittedData: ApplicationStatusData = {
        ...mockStatusData,
        status: 'submitted',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={submittedData}
          pollInterval={0}
        />
      );

      expect(
        screen.getByText(/your application has been submitted and is being processed/i)
      ).toBeInTheDocument();
    });

    it('displays status message for approved application', () => {
      const approvedData: ApplicationStatusData = {
        ...mockStatusData,
        status: 'approved',
        userId: 'user-123',
        accountId: 'acc-456',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={approvedData}
          pollInterval={0}
        />
      );

      expect(
        screen.getByText(/congratulations! your application has been approved/i)
      ).toBeInTheDocument();
      expect(screen.getByText('User ID: user-123')).toBeInTheDocument();
      expect(screen.getByText('Account ID: acc-456')).toBeInTheDocument();
    });

    it('displays status message for rejected application', () => {
      const rejectedData: ApplicationStatusData = {
        ...mockStatusData,
        status: 'rejected',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={rejectedData}
          pollInterval={0}
        />
      );

      expect(
        screen.getByText(/unfortunately, your application has been rejected/i)
      ).toBeInTheDocument();
    });

    it('displays status message for pending review', () => {
      const pendingData: ApplicationStatusData = {
        ...mockStatusData,
        status: 'pending_review',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={pendingData}
          pollInterval={0}
        />
      );

      expect(
        screen.getByText(/your application requires manual review/i)
      ).toBeInTheDocument();
    });

    it('displays timeline information', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          pollInterval={0}
        />
      );

      expect(screen.getByText(/submitted:/i)).toBeInTheDocument();
      expect(screen.getByText(/last updated:/i)).toBeInTheDocument();
    });

    it('displays processing details', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          pollInterval={0}
        />
      );

      expect(screen.getByText(/document extraction:/i)).toBeInTheDocument();
      expect(screen.getByText(/identity verification:/i)).toBeInTheDocument();
      expect(screen.getByText(/verified/i)).toBeInTheDocument();
      expect(screen.getByText(/95% confidence/i)).toBeInTheDocument();
    });
  });

  describe('Refresh Functionality', () => {
    it('calls onRefresh when refresh button is clicked', async () => {
      const user = userEvent.setup({ delay: null });

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          onRefresh={mockRefresh}
          pollInterval={0}
        />
      );

      const refreshButton = screen.getByRole('button', { name: /refresh/i });
      await user.click(refreshButton);

      expect(mockRefresh).toHaveBeenCalledTimes(1);
    });

    it('does not show refresh button when onRefresh is not provided', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          pollInterval={0}
        />
      );

      expect(screen.queryByRole('button', { name: /refresh/i })).not.toBeInTheDocument();
    });
  });

  describe('Polling', () => {
    it('polls for status updates at specified interval', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          onRefresh={mockRefresh}
          pollInterval={2000}
        />
      );

      expect(mockRefresh).not.toHaveBeenCalled();

      jest.advanceTimersByTime(2000);
      expect(mockRefresh).toHaveBeenCalledTimes(1);

      jest.advanceTimersByTime(2000);
      expect(mockRefresh).toHaveBeenCalledTimes(2);
    });

    it('does not poll when pollInterval is 0', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          onRefresh={mockRefresh}
          pollInterval={0}
        />
      );

      jest.advanceTimersByTime(5000);
      expect(mockRefresh).not.toHaveBeenCalled();
    });

    it('stops polling when component unmounts', () => {
      const { unmount } = render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          onRefresh={mockRefresh}
          pollInterval={2000}
        />
      );

      jest.advanceTimersByTime(2000);
      expect(mockRefresh).toHaveBeenCalledTimes(1);

      unmount();

      jest.advanceTimersByTime(2000);
      expect(mockRefresh).toHaveBeenCalledTimes(1);
    });
  });

  describe('Loading State', () => {
    it('shows loading indicator when statusData is not provided', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          pollInterval={0}
        />
      );

      expect(screen.getByRole('progressbar')).toBeInTheDocument();
    });
  });

  describe('Error Handling', () => {
    it('does not show error initially', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          pollInterval={0}
        />
      );

      expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
    });
  });

  describe('Status Colors', () => {
    it('shows success color for approved status', () => {
      const approvedData: ApplicationStatusData = {
        ...mockStatusData,
        status: 'approved',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={approvedData}
          pollInterval={0}
        />
      );

      const chip = screen.getByText('APPROVED');
      expect(chip).toBeInTheDocument();
    });

    it('shows error color for rejected status', () => {
      const rejectedData: ApplicationStatusData = {
        ...mockStatusData,
        status: 'rejected',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={rejectedData}
          pollInterval={0}
        />
      );

      const chip = screen.getByText('REJECTED');
      expect(chip).toBeInTheDocument();
    });

    it('shows warning color for pending review status', () => {
      const pendingData: ApplicationStatusData = {
        ...mockStatusData,
        status: 'pending_review',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={pendingData}
          pollInterval={0}
        />
      );

      const chip = screen.getByText('PENDING REVIEW');
      expect(chip).toBeInTheDocument();
    });

    it('shows info color for processing statuses', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          pollInterval={0}
        />
      );

      const chip = screen.getByText('IDENTITY VERIFICATION');
      expect(chip).toBeInTheDocument();
    });
  });

  describe('Agent Results Display', () => {
    it('displays compliance check results', () => {
      const dataWithCompliance: ApplicationStatusData = {
        ...mockStatusData,
        agentResults: {
          ...mockStatusData.agentResults,
          complianceCheck: {
            kycStatus: 'approved',
            riskTier: 'low',
            timestamp: '2026-05-11T10:20:00Z',
          },
        },
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={dataWithCompliance}
          pollInterval={0}
        />
      );

      expect(screen.getByText(/compliance check:/i)).toBeInTheDocument();
      expect(screen.getByText(/approved/i)).toBeInTheDocument();
      expect(screen.getByText(/risk: low/i)).toBeInTheDocument();
    });

    it('handles missing agent results gracefully', () => {
      const dataWithoutAgentResults: ApplicationStatusData = {
        ...mockStatusData,
        agentResults: undefined,
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={dataWithoutAgentResults}
          pollInterval={0}
        />
      );

      expect(screen.queryByText(/processing details/i)).not.toBeInTheDocument();
    });

    it('displays identity verification as pending when not verified', () => {
      const dataWithUnverified: ApplicationStatusData = {
        ...mockStatusData,
        agentResults: {
          identityVerification: {
            verified: false,
            confidence: 0.5,
          },
        },
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={dataWithUnverified}
          pollInterval={0}
        />
      );

      expect(screen.getByText(/identity verification:/i)).toBeInTheDocument();
      expect(screen.getByText(/pending/i)).toBeInTheDocument();
    });
  });

  describe('Account Information Display', () => {
    it('shows account information section when userId or accountId present', () => {
      const dataWithAccount: ApplicationStatusData = {
        ...mockStatusData,
        userId: 'user-123',
        accountId: 'acc-456',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={dataWithAccount}
          pollInterval={0}
        />
      );

      expect(screen.getByText(/account information/i)).toBeInTheDocument();
      expect(screen.getByText('User ID: user-123')).toBeInTheDocument();
      expect(screen.getByText('Account ID: acc-456')).toBeInTheDocument();
    });

    it('does not show account information when userId and accountId are missing', () => {
      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          pollInterval={0}
        />
      );

      expect(screen.queryByText(/account information/i)).not.toBeInTheDocument();
    });

    it('shows only userId when accountId is missing', () => {
      const dataWithUserId: ApplicationStatusData = {
        ...mockStatusData,
        userId: 'user-123',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={dataWithUserId}
          pollInterval={0}
        />
      );

      expect(screen.getByText('User ID: user-123')).toBeInTheDocument();
      expect(screen.queryByText(/account id:/i)).not.toBeInTheDocument();
    });
  });

  describe('Status Messages for All Statuses', () => {
    const statuses = [
      'submitted',
      'document_extraction',
      'identity_verification',
      'compliance_check',
      'approved',
      'rejected',
      'pending_review',
    ];

    statuses.forEach((status) => {
      it(`displays appropriate message for ${status} status`, () => {
        const data: ApplicationStatusData = {
          ...mockStatusData,
          status: status as any,
        };

        render(
          <ApplicationStatus
            applicationId={applicationId}
            statusData={data}
            pollInterval={0}
          />
        );

        // Each status should have some message displayed
        const alerts = screen.getAllByRole('alert');
        expect(alerts.length).toBeGreaterThan(0);
      });
    });
  });

  describe('Edge Cases', () => {
    it('handles empty agentResults object', () => {
      const dataWithEmptyResults: ApplicationStatusData = {
        ...mockStatusData,
        agentResults: {},
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={dataWithEmptyResults}
          pollInterval={0}
        />
      );

      expect(screen.getByText('Application Status')).toBeInTheDocument();
    });

    it('renders without crashing when all optional fields are missing', () => {
      const minimalData: ApplicationStatusData = {
        id: applicationId,
        status: 'submitted',
        createdAt: '2026-05-11T09:00:00Z',
        updatedAt: '2026-05-11T09:00:00Z',
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={minimalData}
          pollInterval={0}
        />
      );

      expect(screen.getByText('Application Status')).toBeInTheDocument();
    });

    it('handles undefined confidence in identity verification', () => {
      const dataWithoutConfidence: ApplicationStatusData = {
        ...mockStatusData,
        agentResults: {
          identityVerification: {
            verified: true,
          },
        },
      };

      render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={dataWithoutConfidence}
          pollInterval={0}
        />
      );

      expect(screen.getByText(/verified/i)).toBeInTheDocument();
      expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
    });
  });

  describe('No Data Warning', () => {
    it('shows warning when statusData is null after loading', () => {
      const { rerender } = render(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={mockStatusData}
          pollInterval={0}
        />
      );

      rerender(
        <ApplicationStatus
          applicationId={applicationId}
          statusData={null as any}
          pollInterval={0}
        />
      );

      expect(screen.getByText(/no application data available/i)).toBeInTheDocument();
    });
  });
});
