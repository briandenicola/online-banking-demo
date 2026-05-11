import React from 'react';
import { render, screen, waitFor, act } from '@testing-library/react';
import ApplicationStatus from './ApplicationStatus';

jest.mock('../../api/accountOpening', () => ({
  getApplication: jest.fn(),
}));

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

// Mock the AgentPipeline component to isolate this test
jest.mock('./AgentPipeline', () => {
  return function MockAgentPipeline({ stages }: { stages: any[] }) {
    return (
      <div data-testid="agent-pipeline">
        {stages.map((s: any) => (
          <div key={s.name} data-testid={`stage-${s.name}`}>
            {s.name}: {s.status}
          </div>
        ))}
      </div>
    );
  };
});

import { getApplication } from '../../api/accountOpening';

const mockGetApplication = getApplication as jest.MockedFunction<typeof getApplication>;

const createApplicationResponse = (overrides: Record<string, any> = {}) => ({
  id: 'app-1',
  status: 'submitted',
  stages: [
    { name: 'Document Extraction', status: 'pending' },
    { name: 'Identity Verification', status: 'pending' },
    { name: 'Compliance Check', status: 'pending' },
    { name: 'Provisioning', status: 'pending' },
  ],
  ...overrides,
});

const renderStatus = (props = {}) => {
  return render(
    <ApplicationStatus applicationId="app-1" {...props} />
  );
};

