/**
 * The wire mapper's handling of `keyFactors`.
 *
 * This path used to be a CAST — `Array.isArray(x) ? x as AgentKeyFactor[]` —
 * which asserts a shape instead of checking one. That is part of how the demo
 * fixture taught the UI a `{label, value, concern}` measurement pair the service
 * has never produced: nothing on the wire path would have objected to any array
 * at all, including one of bare strings, which is the shape the deciders
 * actually hold factors in (`SecondOpinion.key_factors: tuple[str, ...]`).
 *
 * The distinction that matters most below: `concern` is TRI-state on the client
 * (`true` / `false` / not stated), so the mapper must never default it. A
 * defaulted `false` would let the card append a ✓ to a judgement no agent made.
 */

import { toApproval } from '../authorityWire';

function approvalWith(supervisorAssessment: Record<string, unknown>) {
  return toApproval({
    id: 'apr_1',
    status: 'pending',
    actionId: 'transaction.hold.place',
    actionLabel: 'Place hold',
    requesterId: 'usr_1',
    payload: { amount: 24500 },
    evidence: {},
    agentAssessment: {
      primary: { agentName: 'Primary agent', verdict: 'PROCEED' },
      supervisor: { agentName: 'Independent supervisor', ...supervisorAssessment },
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
}

const factorsOf = (supervisorAssessment: Record<string, unknown>) =>
  approvalWith(supervisorAssessment).assessments.find((a) => a.role === 'supervisor')!.keyFactors;

describe('toApproval — keyFactors', () => {
  it('finds a supervisor assessment at all (anti-vacuous guard)', () => {
    // Every assertion below reads through `.find(role === 'supervisor')`. If the
    // mapper stopped producing one, `factorsOf` would throw rather than quietly
    // returning undefined — but pin the positive case explicitly anyway.
    const assessments = approvalWith({ keyFactors: [{ label: 'a' }] }).assessments;
    expect(assessments.map((a) => a.role)).toEqual(['primary', 'supervisor']);
  });

  it('accepts the shape the service sends: a label and nothing else', () => {
    expect(factorsOf({ keyFactors: [{ label: 'counterparty is a freight vendor' }] })).toEqual([
      { label: 'counterparty is a freight vendor' },
    ]);
  });

  it('accepts a bare string, which is how a decider actually holds a factor', () => {
    expect(factorsOf({ keyFactors: ['pattern matches invoice settlement'] })).toEqual([
      { label: 'pattern matches invoice settlement' },
    ]);
  });

  it('never invents a value for a factor that has none', () => {
    const factors = factorsOf({ keyFactors: [{ label: 'a' }] })!;
    expect(factors[0].value).toBeUndefined();
    expect(JSON.stringify(factors)).not.toMatch(/corroborated/i);
  });

  it('never defaults `concern`, because absent and false mean different things', () => {
    // A defaulted `false` renders as a green tick on an unstated judgement.
    expect(factorsOf({ keyFactors: [{ label: 'a' }] })![0].concern).toBeUndefined();
    expect('concern' in factorsOf({ keyFactors: [{ label: 'a' }] })![0]).toBe(false);
  });

  it('preserves `concern` in both directions when the producer states it', () => {
    const factors = factorsOf({
      keyFactors: [
        { label: 'flagged', concern: true },
        { label: 'cleared', concern: false },
      ],
    })!;
    expect(factors[0].concern).toBe(true);
    expect(factors[1].concern).toBe(false);
  });

  it('preserves a genuine value', () => {
    expect(factorsOf({ keyFactors: [{ label: 'Aggregate', value: '$24,500 / 48h' }] })).toEqual([
      { label: 'Aggregate', value: '$24,500 / 48h' },
    ]);
  });

  it('drops entries that carry no usable label rather than rendering blanks', () => {
    expect(
      factorsOf({ keyFactors: [{ value: 'orphan' }, '', '   ', null, 42, { label: '  ' }] })
    ).toEqual([]);
  });

  it('is undefined when the field is absent or not a list', () => {
    expect(factorsOf({})).toBeUndefined();
    expect(factorsOf({ keyFactors: 'not a list' })).toBeUndefined();
  });
});
