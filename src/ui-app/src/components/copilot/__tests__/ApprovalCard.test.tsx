/**
 * Render tests for the approval surface.
 *
 * These assert the promises the whole epic rests on, in the place where they
 * are actually kept or broken:
 *
 *   - the payload hash is VISIBLE, because the signature binds the hash and not
 *     the intent, so a person must be able to see what they are signing
 *   - `Sign` is gated, never live on first paint
 *   - the button never says "Approve" — that word describes a thing agents may
 *     never do, and using it as a generic label cheapens the distinction
 *   - an unfilled second slot renders a RULE ("a supervisor", "must be a
 *     different person") and never a named person
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import ApprovalCard, { TerminalApprovalCard } from '../ApprovalCard';
import { CopilotProvider } from '../CopilotContext';
import { demoApproval } from '../demoFixture';
import { Approval } from '../types';

function renderCard(approval: Approval, streamStatus: Parameters<typeof ApprovalCard>[0]['streamStatus'] = 'live') {
  return render(
    <CopilotProvider offline>
      <ApprovalCard approval={approval} streamStatus={streamStatus} />
    </CopilotProvider>
  );
}

describe('ApprovalCard', () => {
  it('shows the payload hash the signature will bind to', () => {
    renderCard(demoApproval);
    expect(screen.getByText(new RegExp(demoApproval.payloadHashShort, 'i'))).toBeInTheDocument();
  });

  it('labels the action on the Sign button and never says "Approve"', () => {
    renderCard(demoApproval);
    const sign = screen.getByRole('button', { name: /^Sign — / });
    expect(sign).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Approve/i })).not.toBeInTheDocument();
  });

  it('does not enable Sign on first paint', () => {
    // The dwell gate has not elapsed and the material fields have not been
    // read. A card that is signable the instant it appears is a card that gets
    // signed without being read.
    renderCard(demoApproval);
    expect(screen.getByRole('button', { name: /^Sign — / })).toBeDisabled();
  });

  it('offers denial with equal weight to signing', () => {
    renderCard(demoApproval);
    expect(screen.getByRole('button', { name: /^Deny$/ })).toBeEnabled();
  });

  it('describes the second signature as a rule, not a person', () => {
    renderCard(demoApproval);

    // The L2 slot states eligibility. It must never be phrased as an assignment
    // and must never carry a name: there is no `cosignerId` in the domain
    // precisely so a requester cannot choose their own reviewer, and the UI
    // must not reintroduce one by rendering a prospective signer.
    expect(screen.getByText(/awaiting a supervisor — must be a different person/i)).toBeInTheDocument();
    expect(screen.queryByText(/assigned to you/i)).not.toBeInTheDocument();
    expect(screen.getByText(/different people, not different proofs/i)).toBeInTheDocument();
  });

  it('does not name a prospective signer in any unfilled slot', () => {
    const roster = screen;
    renderCard(demoApproval);
    demoApproval.signatureSlots
      .filter((slot) => !slot.filled)
      .forEach((slot) => {
        expect(slot.signedBy).toBeUndefined();
        expect(slot.signedByUsername).toBeUndefined();
      });
    expect(roster.queryByText(/will be signed by/i)).not.toBeInTheDocument();
  });

  it('blocks signing while the live trace is not trustworthy', () => {
    renderCard(demoApproval, 'failed');
    expect(screen.getByRole('button', { name: /^Sign — / })).toBeDisabled();
    expect(screen.getByText(/Signing is disabled/i)).toBeInTheDocument();
  });

  it('surfaces the escalators that raised the rung', () => {
    renderCard(demoApproval);
    expect(screen.getAllByText(/L2/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Aggregate hold value exceeds the L1 ceiling/i)).toBeInTheDocument();
  });
});

describe('evidence shows findings, not just tool names', () => {
  it('renders the values the agent returned', () => {
    // The second of the two drops: even with `findings` populated, the list
    // rendered `item.label` and nothing else. Fixing the mapper alone would have
    // changed nothing on screen.
    const approval: Approval = {
      ...demoApproval,
      evidence: [
        {
          id: 'get_account',
          kind: 'record',
          label: 'Get account',
          findings: [
            { path: 'balance', label: 'Balance', value: 59480, format: 'currency', material: true },
            { path: 'count', label: 'Count', value: 3, format: 'text', material: false },
          ],
        },
      ],
    };
    renderCard(approval);

    // The panel is collapsed by default when the two positions concur, so open it.
    const toggle = screen.getByRole('button', { name: /evidence/i });
    fireEvent.click(toggle);

    expect(screen.getByText('Get account')).toBeInTheDocument();
    expect(screen.getByText(/59,480|59480/)).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });
});

describe('TerminalApprovalCard', () => {
  it('does not call a TTL expiry a denial by a person', () => {
    const expired: Approval = {
      ...demoApproval,
      status: 'denied',
      terminalReason: 'TTL_EXPIRED',
      terminalAt: new Date().toISOString(),
    };

    render(
      <CopilotProvider offline>
        <TerminalApprovalCard approval={expired} />
      </CopilotProvider>
    );

    expect(screen.getByText(/expired/i)).toBeInTheDocument();
    expect(screen.queryByText(/A reviewer denied this request/i)).not.toBeInTheDocument();
  });

  it('states that nothing was executed when policy voided a signature', () => {
    const escalated: Approval = {
      ...demoApproval,
      status: 'denied',
      terminalReason: 'POLICY_RUNG_ESCALATED',
      terminalAt: new Date().toISOString(),
    };

    render(
      <CopilotProvider offline>
        <TerminalApprovalCard approval={escalated} />
      </CopilotProvider>
    );

    expect(screen.getByText(/NOT been applied/i)).toBeInTheDocument();
  });
});

describe('co-signature identity clarity', () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it('states which identity is about to sign, for the two-session demo', () => {
    window.localStorage.setItem('auth_email', 'a.reyes@bank.example');
    window.localStorage.setItem('auth_role', 'supervisor');
    renderCard(demoApproval);
    expect(screen.getByText(/Signing as/i)).toBeInTheDocument();
    expect(screen.getByText('A Reyes')).toBeInTheDocument();
  });

  it('never calls the opening signature an independent co-signature', () => {
    // The old copy branched on the rung alone and told EVERY L2 signer they were
    // "providing the independent supervisor co-signature ... because you are a
    // different identity from the requester". Brian, signed in as `banker` on his
    // own request, was told his signature counted because he was not `banker`.
    window.localStorage.setItem('auth_email', 'banker@banking-demo.com');
    renderCard({ ...demoApproval, requesterUsername: 'banker' });
    expect(screen.queryByText(/independent supervisor co-signature/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/different identity from the requester/i)).not.toBeInTheDocument();

    // Positive assertion, deliberately: the slot cases are covered against the
    // pure function, but nothing else pins the COMPONENT passing the right
    // identity into it. Swap `identity.id` for the email or display name and the
    // requester branch would never match again — the copy would quietly degrade
    // to the neutral fallback while every other test stayed green.
    expect(screen.getByText(/you raised this request/i)).toBeInTheDocument();
  });

  it('points the acting identity at their own unfilled slot without naming a reviewer at proposal time', () => {
    window.localStorage.setItem('auth_email', 'a.reyes@bank.example');
    renderCard(demoApproval);
    expect(screen.getByText(/you \(A Reyes\) sign here/i)).toBeInTheDocument();
    // The other unfilled slot is still a rule, never an assignment.
    expect(screen.getByText(/must be a different person/i)).toBeInTheDocument();
  });

  it('shows no signing-identity banner when the caller may not sign', () => {
    window.localStorage.setItem('auth_email', 'a.reyes@bank.example');
    renderCard({ ...demoApproval, callerMaySign: false });
    expect(screen.queryByText(/Signing as/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sign here/i)).not.toBeInTheDocument();
  });
});

describe('TerminalApprovalCard — the path forward is live, not a dead end', () => {
  it('offers a clickable review of the replacement approval when superseded', () => {
    const superseded: Approval = {
      ...demoApproval,
      status: 'denied',
      terminalReason: 'PAYLOAD_SUPERSEDED',
      terminalAt: new Date().toISOString(),
      supersededByApprovalId: 'apr_demo_0002',
    };
    render(
      <CopilotProvider offline>
        <TerminalApprovalCard approval={superseded} />
      </CopilotProvider>
    );
    expect(screen.getByRole('button', { name: /Review the new approval/i })).toBeEnabled();
    // A blameless void tells the banker a fresh signature is required.
    expect(screen.getByText(/fresh signature is required/i)).toBeInTheDocument();
  });

  it('offers no review button when there is no replacement pointer', () => {
    const denied: Approval = {
      ...demoApproval,
      status: 'denied',
      terminalReason: 'HUMAN_DENIED',
      terminalAt: new Date().toISOString(),
    };
    render(
      <CopilotProvider offline>
        <TerminalApprovalCard approval={denied} />
      </CopilotProvider>
    );
    expect(screen.queryByRole('button', { name: /Review the new approval/i })).not.toBeInTheDocument();
  });
});
