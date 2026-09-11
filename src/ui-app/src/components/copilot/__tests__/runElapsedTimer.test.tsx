/**
 * The run timer must stop when the run stops.
 *
 * Brian's UI showed "181s and still counting" beside "the agent is still running on the
 * server" for a run the service had finished in 241ms four minutes earlier. Two separate
 * lies on one line: the reconnect copy (fixed in TracePane) and this timer, which recomputed
 * `now - startedAt` on every tick and ignored the authoritative `durationMs` that `run.done`
 * carries and the reducer already stores.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import TracePane from '../TracePane';
import { RunState } from '../types';

jest.mock('../CopilotContext', () => ({
  useNow: () => Date.now(),
  useCopilot: () => ({
    density: 'comfortable',
    setDensity: jest.fn(),
    streamStatus: 'live',
    incomplete: false,
  }),
}));

/** The run from the trace pulled off the live cluster: one step, finished in 166ms. */
function completedRun(overrides: Partial<RunState> = {}): RunState {
  return {
    runId: 'run_1',
    title: 'Refund a $35 overdraft fee on retail’s checking as goodwill',
    status: 'completed',
    startedAt: new Date(Date.now() - 181000).toISOString(),
    durationMs: 166,
    planVersion: 1,
    stepIds: ['step_1'],
    steps: {
      step_1: {
        id: 'step_1',
        index: 0,
        title: 'Assemble evidence bundle',
        status: 'complete',
        kind: 'artifact',
        toolCallIds: [],
        subagentIds: [],
      },
    },
    subagents: {},
    toolCalls: {},
    rootSubagentIds: [],
    revisions: [],
    artifactIds: [],
    approvalIds: [],
    ...overrides,
  } as RunState;
}

describe('run elapsed timer', () => {
  it('reports the duration the server recorded, not wall clock since it started', () => {
    render(<TracePane run={completedRun()} />);

    // 166ms, not 181s. `startedAt` is deliberately three minutes in the past here — exactly
    // the shape of Brian's screen — so a timer still counting from it cannot pass.
    expect(screen.getByText(/1 steps · 0\.2s/)).toBeInTheDocument();
    expect(screen.queryByText(/18\ds/)).not.toBeInTheDocument();
  });

  it('still counts up while the run is actually running', () => {
    render(
      <TracePane
        run={completedRun({
          status: 'running',
          durationMs: undefined,
          startedAt: new Date(Date.now() - 5000).toISOString(),
        })}
      />
    );

    expect(screen.getByText(/1 steps · 5s/)).toBeInTheDocument();
  });
});
