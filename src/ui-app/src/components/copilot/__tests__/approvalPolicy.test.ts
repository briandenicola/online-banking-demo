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

describe('batch eligibility — L2 is structurally impossible', () => {
  const { batchableGroups, isBatchEligible } = require('../approvalPolicy');

  const mkL1 = (id: string, actionId = 'act_fee_reversal'): Approval => ({
    ...l1,
    id,
    actionId,
    actionLabel: 'Reverse a $12 fee',
    status: 'pending',
    requiredRung: 'L1',
    requiredSigners: 1,
    callerMaySign: true,
  });

  it('admits an L1 single-signer item the caller may sign', () => {
    expect(isBatchEligible(mkL1('a'))).toBe(true);
  });

  it('never admits an L2 item, however else it qualifies', () => {
    const l2: Approval = { ...mkL1('b'), requiredRung: 'L2', requiredSigners: 2 };
    expect(isBatchEligible(l2)).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Condition-isolating tests. The two guards (`requiredRung === 'L1'` and
  // `requiredSigners === 1`) protect L2 batching TOGETHER, and an aggregate
  // fixture that breaks both at once (the test above) stays green if either
  // guard is deleted — a false pass, and the exact erosion path this epic keeps
  // getting bitten by. The fixtures below are DELIBERATELY self-inconsistent:
  // an L2/one-signer approval and an L1/two-signer approval do not occur in the
  // wild. That inconsistency is the point — each makes ONE guard useless so the
  // OTHER guard is the only thing that can produce the expected `false`, which
  // is what pins it. DO NOT "fix" these fixtures into internal consistency: that
  // silently merges them back into the aggregate case and restores the hole.
  it('rejects an L2 rung on its own, even with a single required signer (pins the rung check)', () => {
    const rungOnly: Approval = { ...mkL1('rung'), requiredRung: 'L2', requiredSigners: 1 };
    // If the rung guard were deleted, `requiredSigners === 1` would pass this and
    // return true. Only the rung check can make it false.
    expect(isBatchEligible(rungOnly)).toBe(false);
  });

  it('rejects a two-signer requirement on its own, even at rung L1 (pins the signers check)', () => {
    const signersOnly: Approval = { ...mkL1('signers'), requiredRung: 'L1', requiredSigners: 2 };
    // If the signers guard were deleted, `requiredRung === 'L1'` would pass this
    // and return true. Only the signers check can make it false.
    expect(isBatchEligible(signersOnly)).toBe(false);
  });

  it('excludes a lone-guard L2 item from grouping too (batchableGroups re-filters, never trusts input)', () => {
    // Two clean L1 items plus one self-inconsistent L2/one-signer item. If
    // batchableGroups trusted its input, or if the rung guard were gone, the
    // tampered item would join the group. It must not.
    const approvals: Approval[] = [
      mkL1('a'),
      mkL1('b'),
      { ...mkL1('rung'), requiredRung: 'L2', requiredSigners: 1 },
    ];
    const groups = batchableGroups(approvals, 10, Date.now());
    expect(groups).toHaveLength(1);
    expect(groups[0].items.map((i: Approval) => i.id)).toEqual(['a', 'b']);
  });

  it('never admits an item the service says the caller may not sign', () => {
    expect(isBatchEligible({ ...mkL1('c'), callerMaySign: false })).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // The `callerMaySign` guard is the single most security-critical condition
  // here: it is the SERVER-supplied authorization gate, the one thing the client
  // is not allowed to decide for itself. The real code is `callerMaySign ===
  // true`, which differs from the tempting `!== false` on exactly one input:
  // undefined. A refactor to `!== false` fails OPEN — an approval whose
  // `callerMaySign` never arrived (older API, renamed field, partial DTO, a
  // serializer that omits nulls, a mapping layer that drops unknown keys) would
  // become batch-eligible and the banker would be shown a bulk-sign button for
  // approvals they may have no entitlement to sign. A missing field must NEVER
  // read as permission. The `delete` below removes the key entirely (not
  // `undefined`) so this survives a fixture-builder refactor that stops setting
  // it. The `Approval` type marks the field required; the WIRE is not bound by
  // our TypeScript, so we cast at this boundary to model what the DTO can
  // actually carry.
  it('never admits an item whose callerMaySign is absent — a missing gate is not consent', () => {
    const noGate = { ...mkL1('nogate') } as Partial<Approval>;
    delete noGate.callerMaySign;
    expect(isBatchEligible(noGate as Approval)).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Status guard. The real code is a positive allow-list of the two OPEN,
  // awaiting-signature states (`pending`, `proposed`) — not a `!== 'denied'`
  // deny-list. That shape matters: a status added to the lifecycle later, or a
  // terminal one, falls OUTSIDE the allow-list and is rejected (fails closed)
  // rather than sliding into a batch. These pin that a terminal approval —
  // already signed, or already executed — can never enter a bulk-sign group.
  it('never admits an already-signed approval (terminal status fails closed)', () => {
    expect(isBatchEligible({ ...mkL1('signed'), status: 'signed' })).toBe(false);
  });

  it('never admits an already-executed approval (terminal status fails closed)', () => {
    expect(isBatchEligible({ ...mkL1('executed'), status: 'executed' })).toBe(false);
  });

  it('groups only same-action L1 items and yields no L2 group', () => {
    const approvals: Approval[] = [
      mkL1('a', 'act_fee_reversal'),
      mkL1('b', 'act_fee_reversal'),
      mkL1('c', 'act_fee_reversal'),
      { ...mkL1('d', 'act_fee_reversal'), requiredRung: 'L2', requiredSigners: 2 },
      mkL1('e', 'act_other'), // only one of this action → not a batch
    ];
    const groups = batchableGroups(approvals, 10, Date.now());
    expect(groups).toHaveLength(1);
    expect(groups[0].actionId).toBe('act_fee_reversal');
    expect(groups[0].items).toHaveLength(3);
    // The L2 item never appears in any group.
    const allIds = groups.flatMap((g: { items: Approval[] }) => g.items.map((i) => i.id));
    expect(allIds).not.toContain('d');
  });

  it('enforces the cap as a hard slice', () => {
    const many = Array.from({ length: 15 }, (_, i) => mkL1(`x${i}`));
    const groups = batchableGroups(many, 10, Date.now());
    expect(groups[0].items).toHaveLength(10);
  });

  it('does not offer a batch of one', () => {
    expect(batchableGroups([mkL1('solo')], 10, Date.now())).toHaveLength(0);
  });
});

describe('denialCountsByReason — never one undifferentiated total', () => {
  const { denialCountsByReason } = require('../approvalPolicy');

  const denied = (id: string, reason: string): Approval => ({
    ...l1,
    id,
    status: 'denied',
    terminalReason: reason as Approval['terminalReason'],
  });

  it('keeps a policy void separate from a human denial', () => {
    const breakdown = denialCountsByReason([
      denied('a', 'HUMAN_DENIED'),
      denied('b', 'POLICY_RUNG_ESCALATED'),
      denied('c', 'PAYLOAD_SUPERSEDED'),
      denied('d', 'TTL_EXPIRED'),
      denied('e', 'HUMAN_DENIED'),
    ]);
    expect(breakdown.byReason.HUMAN_DENIED).toBe(2);
    expect(breakdown.byReason.POLICY_RUNG_ESCALATED).toBe(1);
    // Only human denials are evidence about the agent.
    expect(breakdown.humanDenied).toBe(2);
    // The other three are the ground moving, grouped away from human denial.
    expect(breakdown.systemVoided).toBe(3);
  });

  it('ignores non-terminal approvals', () => {
    const breakdown = denialCountsByReason([{ ...l1, status: 'pending' }]);
    expect(breakdown.total).toBe(0);
  });
});
