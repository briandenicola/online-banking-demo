/**
 * What each identity actually SEES on the Classic Admin page.
 *
 * The pure rules are pinned in adminTabs.test.ts; this asserts the page is
 * wired to them — that the filter reaches the tab strip AND the panel renderer,
 * which is where the positional-index hazard lived.
 */
import React from 'react';
import { render, screen, waitFor, act } from '@testing-library/react';
import AdminPage from '../AdminPage';
import { AuthProvider } from '../../contexts/AuthContext';
import { FeatureFlagProvider } from '../../contexts/FeatureFlagContext';

jest.mock('../../api/client', () => ({
  __esModule: true,
  default: { get: jest.fn().mockResolvedValue({ data: [] }) },
}));

// Panels are stubbed so this suite is about VISIBILITY, not about each tab's
// own behaviour. Each stub announces itself, so a wrongly-rendered panel is
// caught by name rather than inferred.
jest.mock('../../components/account-opening/AdminApplicationsTab', () => () => (
  <div>PANEL Applications</div>
));
jest.mock('../../components/AdminUserManagementTab', () => () => (
  <div>PANEL User Management</div>
));
jest.mock('../../components/AdminChatbotPromptTab', () => () => <div>PANEL Chatbot Prompt</div>);
jest.mock('../../components/AdminEvalTab', () => () => <div>PANEL Eval</div>);
jest.mock('../../components/AdminLoginAuditTab', () => () => <div>PANEL Login Audit</div>);
jest.mock('../../components/AdminFoundryStatusTab', () => () => <div>PANEL Foundry Status</div>);
jest.mock('../../components/FlaggedTransactionsTab', () => ({
  __esModule: true,
  default: () => <div>PANEL Flagged</div>,
}));
jest.mock('../../components/AllTransactionsTab', () => ({
  __esModule: true,
  default: () => <div>PANEL All Transactions</div>,
}));

function b64(o: unknown) {
  return btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function signIn(role: string, effectiveRoles: string[]) {
  localStorage.setItem(
    'auth_token',
    `${b64({ alg: 'none' })}.${b64({ role, effectiveRoles })}.sig`
  );
  localStorage.setItem('auth_email', 'a.person@example.com');
  localStorage.setItem('auth_role', role);
}

async function renderAdmin() {
  await act(async () => {
    render(
      <FeatureFlagProvider>
        <AuthProvider>
          <AdminPage />
        </AuthProvider>
      </FeatureFlagProvider>
    );
  });
  await waitFor(() => expect(screen.getByText('Admin Dashboard')).toBeInTheDocument());
}

const tabNames = () =>
  screen.queryAllByRole('tab').map((t) => t.textContent);

beforeEach(() => {
  localStorage.clear();
  jest.clearAllMocks();
});

describe('Classic Admin — supervisor', () => {
  beforeEach(() => signIn('supervisor', ['supervisor', 'banker']));

  it('sees the five read-only observability tabs', async () => {
    await renderAdmin();
    expect(tabNames()).toEqual([
      'All Transactions',
      'Flagged Transactions',
      'AI Evaluation',
      'Login Audit',
      'System Health',
    ]);
  });

  /** The assertion that protects the demo's separation-of-duties story. */
  it('does NOT see User Management', async () => {
    await renderAdmin();
    expect(tabNames()).not.toContain('User Management');
    expect(screen.queryByText('PANEL User Management')).not.toBeInTheDocument();
  });

  it('does not see the other write tabs', async () => {
    await renderAdmin();
    expect(tabNames()).not.toContain('Chatbot Prompt');
    expect(tabNames()).not.toContain('Account Applications');
    expect(screen.queryByText('PANEL Chatbot Prompt')).not.toBeInTheDocument();
    expect(screen.queryByText('PANEL Applications')).not.toBeInTheDocument();
  });

  /**
   * The positional-index hazard, at the render layer.
   *
   * Under the old `activeTab === 1 && <AdminUserManagementTab/>`, the FIRST tab
   * of a filtered list would have rendered the Applications panel and the
   * second would have rendered User Management. Assert the panel by name, not
   * by absence of an error.
   */
  it('opens on All Transactions, not whatever sits at index 0 of the full list', async () => {
    await renderAdmin();
    expect(screen.getByText('PANEL All Transactions')).toBeInTheDocument();
    expect(screen.queryByText('PANEL Applications')).not.toBeInTheDocument();
  });

  it('keeps the frozen comparison region on the tabs it does show', async () => {
    await renderAdmin();
    const regions = screen
      .queryAllByRole('tab')
      .map((t) => t.getAttribute('data-comparison-region'));
    expect(regions).toEqual([
      'admin-transactions',
      'admin-flagged',
      'admin-eval',
      'admin-audit',
      'admin-health',
    ]);
  });
});

describe('Classic Admin — admin', () => {
  beforeEach(() => signIn('admin', ['admin']));

  it('still sees all eight tabs, including User Management', async () => {
    await renderAdmin();
    expect(tabNames()).toEqual([
      'Account Applications',
      'User Management',
      'All Transactions',
      'Flagged Transactions',
      'Chatbot Prompt',
      'AI Evaluation',
      'Login Audit',
      'System Health',
    ]);
  });

  it('still opens on Account Applications', async () => {
    await renderAdmin();
    expect(screen.getByText('PANEL Applications')).toBeInTheDocument();
  });
});

describe('Classic Admin — plain banker', () => {
  beforeEach(() => signIn('banker', ['banker']));

  it('sees no tabs and no panels', async () => {
    // The route is not registered for this identity; if it is ever reached
    // anyway, the page must not fall open.
    await renderAdmin();
    expect(tabNames()).toEqual([]);
    expect(screen.queryByText(/^PANEL /)).not.toBeInTheDocument();
    expect(screen.getByText(/do not have access to the admin console/i)).toBeInTheDocument();
  });
});
