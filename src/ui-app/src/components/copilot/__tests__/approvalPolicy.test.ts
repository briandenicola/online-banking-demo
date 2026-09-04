/**
 * Approval-policy tests.
 *
 * This is the part of the surface where the invariant "agents never approve"
 * either holds or quietly stops holding, so it gets the closest tests in the
 * lane. Two properties matter above all:
 *
 *  1. all four terminal reasons render as DISTINCT copy — a policy-driven void
 *     must never look like a colleague rejecting your work
 *  2. dwell scales with consequence, and no configuration can take it to zero
 */

import {
  countMaterialChanges,
  diffPayloads,
  disagreementOf,
  dwellRequirementMs,
  isReversible,
  shouldSpotCheck,
  terminalCopy,
  validateReason,
} from '../approvalPolicy';
import { demoApproval } from '../demoFixture';
import { getCopilotConfig, resetCopilotConfig } from '../../../config/copilotConfig';
import { Approval, PayloadField, TERMINAL_REASONS } from '../types';

const l1: Approval = {
  ...demoApproval,
  id: 'apr_l1',
  requiredRung: 'L1',
  requiredSigners: 1,
  assessments: [demoApproval.assessments[0]],
  firedEscalators: [],
};

describe('terminalCopy', () => {
  it('produces distinct copy for every terminal reason', () => {
    const badges = TERMINAL_REASONS.map((reason) => terminalCopy(reason).badge);
    expect(new Set(badges).size).toBe(TERMINAL_REASONS.length);
  });

  it('never renders a bare "Denied" for a non-human cause', () => {
    // A banker told "Denied" for a TTL expiry will go and ask a colleague why
    // they rejected it. The copy must name the cause.
    ['POLICY_RUNG_ESCALATED', 'PAYLOAD_SUPERSEDED', 'TTL_EXPIRED'].forEach((reason) => {
      const copy = terminalCopy(reason as never);
      expect(copy.badge.toUpperCase()).not.toBe('DENIED');
      expect(copy.blameless).toBe(true);
    });
    expect(terminalCopy('HUMAN_DENIED').blameless).toBe(false);
  });

  it('answers "did something half-happen?" for every reason', () => {
    // The first question anyone asks about a failed approval. Every branch
    // answers it explicitly rather than leaving it to be inferred.
    TERMINAL_REASONS.forEach((reason) => {
      const copy = terminalCopy(reason);
      expect(`${copy.body} ${copy.headline}`.toLowerCase()).toContain('executed');
    });
  });
});

describe('dwellRequirementMs', () => {
  beforeEach(() => resetCopilotConfig());

  it('scales with consequence', () => {
    const config = getCopilotConfig();

    const l1Irreversible = dwellRequirementMs({
      approval: l1,
      disagreement: 'none',
      supersedes: false,
    });
    const l2Agree = dwellRequirementMs({
      approval: demoApproval,
      disagreement: 'none',
      supersedes: false,
    });
    const l2Disagree = dwellRequirementMs({
      approval: demoApproval,
      disagreement: 'verdict',
      supersedes: false,
    });

    expect(l1Irreversible).toBe(config.dwellMs.l1Irreversible);
    expect(l2Agree).toBeGreaterThan(l1Irreversible);
    expect(l2Disagree).toBeGreaterThan(l2Agree);
  });

  it('gives no credit for having read a superseded payload', () => {
    const fresh = dwellRequirementMs({
      approval: demoApproval,
      disagreement: 'verdict',
      supersedes: false,
    });
    const resuperseded = dwellRequirementMs({
      approval: demoApproval,
      disagreement: 'verdict',
      supersedes: true,
    });
    expect(resuperseded).toBeGreaterThanOrEqual(fresh);
  });

  it('cannot be configured to zero', () => {
    // A knob that can empty an anti-fatigue control is a bypass, not a knob.
    (window as unknown as { __RUNTIME_CONFIG__: unknown }).__RUNTIME_CONFIG__ = {
      copilot: { dwellMs: { l1Reversible: 0, l1Irreversible: 0, l2Agree: 0, l2Disagree: 0 } },
    };
    resetCopilotConfig();

    expect(
      dwellRequirementMs({ approval: demoApproval, disagreement: 'none', supersedes: false })
    ).toBeGreaterThan(0);
    expect(
      dwellRequirementMs({ approval: l1, disagreement: 'none', supersedes: false })
    ).toBeGreaterThan(0);

    delete (window as unknown as { __RUNTIME_CONFIG__?: unknown }).__RUNTIME_CONFIG__;
    resetCopilotConfig();
  });
});

describe('isReversible', () => {
  it('defaults to irreversible when the payload is silent', () => {
    // The conservative default is the whole point: assuming "probably
    // reversible" applies the least friction to the items we know least about.
    expect(isReversible(demoApproval)).toBe(false);
  });

  it('honours an explicit reversible flag', () => {
    const reversible: Approval = {
      ...demoApproval,
      payload: [
        ...demoApproval.payload,
        { path: 'reversible', label: 'Reversible', value: true },
      ],
    };
    expect(isReversible(reversible)).toBe(true);
  });
});

describe('disagreementOf', () => {
  it('detects opposite verdicts', () => {
    const result = disagreementOf(demoApproval.assessments);
    expect(result.kind).not.toBe('none');
    expect(result.summary).toContain('Supervisor');
  });

  it('reports none when there is no supervisor opinion', () => {
    expect(disagreementOf([demoApproval.assessments[0]]).kind).toBe('none');
  });
});

describe('validateReason', () => {
  beforeEach(() => resetCopilotConfig());

  it('rejects short input', () => {
    expect(validateReason('too short').valid).toBe(false);
  });

  it('rejects low-entropy padding', () => {
    expect(validateReason('aaaaaaaaaaaaaaaaaaaaaaaa').valid).toBe(false);
    expect(validateReason('                            ').valid).toBe(false);
  });

  it('accepts a genuine reason', () => {
    expect(
      validateReason('Customer confirmed these are scheduled vendor payments; releasing the hold.')
        .valid
    ).toBe(true);
  });
});

describe('shouldSpotCheck', () => {
  it('is deterministic per approval', () => {
    // A check that reshuffles on every render would let a banker click Sign
    // twice and get a different gate. The decision is a pure function of the id.
    const first = shouldSpotCheck('apr_stable_id', 0.5);
    for (let i = 0; i < 20; i += 1) {
      expect(shouldSpotCheck('apr_stable_id', 0.5)).toBe(first);
    }
  });

  it('is off at rate zero and on at rate one', () => {
    expect(shouldSpotCheck('apr_any', 0)).toBe(false);
    expect(shouldSpotCheck('apr_any', 1)).toBe(true);
  });
});

describe('diffPayloads', () => {
  it('flags material changes in a re-proposed payload', () => {
    const before: PayloadField[] = demoApproval.payload;
    const after: PayloadField[] = demoApproval.payload.map((field) =>
      field.path === 'amount' ? { ...field, value: 31000 } : field
    );

    const rows = diffPayloads(before, after);
    const changed = rows.filter((row) => row.kind === 'changed');
    expect(changed).toHaveLength(1);
    expect(changed[0].path).toBe('amount');
    expect(countMaterialChanges(rows)).toBe(1);
  });

  it('reports no changes for an identical payload', () => {
    const rows = diffPayloads(demoApproval.payload, demoApproval.payload);
    expect(countMaterialChanges(rows)).toBe(0);
  });
});
