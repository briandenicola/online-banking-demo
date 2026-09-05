/**
 * Batch approval tests.
 *
 * The one property that matters most here is a NEGATIVE one: an L2 item can
 * never be batched. So the sharpest test hands the component a group that has
 * been tampered with to include an L2 item and asserts it does not render — the
 * structural guarantee must not depend on the caller passing a clean group.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import BatchApprovalCard from '../BatchApprovalCard';
import { CopilotProvider } from '../CopilotContext';
import { demoApproval } from '../demoFixture';
import { BatchGroup } from '../approvalPolicy';
import { Approval } from '../types';

const l1Item = (id: string): Approval => ({
  ...demoApproval,
  id,
  actionId: 'act_fee_reversal',
  actionLabel: 'Reverse a $12 fee',
  status: 'pending',
  requiredRung: 'L1',
  requiredSigners: 1,
  callerMaySign: true,
  assessments: [],
  firedEscalators: [],
  payloadHash: `hash_${id}_000000000000`,
  payloadHashShort: `h_${id}`,
});

function renderBatch(items: Approval[], streamStatus: Parameters<typeof BatchApprovalCard>[0]['streamStatus'] = 'live') {
  const group: BatchGroup = { actionId: 'act_fee_reversal', actionLabel: 'Reverse a $12 fee', items };
  return render(
    <CopilotProvider offline>
      <BatchApprovalCard group={group} streamStatus={streamStatus} />
    </CopilotProvider>
  );
}

describe('BatchApprovalCard', () => {
  it('renders a scannable row per L1 item, not a count', () => {
    renderBatch([l1Item('a'), l1Item('b'), l1Item('c')]);
    expect(screen.getByText(/3 items · one action type/i)).toBeInTheDocument();
    // Each item's payload hash is shown — material fields rendered, never summarised.
    expect(screen.getByText(/h_a/)).toBeInTheDocument();
    expect(screen.getByText(/h_b/)).toBeInTheDocument();
    expect(screen.getByText(/h_c/)).toBeInTheDocument();
  });

  it('drops an L2 item even when a hand-built group smuggles one in', () => {
    const l2: Approval = { ...l1Item('l2'), requiredRung: 'L2', requiredSigners: 2 };
    renderBatch([l1Item('a'), l1Item('b'), l2]);
    // The two L1 items remain; the L2 item's hash never renders.
    expect(screen.getByText(/2 items · one action type/i)).toBeInTheDocument();
    expect(screen.queryByText(/h_l2/)).not.toBeInTheDocument();
  });

  it('never labels its action "Approve"', () => {
    renderBatch([l1Item('a'), l1Item('b')]);
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Sign \d+ items?$/ })).toBeInTheDocument();
  });

  it('disables batch signing when the stream is not trustworthy', () => {
    renderBatch([l1Item('a'), l1Item('b')], 'failed');
    expect(screen.getByRole('button', { name: /^Sign \d+ items?$/ })).toBeDisabled();
    expect(screen.getByText(/Signing paused/i)).toBeInTheDocument();
  });

  it('renders nothing for a degenerate batch of one', () => {
    const { container } = renderBatch([l1Item('solo')]);
    expect(container).toBeEmptyDOMElement();
  });

  it('states that a second opinion cannot be batched', () => {
    renderBatch([l1Item('a'), l1Item('b')]);
    expect(screen.getByText(/second opinion cannot be batched/i)).toBeInTheDocument();
  });
});
