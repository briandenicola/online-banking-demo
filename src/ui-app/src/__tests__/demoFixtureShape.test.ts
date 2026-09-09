/**
 * The demo fixture may not teach this UI a shape the service does not produce.
 *
 * THREE separate defects on this one card came from exactly that, and each was
 * written by somebody looking at the screen rather than at the wire:
 *
 *  1. `keyFactors: [{label: 'Aggregate', value: '$24,500 / 48h'}]` — a
 *     dimension-and-measurement pair the service has never once emitted. It
 *     taught the card a `value` column, which the service then filled with the
 *     constant "independently corroborated" to satisfy the type.
 *  2. Prose verdicts — "Recommend hold" / "Recommend release" — vocabulary no
 *     server verdict maps to, which on an adverse action read BACKWARDS.
 *  3. A primary `confidence: 0.81` that made the confidence comparison look
 *     exercised while it was, live, permanently dead.
 *
 * Every one of them passed every test, because the fixture agreed with the
 * RENDERER and the renderer agreed with the fixture. Nothing in that loop ever
 * consulted the service.
 *
 * So the loop is cut here: every assessment field the demo fixture carries must
 * also appear on the corresponding assessment in the regenerated golden wire
 * fixture, which is captured by driving the real planner.
 *
 * Deliberately ONE-DIRECTIONAL. The fixture may carry FEWER fields than the wire
 * — an assessment that omits something is honest, and a card that renders less
 * than it could is not a lie. It may never carry MORE. Inventing is the defect;
 * omitting is not.
 */

import golden from '../../../../tests/fixtures/copilot-wire-envelopes.json';
import { demoApproval } from '../components/copilot/demoFixture';
import { toApproval } from '../api/authorityWire';

interface RawEnvelope {
  kind: string;
  payload: { approval?: Record<string, unknown> };
}

const envelopes = golden as unknown as RawEnvelope[];

/** The golden approval carrying BOTH assessments, mapped through the real mapper. */
function goldenApproval() {
  const dual = envelopes.find((e) => {
    const aa = e.payload.approval?.agentAssessment as
      | { primary?: unknown; supervisor?: unknown }
      | undefined;
    return Boolean(aa?.primary && aa?.supervisor);
  });
  // Prove the haystack. If the golden fixture stopped carrying a two-assessment
  // approval, every comparison below would pass on an empty reference set — the
  // fixture would be free to invent again and this file would say nothing.
  expect(dual).toBeDefined();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return toApproval(dual!.payload.approval as any);
}

/** Keys actually populated — an `undefined` value is not a shape the wire taught. */
function populatedKeys(value: object): string[] {
  return Object.entries(value)
    .filter(([, v]) => v !== undefined)
    .map(([k]) => k)
    .sort();
}

describe('demoFixture is a subset of the shape the service really sends', () => {
  const wire = goldenApproval();

  it('the golden reference itself carries two real assessments (anti-vacuous guard)', () => {
    expect(wire.assessments.map((a) => a.role).sort()).toEqual(['primary', 'supervisor']);
    for (const assessment of wire.assessments) {
      expect(populatedKeys(assessment).length).toBeGreaterThan(3);
    }
    expect(demoApproval.assessments).toHaveLength(2);
  });

  for (const role of ['primary', 'supervisor'] as const) {
    it(`the demo ${role} assessment invents no field the wire does not carry`, () => {
      const demo = demoApproval.assessments.find((a) => a.role === role)!;
      const real = wire.assessments.find((a) => a.role === role)!;
      const invented = populatedKeys(demo).filter((k) => !populatedKeys(real).includes(k));
      expect(invented).toEqual([]);
    });

    it(`the demo ${role} key factors are flat statements, exactly as the wire's are`, () => {
      const demo = demoApproval.assessments.find((a) => a.role === role)!;
      for (const factor of demo.keyFactors || []) {
        // `value` is the fabricated field this whole file exists to keep out.
        // `concern` defaulted to false is a green tick on a judgement nobody
        // made — the same shape, one column over.
        expect(populatedKeys(factor)).toEqual(['label']);
      }
      for (const factor of wire.assessments.find((a) => a.role === role)!.keyFactors || []) {
        expect(populatedKeys(factor).filter((k) => k !== 'label')).toEqual([]);
      }
    });
  }

  it('the demo agreement state is one the server can actually send', () => {
    // A fixture with two assessments and no server-stated `agreement` is a shape
    // `fanout.py` cannot produce — it writes all three keys in one dict literal.
    expect(demoApproval.assessmentAgreement).toBeDefined();
    expect(wire.assessmentAgreement).toBeDefined();
  });

  it('the demo verdicts are in the server vocabulary, not invented prose', () => {
    for (const assessment of demoApproval.assessments) {
      expect(['proceed', 'hold', 'decline']).toContain((assessment.verdict || '').toLowerCase());
    }
  });
});
