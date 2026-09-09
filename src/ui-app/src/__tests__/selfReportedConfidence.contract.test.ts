/**
 * Contract: the wire field the card reads for self-reported confidence.
 *
 * The ruling (§P7.2) renames `confidence` to `selfReportedConfidence` — the field
 * name is the only form of caveat that survives being copied into a screenshot —
 * but DEFERS the wire half of that rename to §P9, because it crosses the language
 * boundary and the frozen golden bytes. So today: the client type says
 * `selfReportedConfidence`, and the wire still says `confidence`.
 *
 * That is a rename in transit, and this repo has already been burned once by a
 * value being renamed between two ends of a wire. The difference is that this one
 * is declared, single-mapper, and held here.
 *
 * The failure mode being prevented is SILENT. `toAssessments` reads exactly one
 * key. On the day the server renames its field, the mapper finds nothing, the
 * number simply stops appearing on the card, and no test goes red — the card
 * looks fine, just quieter. The tempting fix is to read both spellings, which is
 * the `policyVersion` seam again: two accepted spellings of one fact, drifting
 * independently. So instead the rename is made to fail HERE, loudly, in the same
 * change that performs it.
 */

import { readFileSync } from 'fs';
import { join } from 'path';

const APPROVAL_VIEW_PY = join(
  __dirname,
  '..',
  '..',
  '..',
  'banker-copilot-service',
  'app',
  'planner',
  'approval_view.py'
);

describe('self-reported confidence wire-name contract', () => {
  const source = readFileSync(APPROVAL_VIEW_PY, 'utf8');

  it('finds the wire builders in the real Python source (anti-vacuous guard)', () => {
    expect(source).toMatch(/def primary_proposal_assessment\(/);
    expect(source).toMatch(/def supervisor_wire_assessment\(/);
  });

  it('the primary still writes the number under the key the mapper reads', () => {
    // `authorityWire.toAssessments` reads `value.confidence` and nothing else.
    expect(source).toMatch(/wire\["confidence"\]\s*=\s*assessment\.self_reported_confidence/);
  });

  it('the supervisor writes the same key', () => {
    expect(source).toMatch(/"confidence":\s*confidence/);
  });

  it('the number is ABSENT on a failed assessment, never zero', () => {
    // §P4.1. A zero is a number: it can be plotted, averaged and compared, and a
    // sentinel number gets pooled into a statistic by accident. An absent field
    // cannot be. The card's `typeof === 'number'` test would happily render a
    // sentinel 0.0 as a real self-reported confidence.
    expect(source).toMatch(/if assessment\.self_reported_confidence is not None:/);
  });
});