describe('ApplicationStatus', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('Initial load', () => {
    test('fetches application status on mount', async () => {
      mockGetApplication.mockResolvedValue(createApplicationResponse());

      await act(async () => {
        renderStatus();
      });

      expect(mockGetApplication).toHaveBeenCalledWith('app-1');
    });

    test('renders AgentPipeline component', async () => {
      mockGetApplication.mockResolvedValue(createApplicationResponse());

      await act(async () => {
        renderStatus();
      });

      expect(screen.getByTestId('agent-pipeline')).toBeInTheDocument();
    });
  });

  describe('Polling behavior', () => {
    test('polls API every 2 seconds', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({ status: 'document_extraction' })
      );

      await act(async () => {
        renderStatus();
      });

      // Initial call
      expect(mockGetApplication).toHaveBeenCalledTimes(1);

      // Advance 2 seconds
      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(mockGetApplication).toHaveBeenCalledTimes(2);

      // Advance another 2 seconds
      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(mockGetApplication).toHaveBeenCalledTimes(3);
    });

    test('does not poll before 2 seconds', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({ status: 'document_extraction' })
      );

      await act(async () => {
        renderStatus();
      });

      expect(mockGetApplication).toHaveBeenCalledTimes(1);

      // Advance 1 second — should not poll yet
      await act(async () => {
        jest.advanceTimersByTime(1000);
      });
      expect(mockGetApplication).toHaveBeenCalledTimes(1);
    });
  });

  describe('Terminal status banners', () => {
    test('shows "Approved" banner when application is approved', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({
          status: 'approved',
          stages: [
            { name: 'Document Extraction', status: 'completed', confidence: 0.95 },
            { name: 'Identity Verification', status: 'completed', confidence: 0.91 },
            { name: 'Compliance Check', status: 'completed', confidence: 0.88 },
            { name: 'Provisioning', status: 'completed', confidence: 1.0 },
          ],
        })
      );

      await act(async () => {
        renderStatus();
      });

      await waitFor(() => {
        expect(screen.getByText(/approved/i)).toBeInTheDocument();
      });
    });

    test('shows "Rejected" banner when application is rejected', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({
          status: 'rejected',
          stages: [
            { name: 'Document Extraction', status: 'completed', confidence: 0.95 },
            { name: 'Identity Verification', status: 'failed', reasoning: 'Name mismatch' },
            { name: 'Compliance Check', status: 'pending' },
            { name: 'Provisioning', status: 'pending' },
          ],
        })
      );

      await act(async () => {
        renderStatus();
      });

      await waitFor(() => {
        expect(screen.getByText(/rejected/i)).toBeInTheDocument();
      });
    });

    test('shows "Under Review" for pending_review status', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({
          status: 'pending_review',
          stages: [
            { name: 'Document Extraction', status: 'completed', confidence: 0.95 },
            { name: 'Identity Verification', status: 'completed', confidence: 0.72 },
            { name: 'Compliance Check', status: 'completed', confidence: 0.65 },
            { name: 'Provisioning', status: 'completed', confidence: 0.5 },
          ],
        })
      );

      await act(async () => {
        renderStatus();
      });

      await waitFor(() => {
        expect(screen.getByText(/under review|pending review/i)).toBeInTheDocument();
      });
    });

    test('shows processing state while pipeline is running', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({
          status: 'identity_verification',
          stages: [
            { name: 'Document Extraction', status: 'completed', confidence: 0.95 },
            { name: 'Identity Verification', status: 'in_progress' },
            { name: 'Compliance Check', status: 'pending' },
            { name: 'Provisioning', status: 'pending' },
          ],
        })
      );

      await act(async () => {
        renderStatus();
      });

      // Should NOT show a terminal banner
      expect(screen.queryByText(/^approved$/i)).toBeNull();
      expect(screen.queryByText(/^rejected$/i)).toBeNull();
    });
  });

  describe('Polling stops on terminal status', () => {
    test('stops polling when status is approved', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({ status: 'approved' })
      );

      await act(async () => {
        renderStatus();
      });

      // Initial call
      expect(mockGetApplication).toHaveBeenCalledTimes(1);

      // Advance timers — should NOT make more calls
      await act(async () => {
        jest.advanceTimersByTime(6000);
      });

      // Should still be 1 call (no polling after terminal status)
      expect(mockGetApplication).toHaveBeenCalledTimes(1);
    });

    test('stops polling when status is rejected', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({ status: 'rejected' })
      );

      await act(async () => {
        renderStatus();
      });

      expect(mockGetApplication).toHaveBeenCalledTimes(1);

      await act(async () => {
        jest.advanceTimersByTime(6000);
      });

      expect(mockGetApplication).toHaveBeenCalledTimes(1);
    });

    test('stops polling when status is pending_review', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({ status: 'pending_review' })
      );

      await act(async () => {
        renderStatus();
      });

      expect(mockGetApplication).toHaveBeenCalledTimes(1);

      await act(async () => {
        jest.advanceTimersByTime(6000);
      });

      expect(mockGetApplication).toHaveBeenCalledTimes(1);
    });

    test('transitions from polling to stopped on status change', async () => {
      // First call: in progress (should keep polling)
      mockGetApplication
        .mockResolvedValueOnce(
          createApplicationResponse({ status: 'compliance_check' })
        )
        // Second call: still in progress
        .mockResolvedValueOnce(
          createApplicationResponse({ status: 'compliance_check' })
        )
        // Third call: approved (terminal)
        .mockResolvedValueOnce(
          createApplicationResponse({ status: 'approved' })
        );

      await act(async () => {
        renderStatus();
      });

      // Initial call
      expect(mockGetApplication).toHaveBeenCalledTimes(1);

      // First poll
      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(mockGetApplication).toHaveBeenCalledTimes(2);

      // Second poll — returns approved
      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      expect(mockGetApplication).toHaveBeenCalledTimes(3);

      // No more polls after terminal status
      await act(async () => {
        jest.advanceTimersByTime(6000);
      });
      expect(mockGetApplication).toHaveBeenCalledTimes(3);
    });
  });

  describe('Cleanup', () => {
    test('cleans up polling interval on unmount', async () => {
      mockGetApplication.mockResolvedValue(
        createApplicationResponse({ status: 'document_extraction' })
      );

      const { unmount } = await act(async () => {
        return renderStatus();
      });

      expect(mockGetApplication).toHaveBeenCalledTimes(1);

      // Unmount the component
      unmount();

      // Advance timers — should NOT make more calls
      await act(async () => {
        jest.advanceTimersByTime(6000);
      });

      expect(mockGetApplication).toHaveBeenCalledTimes(1);
    });
  });
});
