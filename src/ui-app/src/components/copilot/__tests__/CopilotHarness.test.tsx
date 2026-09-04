/**
 * Smoke test: the /copilot surface mounts and shows the three panes.
 *
 * Deliberately shallow. Its job is to catch the failure mode where the surface
 * typechecks and builds but throws on first paint — which no amount of unit
 * testing on the reducer would find.
 *
 * It replays the recorded fixture through the real store, so it also proves the
 * envelope → reducer → render path end to end without a network.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import CopilotHarness from '../CopilotHarness';
import { CopilotProvider } from '../CopilotContext';
import { createCopilotStore } from '../../../state/copilotStore';
import { demoEvents } from '../demoFixture';
import { FeatureFlagProvider } from '../../../contexts/FeatureFlagContext';
import TaskMeasurementBar from '../../comparison/TaskMeasurementBar';

function renderHarness() {
  const store = createCopilotStore();
  demoEvents.forEach((event) => store.dispatchSync(event));

  return render(
    <FeatureFlagProvider>
      <TaskMeasurementBar surface="copilot">
        <CopilotProvider store={store} offline>
          <CopilotHarness />
        </CopilotProvider>
      </TaskMeasurementBar>
    </FeatureFlagProvider>
  );
}

describe('CopilotHarness', () => {
  it('renders the three panes', () => {
    renderHarness();
    expect(screen.getByRole('region', { name: /task queue/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /plan and trace/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /artifacts and approvals/i })).toBeInTheDocument();
  });

  it('renders the plan, including the step added by the mid-run revision', () => {
    renderHarness();
    expect(screen.getByText(/Pull overnight flagged transactions/)).toBeInTheDocument();
    expect(screen.getByText(/Assess the Meridian Freight cluster/)).toBeInTheDocument();
    expect(screen.getByText(/plan revised/i)).toBeInTheDocument();
  });

  it('separates the supervisor agent from the plan it reviews', () => {
    renderHarness();
    expect(screen.getByText(/SUPERVISOR AGENT/)).toBeInTheDocument();
    expect(
      screen.getByText(/does NOT see the primary agent's recommendation/i)
    ).toBeInTheDocument();
  });

  it('is a work surface, not a chatbot', () => {
    // The composer is a thin command bar. If this ever becomes a chat column,
    // the product has quietly turned into the thing the design argued against.
    renderHarness();
    expect(screen.getByLabelText(/describe the task/i)).toBeInTheDocument();
    expect(screen.queryByText(/send message/i)).not.toBeInTheDocument();
  });

  it('does not announce the streaming trace to screen readers frame by frame', () => {
    // A polite live region on a 200-events/sec trace gets switched off by the
    // user, which is strictly worse than never offering one.
    renderHarness();
    const tree = screen.getByRole('tree', { name: /agent plan trace/i });
    expect(tree).toHaveAttribute('aria-live', 'off');
  });
});
