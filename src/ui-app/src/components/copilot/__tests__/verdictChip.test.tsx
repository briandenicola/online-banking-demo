/**
 * The chip is where the verdict is finally READ by a human, so the guard has to
 * live at the rendered DOM, not only at the pure function.
 *
 * The defect this pins: `decline` — the strongest objection a supervisor can
 * make — rendered as "CONDITIONAL" in amber, and `hold` rendered as "DECLINE"
 * in red. Check 4.2 ("does the supervisor ever genuinely disagree?") is answered
 * by looking at this chip, so a mislabelled verdict does not merely look wrong,
 * it corrupts the measurement.
 *
 * Anti-vacuity: a fixture per verdict, driven through the REAL card, asserting a
 * SPECIFIC label and a SPECIFIC colour. A suite carrying one verdict cannot
 * notice two verdicts colliding on the same label.
 */

import React from 'react';
import { cleanup, render, within } from '@testing-library/react';
import ApprovalCard from '../ApprovalCard';
import { CopilotProvider } from '../CopilotContext';
import { demoApproval } from '../demoFixture';
import { Approval } from '../types';

function cardWithSupervisorVerdict(verdict: string | undefined): Approval {
  return {
    ...demoApproval,
    assessments: [
      { ...demoApproval.assessments[0], verdict: 'proceed' },
      { ...demoApproval.assessments[1], verdict },
    ],
  };
}

function renderWith(verdict: string | undefined) {
  // RTL's bound queries search `document.body`, so a second render inside one test
  // would match two chips. Unmount first: each case is about ONE verdict's chip.
  cleanup();
  const view = render(
    <CopilotProvider offline>
      <ApprovalCard approval={cardWithSupervisorVerdict(verdict)} streamStatus="live" />
    </CopilotProvider>
  );
  return within(view.container).getByTestId('verdict-chip-supervisor');
}

// Expected values written out literally, transcribed from the server's own
// vocabulary — not read back from the module that produces them.
const CASES = [
  { verdict: 'proceed', label: 'PROCEED', color: 'success' },
  { verdict: 'hold', label: 'HOLD', color: 'warning' },
  { verdict: 'decline', label: 'DECLINE', color: 'error' },
] as const;

describe('the supervisor verdict chip', () => {
  it('the demo fixture itself carries a real disagreement in real vocabulary', () => {
    // Anti-vacuous: if the shipped fixture drifted back to prose verdicts, every
    // case below would still pass while the actual demo screen lied.
    expect(demoApproval.assessments[0].verdict).toBe('proceed');
    expect(demoApproval.assessments[1].verdict).toBe('decline');
  });

  describe.each(CASES)('$verdict', ({ verdict, label, color }) => {
    it(`shows the label "${label}"`, () => {
      expect(within(renderWith(verdict)).getByText(label)).toBeInTheDocument();
    });

    it(`shows it in "${color}"`, () => {
      expect(renderWith(verdict)).toHaveAttribute('data-verdict-color', color);
    });

    it('shows no other verdict label alongside it', () => {
      const chip = renderWith(verdict);
      for (const other of CASES.filter((c) => c.label !== label)) {
        expect(within(chip).queryByText(other.label)).not.toBeInTheDocument();
      }
    });
  });

  it('never renders a label the server cannot emit', () => {
    for (const { verdict } of CASES) {
      const chip = renderWith(verdict);
      expect(chip.textContent).not.toMatch(/APPROVE|CONDITIONAL/);
    }
  });

  it('renders `decline` louder than `hold`, not milder', () => {
    const declineSeverity = Number(renderWith('decline').dataset.verdictSeverity);
    const holdSeverity = Number(renderWith('hold').dataset.verdictSeverity);
    const proceedSeverity = Number(renderWith('proceed').dataset.verdictSeverity);
    expect(proceedSeverity).toBeLessThan(holdSeverity);
    expect(holdSeverity).toBeLessThan(declineSeverity);
  });

  describe('a verdict the UI has no case for', () => {
    it('is visibly distinct and not mistaken for a real verdict', () => {
      const chip = renderWith('CONDITIONAL');
      expect(within(chip).getByText('UNRECOGNISED VERDICT')).toBeInTheDocument();
      expect(chip.textContent).not.toMatch(/^(PROCEED|HOLD|DECLINE)$/);
    });

    it('is never rendered in the mildest colour', () => {
      expect(renderWith('whatever')).toHaveAttribute('data-verdict-color', 'error');
    });

    it('outranks every real verdict so it can never be read as the mildest', () => {
      expect(Number(renderWith('whatever').dataset.verdictSeverity)).toBeGreaterThan(
        Number(renderWith('decline').dataset.verdictSeverity)
      );
    });
  });

  describe('a missing verdict', () => {
    it('says so explicitly rather than rendering an empty or mild chip', () => {
      const chip = renderWith(undefined);
      expect(within(chip).getByText('NO VERDICT')).toBeInTheDocument();
      expect(chip).toHaveAttribute('data-verdict-color', 'error');
    });
  });
});
