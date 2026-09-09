/**
 * The rendered key-factor row, through the REAL card.
 *
 * The pure-function guards live in `supervisorFactors.test.ts`. These exist
 * because the lie was only ever visible in the DOM: a tick appended by a ternary
 * in JSX, a value column filled by the service, and a bold-red DIVERGENT flag
 * driven from a comparison in a third file. Each was defensible where it was
 * written; only the rendered row showed them contradicting each other.
 */

import React from 'react';
import { cleanup, render, within } from '@testing-library/react';
import ApprovalCard from '../ApprovalCard';
import { CopilotProvider } from '../CopilotContext';
import { demoApproval } from '../demoFixture';
import { SUPERVISOR_UNAVAILABLE_FACTOR } from '../supervisorFactors';
import { AgentKeyFactor, Approval } from '../types';

function renderWithFactors(
  supervisorFactors: AgentKeyFactor[],
  primaryFactors?: AgentKeyFactor[]
): HTMLElement {
  cleanup();
  const approval: Approval = {
    ...demoApproval,
    assessments: [
      { ...demoApproval.assessments[0], keyFactors: primaryFactors },
      { ...demoApproval.assessments[1], keyFactors: supervisorFactors },
    ],
  };
  const view = render(
    <CopilotProvider offline>
      <ApprovalCard approval={approval} streamStatus="live" />
    </CopilotProvider>
  );
  return view.container;
}

describe('the key factor row', () => {
  it('the shipped fixture matches what the service can produce (anti-vacuous guard)', () => {
    // The primary NOW states factors of its own — it did not until this week —
    // so the assertion is no longer "it sends none". What must still hold is the
    // GROUNDING: on BOTH sides a factor is a flat statement. `value` was the
    // fabricated constant "independently corroborated"; `concern` defaulted to
    // false put a green tick beside a judgement nobody made. Neither builder has
    // a parameter for either, and this is the fixture-side half of that.
    for (const assessment of demoApproval.assessments) {
      const factors = assessment.keyFactors!;
      expect(factors.length).toBeGreaterThan(0);
      for (const factor of factors) {
        expect(factor.value).toBeUndefined();
        expect(factor.concern).toBeUndefined();
      }
    }
  });

  describe('a factor the agent did not classify', () => {
    it('renders no tick', () => {
      const c = renderWithFactors([{ label: 'pattern matches invoice settlement' }]);
      const row = within(c).getByTestId('factor-row');
      expect(row.textContent).toContain('pattern matches invoice settlement');
      expect(row.textContent).not.toContain('✓');
      expect(row.textContent).not.toContain('✗');
    });

    it('renders no invented value beside it', () => {
      const c = renderWithFactors([{ label: 'pattern matches invoice settlement' }]);
      expect(c.textContent).not.toMatch(/corroborated/i);
    });
  });

  describe('a factor the agent DID classify', () => {
    it('renders ✗ for a flagged concern', () => {
      const c = renderWithFactors([{ label: 'aggregate above trigger', concern: true }]);
      expect(within(c).getByTestId('factor-row').textContent).toContain('✗');
    });

    it('renders ✓ only when explicitly not a concern', () => {
      const c = renderWithFactors([{ label: 'account history clean', concern: false }]);
      const text = within(c).getByTestId('factor-row').textContent || '';
      expect(text).toContain('✓');
      expect(text).not.toContain('✗');
    });
  });

  describe('the supervisor never answered', () => {
    const failed = [{ label: SUPERVISOR_UNAVAILABLE_FACTOR }];

    it('renders as an explicit failure, not as a factor', () => {
      const c = renderWithFactors(failed);
      const row = within(c).getByTestId('factor-unavailable');
      expect(row.textContent).toMatch(/did not return a usable opinion/i);
      expect(within(c).queryByTestId('factor-row')).not.toBeInTheDocument();
    });

    it('never shows a tick, a corroboration claim, or the raw token', () => {
      const c = renderWithFactors(failed);
      const row = within(c).getByTestId('factor-unavailable');
      expect(row.textContent).not.toContain('✓');
      expect(c.textContent).not.toMatch(/corroborated/i);
      expect(c.textContent).not.toContain(SUPERVISOR_UNAVAILABLE_FACTOR);
    });

    it('is never flagged as a divergence from the primary', () => {
      // It is not an opinion about the action, so it cannot diverge from one.
      const c = renderWithFactors(failed, [{ label: 'aggregate', concern: true }]);
      expect(c.textContent).not.toContain('DIVERGENT');
    });
  });

  describe('the divergence flag', () => {
    it('does not fire when the primary structurally has no factors', () => {
      // The defect: comparing against an always-empty set flagged EVERY supervisor
      // factor, on every run. An indicator that fires 100% of the time is noise.
      const c = renderWithFactors(
        [{ label: 'a' }, { label: 'b' }, { label: 'c' }],
        undefined
      );
      expect(c.textContent).not.toContain('DIVERGENT');
    });

    it('does not fire on the shipped demo approval, where the two agents merely word things differently', () => {
      cleanup();
      const view = render(
        <CopilotProvider offline>
          <ApprovalCard approval={demoApproval} streamStatus="live" />
        </CopilotProvider>
      );
      expect(view.container.textContent).not.toContain('DIVERGENT');
    });

    it('STILL fires when both agents genuinely stated factors and they differ', () => {
      // Anti-vacuous: proves the fix removed the false positives, not the feature.
      // Without this, deleting the indicator entirely would pass every test above.
      const c = renderWithFactors(
        [{ label: 'aggregate', concern: false }],
        [{ label: 'aggregate', concern: true }]
      );
      expect(c.textContent).toContain('DIVERGENT');
    });

    it('does not fire when both agents stated the same factors and agree', () => {
      const c = renderWithFactors(
        [{ label: 'aggregate', concern: true }],
        [{ label: 'aggregate', concern: true }]
      );
      expect(c.textContent).not.toContain('DIVERGENT');
    });
  });
});
