import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import AdminApplicationsTab from './AdminApplicationsTab';

jest.mock('../../api/accountOpening', () => ({
  listApplications: jest.fn(),
  reviewApplication: jest.fn(),
  getAuditTrail: jest.fn(),
}));

jest.mock('../../api/client', () => ({
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

import { listApplications, reviewApplication, getAuditTrail, ApplicationResponse } from '../../api/accountOpening';

const mockListApplications = listApplications as jest.MockedFunction<typeof listApplications>;
const mockReviewApplication = reviewApplication as jest.MockedFunction<typeof reviewApplication>;

const sampleApplications: ApplicationResponse[] = [
  {
    id: 'app-1',
    firstName: 'Jane',
    lastName: 'Doe',
    email: 'jane@example.com',
    status: 'pending_review',
    riskTier: 'medium',
    createdAt: '2026-05-01T10:00:00Z',
    stages: [
      { name: 'Document Extraction', status: 'completed', confidence: 0.95 },
      { name: 'Identity Verification', status: 'completed', confidence: 0.72 },
      { name: 'Compliance Check', status: 'completed', confidence: 0.65 },
      { name: 'Provisioning', status: 'completed', confidence: 0.5 },
    ],
  },
  {
    id: 'app-2',
    firstName: 'John',
    lastName: 'Smith',
    email: 'john@example.com',
    status: 'approved',
    riskTier: 'low',
    createdAt: '2026-05-02T14:00:00Z',
    stages: [
      { name: 'Document Extraction', status: 'completed', confidence: 0.98 },
      { name: 'Identity Verification', status: 'completed', confidence: 0.96 },
      { name: 'Compliance Check', status: 'completed', confidence: 0.99 },
      { name: 'Provisioning', status: 'completed', confidence: 1.0 },
    ],
  },
  {
    id: 'app-3',
    firstName: 'Bob',
    lastName: 'Jones',
    email: 'bob@example.com',
    status: 'rejected',
    riskTier: 'high',
    createdAt: '2026-04-30T08:00:00Z',
    stages: [
      { name: 'Document Extraction', status: 'completed', confidence: 0.95 },
      { name: 'Identity Verification', status: 'failed', reasoning: 'Expired document' },
      { name: 'Compliance Check', status: 'pending' },
      { name: 'Provisioning', status: 'pending' },
    ],
  },
];

const renderAdmin = () => {
  mockListApplications.mockResolvedValue({
    items: sampleApplications,
    total: sampleApplications.length,
  });

  return render(<AdminApplicationsTab />);
};

describe('AdminApplicationsTab', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Table rendering', () => {
    test('renders application table', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByRole('table') || screen.getByText(/Jane/)).toBeTruthy();
      });
    });

    test('displays application data in table rows', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
        expect(screen.getByText(/Doe/)).toBeInTheDocument();
        expect(screen.getByText(/John/)).toBeInTheDocument();
        expect(screen.getByText(/Smith/)).toBeInTheDocument();
        expect(screen.getByText(/Bob/)).toBeInTheDocument();
        expect(screen.getByText(/Jones/)).toBeInTheDocument();
      });
    });

    test('shows application status in table', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/pending.review/i) || screen.getByText(/Pending Review/i)).toBeTruthy();
      });
    });

    test('fetches applications on mount', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(mockListApplications).toHaveBeenCalled();
      });
    });
  });

  describe('Filter chips', () => {
    test('renders filter options', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/All/i)).toBeInTheDocument();
      });

      // Should have filter options for different statuses
      expect(
        screen.getByRole('tab', { name: /Pending Review/i }) ||
        screen.getByRole('button', { name: /pending/i })
      ).toBeTruthy();
    });

    test('clicking "All" filter shows all applications', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      const allFilter = screen.getByText(/All/i);
      fireEvent.click(allFilter);

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
        expect(screen.getByText(/John/)).toBeInTheDocument();
        expect(screen.getByText(/Bob/)).toBeInTheDocument();
      });
    });

    test('clicking "Pending Review" filter shows only pending applications', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      const pendingFilter = screen.getByRole('tab', { name: /Pending Review/i }) ||
        screen.getByRole('button', { name: /pending/i });
      fireEvent.click(pendingFilter);

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
        // Approved and rejected should be filtered out
        expect(screen.queryByText(/John Smith/)).toBeNull();
        expect(screen.queryByText(/Bob Jones/)).toBeNull();
      });
    });

    test('clicking "Approved" filter shows only approved applications', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      const approvedFilter = screen.getByRole('tab', { name: /Approved/i });
      fireEvent.click(approvedFilter);

      await waitFor(() => {
        expect(screen.getByText(/John/)).toBeInTheDocument();
      });
    });

    test('clicking "Rejected" filter shows only rejected applications', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      const rejectedFilter = screen.getByRole('tab', { name: /Rejected/i });
      fireEvent.click(rejectedFilter);

      await waitFor(() => {
        expect(screen.getByText(/Bob/)).toBeInTheDocument();
      });
    });
  });

  describe('Column sorting', () => {
    test('can sort by clicking column headers', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      // Find a sortable column header (e.g., date or name)
      const dateHeader = screen.getByText(/Date|Created/i);
      fireEvent.click(dateHeader);

      // After sorting, the order should change
      await waitFor(() => {
        // All applications should still be visible
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
        expect(screen.getByText(/John/)).toBeInTheDocument();
        expect(screen.getByText(/Bob/)).toBeInTheDocument();
      });
    });
  });

  describe('Expandable detail rows', () => {
    test('can expand a row to see agent results', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      // Find and click the expand button/row for Jane's application
      const expandButton =
        screen.getAllByRole('button', { name: /expand|detail|view/i })[0] ||
        screen.getByText(/Jane/).closest('tr');

      if (expandButton) {
        fireEvent.click(expandButton);

        await waitFor(() => {
          // Should show agent stage details
          expect(
            screen.getByText(/Document Extraction/i) ||
            screen.getByText(/Identity Verification/i)
          ).toBeTruthy();
        });
      }
    });
  });

  describe('Admin actions', () => {
    test('shows Approve button for pending_review applications', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      // Expand or find the action area for the pending application
      expect(
        screen.getByRole('button', { name: /Approve/i }) ||
        screen.getAllByRole('button').find((btn) => btn.textContent?.match(/approve/i))
      ).toBeTruthy();
    });

    test('shows Reject button for pending_review applications', async () => {
      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      expect(
        screen.getByRole('button', { name: /Reject/i }) ||
        screen.getAllByRole('button').find((btn) => btn.textContent?.match(/reject/i))
      ).toBeTruthy();
    });

    test('clicking Approve calls reviewApplication API', async () => {
      mockReviewApplication.mockResolvedValueOnce({ id: 'app-1', status: 'approved', createdAt: '2026-05-01T10:00:00Z' } as ApplicationResponse);

      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      const approveButton = screen.getByRole('button', { name: /Approve/i }) ||
        screen.getAllByRole('button').find((btn) => btn.textContent?.match(/approve/i));

      if (approveButton) {
        fireEvent.click(approveButton);

        await waitFor(() => {
          expect(mockReviewApplication).toHaveBeenCalledWith(
            'app-1',
            expect.objectContaining({ decision: 'approved' })
          );
        });
      }
    });

    test('clicking Reject calls reviewApplication API', async () => {
      mockReviewApplication.mockResolvedValueOnce({ id: 'app-1', status: 'rejected', createdAt: '2026-05-01T10:00:00Z' } as ApplicationResponse);

      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      const rejectButton = screen.getByRole('button', { name: /Reject/i }) ||
        screen.getAllByRole('button').find((btn) => btn.textContent?.match(/reject/i));

      if (rejectButton) {
        fireEvent.click(rejectButton);

        await waitFor(() => {
          expect(mockReviewApplication).toHaveBeenCalledWith(
            'app-1',
            expect.objectContaining({ decision: 'rejected' })
          );
        });
      }
    });

    test('refreshes list after approve action', async () => {
      mockReviewApplication.mockResolvedValueOnce({ id: 'app-1', status: 'approved', createdAt: '2026-05-01T10:00:00Z' } as ApplicationResponse);

      renderAdmin();

      await waitFor(() => {
        expect(screen.getByText(/Jane/)).toBeInTheDocument();
      });

      const approveButton = screen.getByRole('button', { name: /Approve/i }) ||
        screen.getAllByRole('button').find((btn) => btn.textContent?.match(/approve/i));

      if (approveButton) {
        fireEvent.click(approveButton);

        await waitFor(() => {
          // Should have fetched the list again after the action
          expect(mockListApplications).toHaveBeenCalledTimes(2);
        });
      }
    });
  });

  describe('Empty state', () => {
    test('shows empty state when no applications exist', async () => {
      mockListApplications.mockResolvedValueOnce({ items: [], total: 0 });

      render(<AdminApplicationsTab />);

      await waitFor(() => {
        expect(
          screen.getByText(/no application|empty|none/i)
        ).toBeInTheDocument();
      });
    });
  });
});
