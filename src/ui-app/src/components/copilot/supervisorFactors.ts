/**
 * The ONE place an agent's key factor becomes a row on the card.
 *
 * Three lies converged on this row, and all three came from filling a field to
 * satisfy a type rather than because something was known:
 *
 *  1. The service paired every factor with the constant string
 *     "independently corroborated". Nothing is corroborated and nothing is
 *     checked — it was a literal in a list comprehension. Worst case:
 *     `_failsafe` emits the factor `supervisor_unavailable` when the supervisor
 *     could not be reached, understood, or trusted, so a FAILED call rendered as
 *     "supervisor_unavailable — independently corroborated".
 *  2. `concern` is never set by the service, and the card read
 *     `concern ? '✗' : '✓'` — so the absence of a judgement rendered as a green
 *     tick. Same shape as a verdict fallback landing on the mildest label: the
 *     falsy branch of a two-way ternary quietly ASSERTS something.
 *  3. `divergentFactors` compared against the primary's factors, which the
 *     service never sends at all, so every supervisor factor was flagged
 *     divergent — bold red, on every run, hardest on the runs where the
 *     supervisor said nothing.
 *
 * Stacked, one row on a failed supervisor call read:
 *
 *     supervisor_unavailable · independently corroborated ✓   (bold red, DIVERGENT)
 *
 * Three mutually contradictory signals, none of them true, immediately beneath
 * `_failsafe`'s honest prose: "Treat this as unreviewed."
 *
 * How the shape drifted: `demoFixture` taught the UI a `{label, value, concern}`
 * measurement pair — `{label: 'Aggregate', value: '$24,500 / 48h'}` — that the
 * service has never once produced. The type was honest, the card rendered it
 * faithfully, and the fixture agreed with the renderer instead of with the
 * service. Every test passed.
 */

import { AgentKeyFactor } from './types';

/**
 * The sentinel `supervisor_model._failsafe` emits as its only key factor when the
 * supervisor could not be reached, understood, or trusted.
 *
 * Pinned against the Python source by `supervisorFactors.contract.test.ts` rather
 * than trusted as a literal — this is a token the server owns, and a restatement
 * of it here can drift silently into never matching, which fails OPEN: the row
 * would quietly go back to rendering as an ordinary factor.
 */
export const SUPERVISOR_UNAVAILABLE_FACTOR = 'supervisor_unavailable';

/**
 * Rendered where the `← DIVERGENT` flags would have been, when the primary stated
 * no key factors and so nothing could be compared against.
 *
 * Wording note: Danny's §F5 offers this "something of the form: *Factor comparison
 * unavailable — the primary agent does not emit key factors.*" The second clause is
 * stated run-scoped here instead, because `primary_model.py` now DOES parse and emit
 * `keyFactors` on the happy path — it is an assessment this run did not produce, not
 * a capability the service lacks. Saying the stronger thing would be the same class
 * of error the ruling exists to remove: a label asserting more than is known.
 */
export const FACTOR_COMPARISON_UNAVAILABLE =
  'Factor comparison unavailable — the primary agent stated no key factors.';

export interface FactorPresentation {
  /** The agent's own statement — the row's main text. */
  text: string;
  /** Present only when a producer genuinely measured something. Never invented. */
  value?: string;
  /**
   * '✗' when the agent flagged a concern, '✓' when it explicitly did not, and
   * `null` when it did not say. `null` renders NOTHING: silence is not assent.
   */
  glyph: '✗' | '✓' | null;
  /** True for the failed-call sentinel. Rendered as a failure, never as a factor. */
  unavailable: boolean;
  /** Screen-reader / tooltip text. The state is never carried by weight or colour alone. */
  description: string;
}

const UNAVAILABLE: FactorPresentation = {
  text: 'The supervisor did not return a usable opinion.',
  glyph: null,
  unavailable: true,
  description:
    'The independent supervisor could not be reached, understood, or trusted, so this action has NOT been reviewed independently. This is a failed call, not a factor, and not agreement.',
};

export function isSupervisorUnavailable(factor: AgentKeyFactor | undefined): boolean {
  return factor?.label?.trim().toLowerCase() === SUPERVISOR_UNAVAILABLE_FACTOR;
}

/** True when this assessment is the failsafe rather than a real second opinion. */
export function assessmentIsUnavailable(factors: AgentKeyFactor[] | undefined): boolean {
  return Boolean(factors?.some(isSupervisorUnavailable));
}

export function factorPresentation(factor: AgentKeyFactor): FactorPresentation {
  if (isSupervisorUnavailable(factor)) return UNAVAILABLE;

  return {
    text: factor.label,
    // Only forwarded when the producer actually sent one. There is no default,
    // because the only default available is a sentence that isn't true.
    value: typeof factor.value === 'string' && factor.value.trim() !== '' ? factor.value : undefined,
    glyph: factor.concern === true ? '✗' : factor.concern === false ? '✓' : null,
    unavailable: false,
    description:
      factor.concern === true
        ? `${factor.label} — flagged as weighing against the action.`
        : factor.concern === false
          ? `${factor.label} — explicitly not a concern.`
          : `${factor.label} — stated as a factor; the agent did not classify it for or against.`,
  };
}
