/**
 * The flagship proof: the backend's OWN bytes drive the SSE pipeline.
 *
 * `tests/fixtures/copilot-wire-envelopes.json` (repo root) is frozen by the
 * banker-copilot-service golden test — it is captured by driving the real
 * planner, and it contains a genuine primary/supervisor disagreement
 * (primary APPROVE vs supervisor DECLINE). We replay it through the EXACT SSE
 * code path the browser runs:
 *
 *     golden JSON  ->  toEnvelope (which now calls toApproval)  ->  reduce  ->  store
 *
 * If the SSE client bypassed `toApproval` — the bug this file exists to pin —
 * the reducer would receive raw WIRE shape: `payload.approval.agentAssessment`
 * as an object instead of `assessments` as a client array, and the disagreement
 * banner would never light. Asserting against the golden bytes rather than
 * `demoFixture.ts` is deliberate: the fixture agreed with the reducer while the
 * service disagreed with both, which is exactly how the live path stayed broken
 * behind a green suite.
 *
 * The import is a relative path to the repo-root fixture. Copying it into `src/`
 * would re-create the duplication this whole change exists to delete, so we do
 * not.
 */

import golden from '../../../../../../tests/fixtures/copilot-wire-envelopes.json';
import { toEnvelope } from '../../../api/copilotStream';
import { emptyState, reduce } from '../../../state/copilotStore';
import { disagreementOf } from '../approvalPolicy';
import { CopilotEvent, CopilotState } from '../types';

interface RawGoldenEnvelope {
  seq: number;
  kind: string;
  payload: { approval?: { id?: string; agentAssessment?: unknown } };
}

const goldenEnvelopes = golden as unknown as RawGoldenEnvelope[];

function replayThroughSsePipeline(): { state: CopilotState; replayed: number } {
  let state = emptyState();
  let replayed = 0;
  for (const envelope of goldenEnvelopes) {
    // Frame the envelope exactly as the SSE transport delivers it, then run the
    // real client parser + mapper.
    const shaped = toEnvelope({ data: JSON.stringify(envelope) });
    // Positive control: every golden frame must survive shaping. If one silently
    // dropped, the disagreement assertion below could pass vacuously on an
    // approval that never got updated.
    expect(shaped).not.toBeNull();
    state = reduce(state, shaped as CopilotEvent);
    replayed += 1;
  }
  return { state, replayed };
}

describe('golden wire envelopes -> SSE pipeline -> store', () => {
  it('the golden fixture actually exercises a disagreement (anti-vacuous guard)', () => {
    // Prove the haystack is non-empty and still shaped the way this test needs
    // BEFORE asserting anything about the needle. A fixture that stopped
    // carrying an approval.updated with {primary, supervisor} must fail loudly
    // here, not quietly stop testing disagreement.
    expect(goldenEnvelopes.length).toBeGreaterThan(0);

    const updated = goldenEnvelopes.filter((e) => e.kind === 'approval.updated');
    expect(updated.length).toBeGreaterThan(0);

    const dualShaped = updated.find((e) => {
      const aa = e.payload.approval?.agentAssessment as
        | { primary?: { verdict?: string }; supervisor?: { verdict?: string } }
        | undefined;
      return Boolean(aa?.primary && aa?.supervisor);
    });
    expect(dualShaped).toBeDefined();

    const aa = dualShaped!.payload.approval!.agentAssessment as {
      primary: { verdict?: string };
      supervisor: { verdict?: string };
    };
    // The raw bytes must disagree, or the pipeline assertion proves nothing.
    expect((aa.primary.verdict || '').toUpperCase()).not.toBe(
      (aa.supervisor.verdict || '').toUpperCase()
    );
  });

  it('routes approval payloads through toApproval (client shape, not wire shape)', () => {
    const { state, replayed } = replayThroughSsePipeline();
    expect(replayed).toBeGreaterThan(0);

    const id = goldenEnvelopes[0].payload.approval!.id as string;
    const approval = state.approvals[id];
    expect(approval).toBeDefined();

    // `toApproval` flattens the free-form wire `payload` object into an array of
    // rendered PayloadField rows. Raw wire shape is an object; client shape is
    // this array. If the SSE path bypassed the mapper, this would be an object.
    expect(Array.isArray(approval.payload)).toBe(true);
    expect(approval.payload.length).toBeGreaterThan(0);
    // The material flags the disclosure gate depends on are produced by the
    // mapper — prove at least one survived the trip.
    expect(approval.payload.some((f) => f.material)).toBe(true);
  });

  it('carries BOTH primary and supervisor after the wholesale update, and reports a real disagreement', () => {
    const { state } = replayThroughSsePipeline();

    const id = goldenEnvelopes[0].payload.approval!.id as string;
    const approval = state.approvals[id];
    expect(approval).toBeDefined();

    const roles = approval.assessments.map((a) => a.role);
    // putApproval replaces wholesale, so the final approval.updated must itself
    // carry both assessments — an update with only the supervisor would erase
    // the primary and the banner needs both.
    expect(roles).toContain('primary');
    expect(roles).toContain('supervisor');

    const disagreement = disagreementOf(approval.assessments);
    // The flagship demo moment: proven against the backend's own bytes.
    expect(disagreement.kind).not.toBe('none');
    expect(disagreement.kind).toBe('verdict');
  });
});
