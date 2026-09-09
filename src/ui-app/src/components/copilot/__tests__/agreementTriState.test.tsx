/**
 * The three states of agreement, and the blank-verdict state, RENDERED.
 *
 * The pure functions are tested in `approvalPolicy.test.ts`. These exist because
 * every defect this card has shipped was only ever visible in the DOM: a verdict
 * renamed by a lookup, a tick appended by a ternary, a constant printed into a
 * value column. The rule this file enforces is one sentence:
 *
 *     A dead pipeline must never be able to display as consensus, and must not
 *     display as a mild verdict either.
 *
 * That is the original defect ("Independent review reached the same verdict" over
 * two ABSENT verdicts) and the one behind it (`decline` falling through to
 * "CONDITIONAL", the mildest word available) — the same bug, one level apart.
 */

import React from 'react';
import { cleanup, render, within } from '@testing-library/react';
import ApprovalCard from '../ApprovalCard';
import { CopilotProvider } from '../CopilotContext';
import { demoApproval } from '../demoFixture';
import { AgentAssessment, AgreementState, Approval } from '../types';

function renderCard(
  primary: Partial<AgentAssessment>,
  supervisor: Partial<AgentAssessment> | null,
  agreement: AgreementState | undefined
): HTMLElement {
  cleanup();
  const assessments: AgentAssessment[] = [{ ...demoApproval.assessments[0], ...primary }];
  if (supervisor) assessments.push({ ...demoApproval.assessments[1], ...supervisor });
  const approval: Approval = { ...demoApproval, assessments, assessmentAgreement: agreement };
  return render(
    <CopilotProvider offline>
      <ApprovalCard approval={approval} streamStatus="live" />
    </CopilotProvider>
  ).container;
}

/** The failed primary exactly as `primary_model.unavailable` puts it on the wire. */
const DETERMINISTIC_PRIMARY: Partial<AgentAssessment> = {
  verdict: undefined,
  selfReportedConfidence: undefined,
  keyFactors: undefined,
  failure: 'primary_unavailable',
  failureReason: 'primary_mode_deterministic',
  rationale:
    'The primary agent did not return an assessment (the planner is running in deterministic mode, so no model was consulted). No judgement was formed on this action by the proposing agent, so nothing on this card is the primary\'s position.',
};

afterEach(cleanup);

describe('the agreement banner is tri-state on screen', () => {
  it('renders three DISTINCT banners for agree / diverge / not_comparable', () => {
    const seen = new Map<string, string>();
    const cases: AgreementState[] = ['agree', 'diverge', 'not_comparable'];
    for (const state of cases) {
      const c = renderCard(
        state === 'not_comparable' ? DETERMINISTIC_PRIMARY : { verdict: 'proceed' },
        { verdict: state === 'agree' ? 'proceed' : 'hold' },
        state
      );
      const banner = within(c).getByTestId('agreement-banner');
      expect(banner.getAttribute('data-agreement')).toBe(state);
      seen.set(state, banner.textContent || '');
    }
    // Distinct text, not merely a distinct attribute. A `data-` attribute nobody
    // renders is a guard that only a test can see.
    expect(new Set(seen.values()).size).toBe(3);
  });

  it('says CONSENSUS only when the server stated agreement', () => {
    const agreed = renderCard({ verdict: 'proceed' }, { verdict: 'proceed' }, 'agree');
    expect(within(agreed).getByTestId('agreement-banner').textContent).toMatch(/same verdict/i);
  });

  it('NEVER says consensus when the primary has no position', () => {
    // The exact sentence, over the exact condition, that made this whole thread
    // of work necessary.
    const c = renderCard(DETERMINISTIC_PRIMARY, { verdict: 'hold' }, 'not_comparable');
    const banner = within(c).getByTestId('agreement-banner');
    // The dangerous readings, named individually. A blanket /agree/i would also
    // reject the honest sentence "neither agreement nor dissent", and a test that
    // forbids the correct wording gets loosened until it forbids nothing.
    expect(banner.textContent).not.toMatch(/same verdict/i);
    expect(banner.textContent).not.toMatch(/\bagrees?\b/i);
    expect(banner.textContent).not.toMatch(/reached the same/i);
    expect(banner.textContent).toMatch(/NOT INDEPENDENTLY REVIEWED/);
    expect(banner.textContent).toMatch(/neither agreement nor dissent/i);
  });

  it('NEVER says consensus when the server stated nothing at all', () => {
    // A UI running ahead of the service. It must fail towards "unreviewed".
    const c = renderCard({ verdict: 'proceed' }, { verdict: 'proceed' }, undefined);
    const banner = within(c).getByTestId('agreement-banner');
    expect(banner.getAttribute('data-agreement')).toBe('not_comparable');
    expect(banner.textContent).not.toMatch(/same verdict/i);
  });

  it('does not report dissent when one side simply never answered', () => {
    // The mirror error, and the one Livingston had to correct by hand in the
    // corpus: a failed call counted as disagreement inflates the dissent rate
    // that check 4.2 reports.
    const c = renderCard(DETERMINISTIC_PRIMARY, { verdict: 'hold' }, 'not_comparable');
    expect(within(c).getByTestId('agreement-banner').textContent).not.toMatch(/DISAGREE/);
  });
});

