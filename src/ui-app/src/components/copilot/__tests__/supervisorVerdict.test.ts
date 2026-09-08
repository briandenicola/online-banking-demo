/**
 * Guards for the verdict presentation seam.
 *
 * What went wrong before: `decline` rendered as "CONDITIONAL" and `hold` as
 * "DECLINE", so the strongest objection a supervisor can make read as the
 * mildest, and vice versa. The existing suite did not catch it because nothing
 * asserted a SPECIFIC label against a SPECIFIC verdict — the fixtures carried
 * one verdict and the test only proved that some chip rendered.
 *
 * So this file is deliberately built to avoid two ways of proving less than it
 * appears to:
 *
 *  1. ONE FIXTURE PER VERDICT, plus an unknown one and a missing one. A suite
 *     that only ever feeds `decline` cannot notice that `hold` collides with it.
 *  2. LABEL AND COLOUR ASSERTED FROM AN INDEPENDENT TABLE, verdict by verdict,
 *     with literal expected values written out here. They come from one lookup
 *     in the implementation, so a table that was itself derived from that lookup
 *     would break and pass together. The values below are transcribed from the
 *     server's semantics, not imported from the module under test.
 */

import {
  SERVER_VERDICTS,
  UNRECOGNISED_SEVERITY,
  normaliseVerdict,
  verdictPresentation,
} from '../supervisorVerdict';

// Transcribed by hand from supervisor_model.py's _INSTRUCTIONS. Not derived from
// the implementation, so a wrong entry there cannot silently agree with this.
const EXPECTED = [
  { verdict: 'proceed', label: 'PROCEED', color: 'success', severity: 0 },
  { verdict: 'hold', label: 'HOLD', color: 'warning', severity: 1 },
  { verdict: 'decline', label: 'DECLINE', color: 'error', severity: 2 },
] as const;

describe('supervisor verdict presentation', () => {
  it('covers exactly the server vocabulary — no more, no less (anti-vacuous guard)', () => {
    // If the server grows a fourth verdict and this list is not updated, the
    // per-verdict cases below would silently stop covering it.
    expect([...SERVER_VERDICTS]).toEqual(['proceed', 'hold', 'decline']);
    expect(EXPECTED.map((e) => e.verdict)).toEqual([...SERVER_VERDICTS]);
  });

  describe.each(EXPECTED)('$verdict', ({ verdict, label, color, severity }) => {
    it(`renders the label "${label}"`, () => {
      expect(verdictPresentation(verdict).label).toBe(label);
    });

    it(`renders the colour "${color}"`, () => {
      expect(verdictPresentation(verdict).color).toBe(color);
    });

    it(`ranks at severity ${severity}`, () => {
      expect(verdictPresentation(verdict).severity).toBe(severity);
    });

    it('is marked known and normalises to its own token', () => {
      const p = verdictPresentation(verdict);
      expect(p.known).toBe(true);
      expect(p.verdict).toBe(verdict);
      expect(p.variant).toBe('filled');
    });
  });

  it('never labels a verdict with vocabulary the server cannot emit', () => {
    // The two invented labels. "APPROVE" maps to no recommendation and violates
    // the card's own rule that agents propose but never approve; "CONDITIONAL"
    // was the default arm that swallowed `decline`.
    const labels = SERVER_VERDICTS.map((v) => verdictPresentation(v).label);
    expect(labels).not.toContain('APPROVE');
    expect(labels).not.toContain('CONDITIONAL');
  });

  describe('severity ordering', () => {
    it('orders proceed < hold < decline', () => {
      const s = (v: string) => verdictPresentation(v).severity;
      expect(s('proceed')).toBeLessThan(s('hold'));
      expect(s('hold')).toBeLessThan(s('decline'));
    });

    it('sorting by severity puts the strongest objection last', () => {
      const sorted = ['decline', 'proceed', 'hold']
        .sort((a, b) => verdictPresentation(a).severity - verdictPresentation(b).severity)
        .map((v) => verdictPresentation(v).label);
      expect(sorted).toEqual(['PROCEED', 'HOLD', 'DECLINE']);
    });

    it('colour carries the same ordering it did before — decline is never green or amber', () => {
      expect(verdictPresentation('decline').color).toBe('error');
      expect(verdictPresentation('decline').color).not.toBe('success');
      expect(verdictPresentation('decline').color).not.toBe('warning');
    });
  });

  describe('an unrecognised verdict', () => {
    const junk = verdictPresentation('CONDITIONAL');

    it('is not treated as known', () => {
      expect(junk.known).toBe(false);
      expect(junk.verdict).toBeNull();
    });

    it('is labelled visibly distinctly, and NOT as any real verdict', () => {
      expect(junk.label).toBe('UNRECOGNISED VERDICT');
      expect(EXPECTED.map((e) => e.label as string)).not.toContain(junk.label);
    });

    it('is never the mildest label or the mildest colour', () => {
      expect(junk.color).not.toBe('success');
      expect(junk.color).not.toBe('warning');
      expect(junk.severity).toBeGreaterThan(verdictPresentation('decline').severity);
      expect(junk.severity).toBe(UNRECOGNISED_SEVERITY);
    });

    it('is distinguishable from `decline` even though both are red', () => {
      // Colour alone cannot carry this: a broken pipeline and a genuine refusal
      // are both error-coloured. The variant and the label must separate them.
      const decline = verdictPresentation('decline');
      expect(junk.color).toBe(decline.color);
      expect(junk.variant).not.toBe(decline.variant);
      expect(junk.label).not.toBe(decline.label);
    });

    it('quotes the offending token so the drift is diagnosable', () => {
      expect(verdictPresentation('proceeed').description).toContain('"proceeed"');
    });

    it.each(['APPROVE', 'CONDITIONAL', 'approve', 'conditional', 'yes', 'ok', '???'])(
      'treats %s as unrecognised rather than repairing it',
      (token) => {
        expect(verdictPresentation(token).known).toBe(false);
      }
    );
  });

  describe('a missing verdict', () => {
    it.each([undefined, null, '', '   '])('renders %p as an explicit absence', (raw) => {
      const p = verdictPresentation(raw as string | null | undefined);
      expect(p.label).toBe('NO VERDICT');
      expect(p.known).toBe(false);
    });

    it('is never the mildest label or colour', () => {
      const p = verdictPresentation(undefined);
      expect(p.color).toBe('error');
      expect(p.severity).toBe(UNRECOGNISED_SEVERITY);
    });

    it('says plainly that an absent opinion is not consent', () => {
      expect(verdictPresentation(undefined).description).toMatch(/not an approval/i);
    });
  });

  describe('normalisation', () => {
    it.each(['PROCEED', 'Proceed', ' proceed ', 'pRoCeEd'])(
      'accepts %p as proceed — the token is re-cased crossing the language boundary',
      (raw) => {
        expect(normaliseVerdict(raw)).toBe('proceed');
      }
    );

    it('does not repair near-misses', () => {
      expect(normaliseVerdict('declined')).toBeNull();
      expect(normaliseVerdict('holding')).toBeNull();
      expect(normaliseVerdict('pro ceed')).toBeNull();
    });
  });
});
