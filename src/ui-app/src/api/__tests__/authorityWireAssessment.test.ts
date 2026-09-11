/**
 * The wire mapper's handling of a FAILED assessment, and of an absent number.
 *
 * Both cases below were found by tampering: the guards on the card were solid,
 * but nothing objected when the mapper THREW AWAY the inputs those guards read.
 * A card that renders `failure` correctly is worth nothing if the mapper never
 * carries `failure` across.
 *
 * The two shapes asserted here are the ones `approval_view.py` really writes:
 *
 *   - on failure it sets `wire["failure"]` and `wire["failureReason"]`, and
 *     OMITS `confidence` entirely (`primary_model.py`: "self_reported_confidence
 *     is ABSENT on failure, never 0.0. A zero is a claim.")
 *   - a verdict is likewise absent rather than defaulted to a mild one.
 *
 * So the mapper must carry the sentinel through, and must not invent a number
 * where the service deliberately sent none.
 */

import { toApproval } from '../authorityWire';

function primaryFrom(primary: Record<string, unknown>) {
  const approval = toApproval({
    id: 'apr_1',
    status: 'pending',
    actionId: 'transaction.hold.place',
    actionLabel: 'Place hold',
    requesterId: 'usr_1',
    payload: { amount: 24500 },
    evidence: {},
    agentAssessment: {
      primary: { agentName: 'Primary agent', ...primary },
      supervisor: { agentName: 'Independent supervisor', verdict: 'HOLD', confidence: 0.62 },
      agreement: 'not_comparable',
    },
    payloadHash: 'sha256:abc',
    payloadHashShort: 'abc',
    policyVersion: 'p1',
    policyId: 'pol_1',
    baseRung: 'L1',
    requiredRung: 'L2',
    requiredSigners: 2,
    signaturesCollected: 0,
    firedEscalators: [],
  } as never);
  return approval.assessments.find((a) => a.role === 'primary')!;
}

describe('toApproval — a failed assessment', () => {
  it('finds a primary assessment at all (anti-vacuous guard)', () => {
    expect(primaryFrom({ verdict: 'PROCEED' }).verdict).toBe('PROCEED');
  });

  it('CARRIES the failure sentinel across the wire, by name', () => {
    // Dropping this is invisible on a green suite unless something asserts it:
    // the card would fall back to "no verdict" and lose the ability to say WHY.
    const primary = primaryFrom({
      failure: 'primary_unavailable',
      failureReason: 'primary_mode_deterministic',
      rationale: 'No model-backed assessment was produced.',
    });
    expect(primary.failure).toBe('primary_unavailable');
    expect(primary.failureReason).toBe('primary_mode_deterministic');
  });

  it('carries the OTHER sentinel too — the two failures are not collapsed (§P4.1)', () => {
    const primary = primaryFrom({
      failure: 'primary_assessment_invalid',
      failureReason: 'primary_rationale_echoes_objective',
    });
    expect(primary.failure).toBe('primary_assessment_invalid');
    expect(primary.failureReason).toBe('primary_rationale_echoes_objective');
  });

  it('leaves the verdict ABSENT on failure rather than defaulting to a mild one', () => {
    expect(primaryFrom({ failure: 'primary_unavailable', failureReason: 'x' }).verdict).toBeUndefined();
  });
});

describe('toApproval — an absent self-reported confidence', () => {
  it('stays undefined, and is NOT defaulted to 0 (§P2.2)', () => {
    // `0` is not "no confidence"; it is a confident claim of no confidence, and
    // it renders as a number a banker can read authority into. The service omits
    // the key precisely so the client can omit the row.
    const primary = primaryFrom({ failure: 'primary_unavailable', failureReason: 'x' });
    expect(primary.selfReportedConfidence).toBeUndefined();
    expect(primary.selfReportedConfidence).not.toBe(0);
  });

  it('is still carried when the service DOES send one', () => {
    expect(primaryFrom({ verdict: 'PROCEED', confidence: 0.88 }).selfReportedConfidence).toBe(0.88);
  });

  it('does not invent one for an assessment that simply omits it', () => {
    expect(primaryFrom({ verdict: 'PROCEED' }).selfReportedConfidence).toBeUndefined();
  });
});
