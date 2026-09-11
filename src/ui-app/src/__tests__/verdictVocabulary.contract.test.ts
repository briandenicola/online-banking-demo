/**
 * Contract: the verdict vocabulary and the tri-state agreement tokens the UI
 * renders must be the ones the service actually defines.
 *
 * `verdicts.py` opens with "**A second definition of this tuple, in any module or
 * any language, is a defect on sight.**" `supervisorVerdict.ts` is a second
 * definition in another language — unavoidably, because TypeScript cannot import
 * from Python — so it is held to the original by parsing the original.
 *
 * The failure mode that makes this necessary is the one this feature already
 * shipped: `decline` arrived at a lookup that had no case for it and fell through
 * to "CONDITIONAL", the mildest label on the screen. Nothing threw. The suite was
 * green. Check 4.2 — "does the supervisor ever genuinely disagree?" — is answered
 * by looking at that chip, so the drift corrupted a measurement rather than just
 * a pixel.
 *
 * Two more reasons this parses rather than restates:
 *
 *  - the tuple MOVED this week, from `supervisor_model.py` to `verdicts.py`, and
 *    the comment in `supervisorVerdict.ts` still cited the old home. A comment
 *    cannot go stale in a way a test notices; a parse can.
 *  - a renamed constant must fail LOUDLY. A regex that quietly finds nothing and
 *    compares against nothing is the failure this whole file is about.
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { SERVER_VERDICTS } from '../components/copilot/supervisorVerdict';
import { AGREEMENT_STATES } from '../components/copilot/types';

const PLANNER = join(__dirname, '..', '..', '..', 'banker-copilot-service', 'app', 'planner');
const VERDICTS_PY = join(PLANNER, 'verdicts.py');
const FANOUT_PY = join(PLANNER, 'fanout.py');

function pythonTuple(source: string, name: string): string[] {
  const match = source.match(new RegExp(`^${name}\\s*=\\s*\\(([^)]*)\\)`, 'm'));
  // A missing constant means the service was refactored out from under this
  // file. Fail loudly — a silently skipped contract test is worse than none.
  expect(match).not.toBeNull();
  return match![1]
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry !== '')
    .map((entry) => {
      const literal = entry.match(/^["']([^"']+)["']$/);
      if (literal) return literal[1];
      // A bare identifier: `AGREEMENT_STATES = (AGREE, DIVERGE, NOT_COMPARABLE)`.
      // Resolve it to the string it is bound to rather than comparing against the
      // Python variable NAME — those happen to look similar here, and a
      // comparison that passes because two spellings coincide is the kind that
      // survives the rename it exists to catch.
      const bound = source.match(new RegExp(`^${entry}\\s*=\\s*["']([^"']+)["']`, 'm'));
      expect(bound).not.toBeNull();
      return bound![1];
    });
}

describe('verdict vocabulary contract', () => {
  const verdicts = readFileSync(VERDICTS_PY, 'utf8');
  const fanoutSource = readFileSync(FANOUT_PY, 'utf8');

  it('finds the real definitions in the real source (anti-vacuous guard)', () => {
    // Prove the haystack before asserting about the needle.
    expect(verdicts).toMatch(/^RECOMMENDATIONS\s*=\s*\(/m);
    expect(verdicts).toMatch(/^AGREEMENT_STATES\s*=\s*\(/m);
    expect(verdicts).toMatch(/def compare_verdicts\(/);
  });

  it('the UI verdict list is the server list, in the same order', () => {
    // Order matters here and nowhere else: `SERVER_VERDICTS` is documented as
    // ascending objection strength, and the severity ranks in `supervisorVerdict`
    // are read off that order.
    expect([...SERVER_VERDICTS]).toEqual(pythonTuple(verdicts, 'RECOMMENDATIONS'));
  });

  it('the server sentinel for "not a verdict" is not itself a verdict', () => {
    // Found by tampering. The UI is safe against the sentinel being RENAMED —
    // anything outside the closed set renders as UNRECOGNISED at maximum
    // severity. It is NOT safe against the sentinel becoming a real verdict:
    // `UNRECOGNISED_VERDICT = "hold"` would render a broken pipeline as a
    // genuine, mild, plausible second opinion, on the exact banner a banker
    // reads consensus from. That is the original defect restored from the far
    // side of the wire, where no UI test can see it.
    const match = verdicts.match(/^UNRECOGNISED_VERDICT\s*=\s*"([^"]+)"/m);
    expect(match).not.toBeNull();
    const sentinel = match![1];
    expect(sentinel.trim()).not.toBe('');
    expect((SERVER_VERDICTS as readonly string[]).map((v) => v.toLowerCase())).not.toContain(
      sentinel.toLowerCase()
    );
  });

  it('the UI agreement states are the server agreement states', () => {
    const server = pythonTuple(verdicts, 'AGREEMENT_STATES');
    expect([...AGREEMENT_STATES].sort()).toEqual([...server].sort());
    // Named individually, because a set comparison passes on any renaming that
    // swaps two members, and `not_comparable` is the one that carries the whole
    // point of the tri-state.
    expect(server).toContain('not_comparable');
  });

  it('the server still STATES agreement on the wire the card reads', () => {
    // The silent-failure seam. If `fanout.py` stops writing `agreement` into
    // `agentAssessment`, the card does not break — it renders `not_comparable`
    // forever, which is safe and completely invisible. This is where that
    // becomes loud instead.
    expect(fanoutSource).toMatch(/updated_approval\["agentAssessment"\]\s*=\s*\{/);
    expect(fanoutSource).toMatch(/"agreement":\s*agreement/);
    expect(fanoutSource).toMatch(/agreement\s*=\s*compare_verdicts\(/);
  });

  it('the primary side of the comparison has no manufactured fallback', () => {
    // `_primary_recommendation` used to end in `or "proceed"`. That fallback is
    // what made a supervisor `hold` against a FAILED primary render as genuine
    // dissent — the tri-state exists because of it, so its absence is asserted
    // rather than assumed.
    expect(fanoutSource).toMatch(/def _primary_recommendation\(/);
    // Assert the CODE, not the absence of a string: the docstring of that very
    // function quotes `or "proceed"` while explaining why it was removed, so a
    // blanket `not.toMatch` passes or fails on prose.
    expect(fanoutSource).toMatch(
      /return str\(recommendation\) if is_verdict\(recommendation\) else None/
    );
  });
});
