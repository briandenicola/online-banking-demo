/**
 * Full-bleed surfaces must not carry the marketing footer.
 *
 * The `/copilot` console is an operator surface that owns the viewport and
 * scrolls internally. The SecureBank footer is ~110px of static chrome, and on a
 * short window (Brian's was 1550x780) it was the difference between the command
 * bar being visible and being clipped: the shell is `height:100vh; overflow:hidden`,
 * so anything the column cannot fit is cut off, and the command bar is the last
 * row. The footer also has nothing to say to a banker mid-approval.
 *
 * Ordinary pages keep the footer — that is the regression this guards against.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import AppShell, { useFullBleedSurface } from '../AppShell';
import { FeatureFlagProvider } from '../../contexts/FeatureFlagContext';

jest.mock('../../contexts/AuthContext', () => ({
  ...jest.requireActual('../../contexts/AuthContext'),
  useAuthContext: () => ({
    user: { id: 'u1', username: 'banker', email: 'banker@test', role: 'banker' },
    token: 'test-token',
    isAdmin: false,
    isBanker: true,
    mayViewAdminObservability: false,
    login: jest.fn(),
    logout: jest.fn(),
    register: jest.fn(),
    loading: false,
  }),
}));

const FullBleedChild: React.FC = () => {
  useFullBleedSurface();
  return <div>operator surface</div>;
};

function renderShell(children: React.ReactNode) {
  return render(
    <FeatureFlagProvider>
      <AppShell>{children}</AppShell>
    </FeatureFlagProvider>
  );
}

describe('AppShell footer', () => {
  it('renders on an ordinary page', () => {
    renderShell(<div>a normal page</div>);
    expect(screen.getByText(/FDIC Insured/i)).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  it('is suppressed on a full-bleed surface, freeing the vertical room', () => {
    renderShell(<FullBleedChild />);
    expect(screen.getByText('operator surface')).toBeInTheDocument();
    expect(screen.queryByText(/FDIC Insured/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
  });

  it('puts the footer back when the full-bleed surface unmounts', () => {
    const { rerender } = renderShell(<FullBleedChild />);
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();

    rerender(
      <FeatureFlagProvider>
        <AppShell>
          <div>a normal page</div>
        </AppShell>
      </FeatureFlagProvider>
    );

    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });
});
