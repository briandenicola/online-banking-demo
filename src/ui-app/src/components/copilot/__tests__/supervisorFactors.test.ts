/**
 * Guards for the key-factor row.
 *
 * Three lies met on this row and each has its own test here, because they were
 * mutually reinforcing — the fabricated value made the tick look earned, the
 * tick made the divergence flag look considered, and the divergence flag made
 * the whole row look like analysis. Assert them separately or a single fix
 * appears to have resolved all three.
 *
 * The worst case is the one to hold onto: `_failsafe` emits the single factor
 * `supervisor_unavailable` when the supervisor could not be reached, understood
 * or trusted, and it rendered as
 *
 *     supervisor_unavailable · independently corroborated ✓
 *
 * bold red and flagged DIVERGENT — directly beneath the failsafe's own honest
 * prose, "Treat this as unreviewed."
 */

import {
  SUPERVISOR_UNAVAILABLE_FACTOR,
  assessmentIsUnavailable,
  factorPresentation,
  isSupervisorUnavailable,
} from '../supervisorFactors';

describe('key factor presentation', () => {
  describe('the fabricated value is gone', () => {
    it('carries no value when the producer sent none', () => {
      expect(factorPresentation({ label: 'pattern matches invoice settlement' }).value).toBeUndefined();
    });

    it('never substitutes a corroboration claim for a missing value', () => {
      const p = factorPresentation({ label: 'counterparty is an established freight vendor' });
      expect(p.value).not.toBe('independently corroborated');
      expect(JSON.stringify(p)).not.toMatch(/corroborated/i);
    });

    it('forwards a genuine value when one is actually present', () => {
      // Anti-vacuous counterpart: the fix must not have deleted the capability,
      // only the invention. A producer that measures something may still say so.
      expect(factorPresentation({ label: 'Aggregate', value: '$24,500 / 48h' }).value).toBe(
        '$24,500 / 48h'
      );
    });

    it('treats a blank value as absent rather than rendering an empty column', () => {
      expect(factorPresentation({ label: 'x', value: '   ' }).value).toBeUndefined();
    });
  });

  describe('the glyph is tri-state, and silence renders nothing', () => {
    it('shows ✗ when the agent flagged a concern', () => {
      expect(factorPresentation({ label: 'x', concern: true }).glyph).toBe('✗');
    });

    it('shows ✓ only when the agent EXPLICITLY said it was not a concern', () => {
      expect(factorPresentation({ label: 'x', concern: false }).glyph).toBe('✓');
    });

    it('shows nothing when the agent did not classify the factor', () => {
      // The whole defect in one assertion: `concern ? '✗' : '✓'` made an unstated
      // judgement render as a green tick. Absence is not assent.
      expect(factorPresentation({ label: 'x' }).glyph).toBeNull();
    });

    it('never renders a tick for an unstated judgement', () => {
      expect(factorPresentation({ label: 'x' }).glyph).not.toBe('✓');
    });

    it('describes the three states differently for screen readers', () => {
      const stated = factorPresentation({ label: 'x', concern: false }).description;
      const flagged = factorPresentation({ label: 'x', concern: true }).description;
      const silent = factorPresentation({ label: 'x' }).description;
      expect(new Set([stated, flagged, silent]).size).toBe(3);
      expect(silent).toMatch(/did not classify/i);
    });
  });

  describe('the failed-call sentinel', () => {
    const failed = factorPresentation({ label: SUPERVISOR_UNAVAILABLE_FACTOR });

    it('is recognised as a failed call, not a factor', () => {
      expect(failed.unavailable).toBe(true);
      expect(isSupervisorUnavailable({ label: SUPERVISOR_UNAVAILABLE_FACTOR })).toBe(true);
    });

    it('never renders a tick', () => {
      expect(failed.glyph).toBeNull();
      expect(failed.glyph).not.toBe('✓');
    });

    it('never renders a corroboration claim', () => {
      expect(failed.value).toBeUndefined();
      expect(JSON.stringify(failed)).not.toMatch(/corroborated/i);
    });

    it('does not show the raw sentinel token as if it were the supervisor speaking', () => {
      expect(failed.text).not.toBe(SUPERVISOR_UNAVAILABLE_FACTOR);
      expect(failed.text).toMatch(/did not return a usable opinion/i);
    });

    it('says plainly that nothing was reviewed independently', () => {
      expect(failed.description).toMatch(/NOT been reviewed independently/i);
      expect(failed.description).toMatch(/not agreement/i);
    });

    it('is matched case- and whitespace-insensitively across the language boundary', () => {
      expect(isSupervisorUnavailable({ label: ' Supervisor_Unavailable ' })).toBe(true);
    });

    it('does not swallow a real factor that merely mentions the supervisor', () => {
      // Anti-vacuous: a substring match would classify genuine prose as a failure.
      expect(isSupervisorUnavailable({ label: 'supervisor_unavailable in prior run' })).toBe(false);
      expect(factorPresentation({ label: 'the supervisor was unavailable last week' }).unavailable).toBe(
        false
      );
    });

    it('flags the whole assessment as unavailable', () => {
      expect(assessmentIsUnavailable([{ label: SUPERVISOR_UNAVAILABLE_FACTOR }])).toBe(true);
      expect(assessmentIsUnavailable([{ label: 'a real factor' }])).toBe(false);
      expect(assessmentIsUnavailable(undefined)).toBe(false);
    });
  });
});
