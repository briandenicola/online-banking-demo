/**
 * Reducer tests, driven by the recorded fixture.
 *
 * The fixture is the same `CopilotEvent[]` shape the wire produces, so these
 * tests exercise the exact code path the live stream does. A bespoke test
 * format here would let schema drift between the frontend and
 * banker-copilot-service pass the whole suite.
 */

import { emptyState, reduce } from '../../../state/copilotStore';
import { demoEvents } from '../demoFixture';
import { CopilotEvent, CopilotState } from '../types';

function play(events: CopilotEvent[]): CopilotState {
  return events.reduce((state, event) => reduce(state, event), emptyState());
}

describe('copilot reducer', () => {
  it('builds a run from the recorded envelope stream', () => {
    const state = play(demoEvents);
    const run = state.runs[state.activeRunId as string];

    expect(run).toBeDefined();
    expect(run.status).toBe('completed');
    expect(run.title).toBe('Review overnight flagged wires');
  });

  it('keeps superseded plan structure visible rather than deleting steps', () => {
    const state = play(demoEvents);
    const run = state.runs[state.activeRunId as string];

    // The plan was revised mid-run. Every step that ever existed is still
    // addressable — a step that vanishes destroys the reader's trust in the
    // trace as a record.
    expect(run.stepIds).toEqual(expect.arrayContaining(['st_1', 'st_2', 'st_3', 'st_4']));
    expect(run.planVersion).toBe(2);
    expect(run.revisions).toHaveLength(1);
    expect(run.revisions[0].addedStepIds).toContain('st_4');
  });

  it('parents the supervisor agent to the run, not to the step it reviews', () => {
    const state = play(demoEvents);
    const run = state.runs[state.activeRunId as string];

    // Independence is structural. If the supervisor hung off the primary's
    // step, the tree itself would assert a relationship that must not exist.
    expect(run.rootSubagentIds).toContain('sa_sup');
    expect(run.subagents.sa_sup.role).toBe('supervisor');
    expect(run.subagents.sa_1.role).toBe('specialist');
    expect(run.steps.st_4.subagentIds).toContain('sa_1');
    expect(run.steps.st_4.subagentIds).not.toContain('sa_sup');
  });

  it('is idempotent under duplicate frames', () => {
    const once = play(demoEvents);
    const twice = play([...demoEvents, ...demoEvents]);

    const runOnce = once.runs[once.activeRunId as string];
    const runTwice = twice.runs[twice.activeRunId as string];

    // Every write is an upsert keyed by id, never an append, so a duplicate
    // that slips past the seq check cannot double a tool call.
    expect(runTwice.stepIds).toEqual(runOnce.stepIds);
    expect(Object.keys(runTwice.toolCalls).sort()).toEqual(Object.keys(runOnce.toolCalls).sort());
    expect(twice.approvalIds).toEqual(once.approvalIds);
  });

  it('tolerates out-of-order frames without losing state', () => {
    // Deliberately play tool.completed BEFORE tool.started. The transport tries
    // hard to prevent this, but "the reducer explodes if the network reorders"
    // is not a property worth having.
    const reordered = [...demoEvents];
    const startedIndex = reordered.findIndex((e) => e.kind === 'tool.started');
    const completedIndex = reordered.findIndex((e) => e.kind === 'tool.completed');
    [reordered[startedIndex], reordered[completedIndex]] = [
      reordered[completedIndex],
      reordered[startedIndex],
    ];

    const state = play(reordered);
    const run = state.runs[state.activeRunId as string];
    expect(run.toolCalls.tc_1).toBeDefined();
    expect(run.status).toBe('completed');
  });

  it('registers the approval with its payload hash intact', () => {
    const state = play(demoEvents);
    const approval = state.approvals.apr_demo_0001;

    expect(approval).toBeDefined();
    expect(approval.payloadHash).toHaveLength(64);
    expect(approval.requiredRung).toBe('L2');
    expect(approval.requiredSigners).toBe(2);
    expect(approval.signaturesCollected).toBe(0);
  });

  it('never invents a co-signer identity', () => {
    const state = play(demoEvents);
    const approval = state.approvals.apr_demo_0001;
    const unfilled = approval.signatureSlots.filter((slot) => !slot.filled);

    // `cosignerId` does not exist in the domain, and an unfilled slot must not
    // carry a name by any other route either. The slot states a RULE.
    expect(unfilled.length).toBeGreaterThan(0);
    unfilled.forEach((slot) => {
      expect(slot.signedBy).toBeUndefined();
      expect(slot.signedByUsername).toBeUndefined();
      expect(Array.isArray(slot.mustDifferFrom)).toBe(true);
    });
    expect(JSON.stringify(approval)).not.toContain('cosignerId');
  });

  it('records a terminal approval with its reason', () => {
    const withTerminal: CopilotEvent[] = [
      ...demoEvents,
      {
        id: 'evt_term',
        seq: 999,
        runId: 'run_demo_0001',
        kind: 'approval.terminal',
        ts: new Date().toISOString(),
        payload: {
          approvalId: 'apr_demo_0001',
          state: 'denied',
          terminalReason: 'TTL_EXPIRED',
          terminalAt: new Date().toISOString(),
        },
      },
    ];

    const state = play(withTerminal);
    const approval = state.approvals.apr_demo_0001;
    expect(approval.status).toBe('denied');
    expect(approval.terminalReason).toBe('TTL_EXPIRED');
  });
});
