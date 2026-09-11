/**
 * Contract: the failed-supervisor sentinel the UI recognises must be the one the
 * service actually emits.
 *
 * `supervisor_model._failsafe` returns `key_factors=("supervisor_unavailable",)`
 * whenever the supervisor could not be reached, understood, or trusted. The card
 * special-cases that token to render a failed call as a failure rather than as a
 * factor with a green tick beside it.
 *
 * This is the failure mode that makes the test necessary: if the Python literal
 * is renamed and the TypeScript constant is not, the match silently stops firing
 * and the row **fails open** — it goes straight back to rendering the raw
 * sentinel as though it were something the supervisor said. Nothing throws, no
 * suite goes red, and the regression is invisible until someone reads a card
 * from a failed run.
 *
 * Per the ruling on the neighbouring seams, this PARSES the Python source rather
 * than restating the literal. A restatement is a third document that can drift
 * from both the ones it claims to hold together — and here it would drift in the
 * direction that hides the problem.
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { SUPERVISOR_UNAVAILABLE_FACTOR } from '../components/copilot/supervisorFactors';

const SUPERVISOR_MODEL_PY = join(
  __dirname,
  '..',
  '..',
  '..',
  'banker-copilot-service',
  'app',
  'planner',
  'supervisor_model.py'
);

describe('supervisor failsafe sentinel contract', () => {
  const source = readFileSync(SUPERVISOR_MODEL_PY, 'utf8');

  it('finds the failsafe key_factors tuple in the real Python source (anti-vacuous guard)', () => {
    // Prove the haystack before asserting about the needle. If `_failsafe` were
    // refactored away, every assertion below could otherwise pass on nothing.
    expect(source).toMatch(/def _failsafe\(/);
    expect(source).toMatch(/key_factors\s*=\s*\(/);
  });

  it('matches the token _failsafe actually emits', () => {
    const match = source.match(/key_factors\s*=\s*\(\s*["']([^"']+)["']\s*,?\s*\)/);

    // A missing constant means the service was refactored. Fail loudly — a
    // silently skipped contract test is worse than none.
    expect(match).not.toBeNull();
    expect(SUPERVISOR_UNAVAILABLE_FACTOR).toBe(match![1]);
  });

  it('is the failsafe path, and the failsafe still withholds', () => {
    // The sentinel only means "not reviewed" because the failsafe verdict is a
    // withhold. If _failsafe ever returned `proceed`, recognising the token would
    // be beside the point — so the neighbouring invariant is asserted here too.
    expect(source).toMatch(/FAILSAFE_RECOMMENDATION\s*=\s*["']hold["']/);
    expect(source).toMatch(/recommendation=FAILSAFE_RECOMMENDATION/);
  });
});