describe('the blank-verdict state names itself', () => {
  it('states the failure sentinel and its reason, by name', () => {
    const c = renderCard(DETERMINISTIC_PRIMARY, { verdict: 'hold' }, 'not_comparable');
    const failure = within(c).getByTestId('assessment-failure-primary');
    expect(failure.textContent).toContain('primary_unavailable');
    expect(failure.textContent).toContain('primary_mode_deterministic');
    expect(failure.textContent).toMatch(/NO ASSESSMENT WAS FORMED/);
  });

  it('cannot be mistaken for a mild or neutral verdict', () => {
    const c = renderCard(DETERMINISTIC_PRIMARY, { verdict: 'hold' }, 'not_comparable');
    const chip = within(c).getByTestId('verdict-chip-primary');
    expect(chip.textContent).toBe('NO VERDICT');
    // Not the mildest thing on the screen. The original defect put the STRONGEST
    // objection on the MILDEST label; an absent one must not land there either.
    expect(chip.getAttribute('data-verdict-color')).toBe('error');
    expect(Number(chip.getAttribute('data-verdict-severity'))).toBeGreaterThan(
      Number(
        within(renderCard({ verdict: 'decline' }, { verdict: 'hold' }, 'diverge'))
          .getByTestId('verdict-chip-primary')
          .getAttribute('data-verdict-severity')
      )
    );
  });

  it('shows no confidence number for an assessment that was never formed', () => {
    // §P4.1: absent, never 0.0. A sentinel zero would render as a real
    // self-reported confidence of 0.00 and could be averaged into a statistic.
    const c = renderCard(DETERMINISTIC_PRIMARY, { verdict: 'hold' }, 'not_comparable');
    expect(within(c).queryByTestId('self-reported-confidence-primary')).toBeNull();
  });

  it('distinguishes a failed reply from an unreachable model, by sentinel', () => {
    const invalid = renderCard(
      { ...DETERMINISTIC_PRIMARY, failure: 'primary_assessment_invalid', failureReason: 'primary_rationale_echoes_objective' },
      { verdict: 'hold' },
      'not_comparable'
    );
    const text = within(invalid).getByTestId('assessment-failure-primary').textContent || '';
    expect(text).toContain('primary_assessment_invalid');
    expect(text).not.toContain('primary_unavailable');
  });
});

describe('self-reported confidence is prose, and ranks nothing', () => {
  it('is labelled for what it is, wherever it appears', () => {
    const c = renderCard({ verdict: 'proceed' }, { verdict: 'hold' }, 'diverge');
    const shown = within(c).getByTestId('self-reported-confidence-primary');
    expect(shown.textContent).toMatch(/self-reported confidence/i);
    // The caveat travels with the number in the accessible name, because a
    // tooltip does not survive being copied into a screenshot.
    expect(shown.getAttribute('aria-label')).toMatch(/not a reliability measure/i);
  });

  it('renders no progress bar or other proportional scale', () => {
    // `ConfidenceBar` drew a LinearProgress whose stated purpose was making the
    // two numbers comparable at a glance. Measured 0.83-0.98 with no separation
    // between a stable case and a coin flip, so the comparison it invited was
    // not one the number supports.
    const c = renderCard({ verdict: 'proceed' }, { verdict: 'hold' }, 'diverge');
    expect(c.querySelectorAll('.MuiLinearProgress-root')).toHaveLength(0);
    expect(c.querySelectorAll('[role="progressbar"]')).toHaveLength(0);
  });

  it('does not change what the card reveals when confidence is low', () => {
    // The deleted gate: `lowestConfidence < 0.75` forced the evidence panel open,
    // i.e. something was revealed because a number crossed a line. Two renders
    // that differ ONLY in confidence must show the same evidence disclosure.
    const high = renderCard(
      { verdict: 'proceed', selfReportedConfidence: 0.98 },
      { verdict: 'proceed', selfReportedConfidence: 0.97 },
      'agree'
    ).textContent;
    const low = renderCard(
      { verdict: 'proceed', selfReportedConfidence: 0.05 },
      { verdict: 'proceed', selfReportedConfidence: 0.04 },
      'agree'
    ).textContent;
    const strip = (t: string | null) => (t || '').replace(/0\.\d+/g, '');
    expect(strip(low)).toBe(strip(high));
  });
});

describe('attribution is disclosed (§P7.1)', () => {
  it('names the mode and the model, so a script cannot pass for a judgement', () => {
    const c = renderCard({ verdict: 'proceed' }, { verdict: 'hold' }, 'diverge');
    const attribution = within(c).getByTestId('assessment-attribution-primary');
    expect(attribution.textContent).toContain('mode foundry');
    expect(attribution.textContent).toContain('gpt-4o-banker');
  });

  it('shows nothing at all rather than a placeholder when the service sent none', () => {
    const c = renderCard(
      { verdict: 'proceed', mode: undefined, modelDeployment: undefined, promptSha256: undefined, responseSha256: undefined },
      { verdict: 'hold' },
      'diverge'
    );
    expect(within(c).queryByTestId('assessment-attribution-primary')).toBeNull();
  });
});
