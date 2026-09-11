/**
 * What the signing banner tells a person they are about to do.
 *
 * The defect this pins: the attestation branched on `isL2` ALONE. It never
 * consulted which signature slot the caller would fill, nor whether the caller
 * was the requester. So every L2 signer was told they were "providing the
 * independent supervisor co-signature ... because you are a different identity
 * from the requester (banker)" — while signed in AS banker, on banker's own
 * request. False for the opening signer, and self-contradictory for the
 * requester.
 *
 * The truth lives in the slots, not the rung: whether a signature OPENS an
 * approval or CLOSES it is a property of how many remain.
 *
 * Verified against the live `banker` payload before writing any of this: slot 0
 * carries `minSeniority: 1` and an empty `mustDifferFrom` (the opening
 * signature, which the requester may legitimately provide), while slot 1 carries
 * `minSeniority: 2` and `mustDifferFrom: [<requester id>]`. The service returns
 * `callerMaySign: true` for the requester only while the opening slot is still
 * empty, and flips to false with "you cannot also approve it" once they have
 * filled it. The eligibility logic is CORRECT — this was only ever a copy bug.
 */

import { signingAttestation } from '../ApprovalCard';
import { Approval, SignatureSlot } from '../types';
import { demoApproval } from '../demoFixture';

function slot(over: Partial<SignatureSlot> & { ordinal: number }): SignatureSlot {
  return { minSeniority: 1, mustDifferFrom: [], filled: false, ...over };
}

function withSlots(slots: SignatureSlot[], over: Partial<Approval> = {}): Approval {
  return { ...demoApproval, signatureSlots: slots, requiredSigners: slots.length, ...over };
}

describe('signingAttestation', () => {
  it('tells a single signer that theirs is the only signature', () => {
    const text = signingAttestation(withSlots([slot({ ordinal: 0 })]), 'a.reyes');
    expect(text).toMatch(/only signature/i);
    expect(text).not.toMatch(/second/i);
  });

  it('tells the requester they are signing first, and that the other signer cannot be them', () => {
    const approval = withSlots(
      [slot({ ordinal: 0 }), slot({ ordinal: 1, minSeniority: 2, mustDifferFrom: ['uid-banker'] })],
      { requesterUsername: 'banker' }
    );
    const text = signingAttestation(approval, 'banker');

    expect(text).toMatch(/signing it first/i);
    expect(text).toMatch(/cannot be you/i);
    // The contradiction that started this: never claim the requester is not the
    // requester.
    expect(text).not.toMatch(/different identity from the requester/i);
  });

  it('does not claim a non-requester raised the request', () => {
    const approval = withSlots(
      [slot({ ordinal: 0 }), slot({ ordinal: 1, minSeniority: 2, mustDifferFrom: ['uid-banker'] })],
      { requesterUsername: 'banker' }
    );
    const text = signingAttestation(approval, 'a.reyes');

    expect(text).toMatch(/signing first/i);
    expect(text).not.toMatch(/you raised this request/i);
  });

  it('tells the closing signer who went before them and that they release it', () => {
    const approval = withSlots(
      [
        slot({ ordinal: 0, filled: true, signedByUsername: 'banker' }),
        slot({ ordinal: 1, minSeniority: 2, mustDifferFrom: ['uid-banker'] }),
      ],
      { requesterUsername: 'banker' }
    );
    const text = signingAttestation(approval, 'supervisor');

    expect(text).toMatch(/second signature/i);
    expect(text).toMatch(/banker signed first/i);
    expect(text).toMatch(/goes ahead/i);
  });

  it('does not invent a first signer when the record does not name one', () => {
    const approval = withSlots([
      slot({ ordinal: 0, filled: true }),
      slot({ ordinal: 1, minSeniority: 2 }),
    ]);
    const text = signingAttestation(approval, 'supervisor');

    expect(text).toMatch(/second signature/i);
    expect(text).not.toMatch(/signed first/i);
  });

  it('counts the people still needed when more than one signature remains', () => {
    const approval = withSlots([
      slot({ ordinal: 0 }),
      slot({ ordinal: 1, minSeniority: 2 }),
      slot({ ordinal: 2, minSeniority: 2 }),
    ]);
    expect(signingAttestation(approval, 'a.reyes')).toMatch(/2 more people sign/i);
  });

  it('reads the slots by state, not by ordinal number', () => {
    // The demo fixture numbers its slots 1 and 2, so anything keyed off
    // `ordinal === 0` silently mislabels every card built from it.
    const approval = withSlots([
      slot({ ordinal: 1, filled: true, signedByUsername: 'j.okafor' }),
      slot({ ordinal: 2, minSeniority: 2 }),
    ]);
    expect(signingAttestation(approval, 'a.reyes')).toMatch(/second signature/i);
  });

  it('falls back to neutral wording when the identity cannot be matched', () => {
    const approval = withSlots([slot({ ordinal: 0 }), slot({ ordinal: 1, minSeniority: 2 })], {
      requesterUsername: 'banker',
    });
    // No identity id at all. Failing to the wording that is true either way beats
    // guessing.
    const text = signingAttestation(approval, undefined);
    expect(text).toMatch(/signing first/i);
    expect(text).not.toMatch(/you raised this request/i);
  });

  it('speaks plainly — no policy-engine vocabulary', () => {
    const cases = [
      signingAttestation(withSlots([slot({ ordinal: 0 })]), 'banker'),
      signingAttestation(
        withSlots([slot({ ordinal: 0 }), slot({ ordinal: 1, minSeniority: 2 })], {
          requesterUsername: 'banker',
        }),
        'banker'
      ),
      signingAttestation(
        withSlots([
          slot({ ordinal: 0, filled: true, signedByUsername: 'banker' }),
          slot({ ordinal: 1, minSeniority: 2 }),
        ]),
        'supervisor'
      ),
    ];
    cases.forEach((text) => {
      expect(text).not.toMatch(/co-signature|seniority|rung|L1|L2|dual control|separation of duties/i);
      expect(text.length).toBeGreaterThan(0);
    });
  });
});
