/**
 * Symmetry tests for the surface comparison.
 *
 * The Phase 1 carry-over was explicit: instrument BOTH surfaces in one pass or
 * defer again with a reason, because asymmetric instrumentation rigs the
 * comparison in the harness's favour. These tests are how that promise is kept
 * mechanically rather than by memory.
 *
 * The strongest guarantee available is structural: neither surface contains any
 * counting code, so neither CAN be counted more finely than the other. That is
 * asserted here by grepping the surfaces for recorder calls.
 */

import fs from 'fs';
import path from 'path';
import React from 'react';
import { render, screen } from '@testing-library/react';
import TaskMeasurementBar from '../TaskMeasurementBar';
import { COMPARISON_METRICS, SHARED_TASK_SET } from '../../../telemetry/comparison';
import { FeatureFlagProvider } from '../../../contexts/FeatureFlagContext';

const SRC = path.resolve(__dirname, '../../..');

function readSurface(relativePath: string): string {
  return fs.readFileSync(path.join(SRC, relativePath), 'utf8');
}

const RECORDER_CALLS = [
  'recordInteraction',
  'recordContextSwitch',
  'recordEvidenceOpen',
  'startTask',
  'endTask',
];

describe('comparison instrumentation symmetry', () => {
  it('keeps all counting rules out of both surfaces', () => {
    // If either surface called the recorder directly, the two could drift —
    // and the drift would be invisible in a diff that only touched one of them.
    const classic = readSurface('pages/AdminPage.tsx');
    const copilot = readSurface('components/copilot/CopilotHarness.tsx');

    RECORDER_CALLS.forEach((call) => {
      expect(classic).not.toContain(`${call}(`);
      expect(copilot).not.toContain(`${call}(`);
    });
  });

  it('wraps both surfaces in the same measurement component', () => {
    const classic = readSurface('pages/AdminPage.tsx');
    const copilot = readSurface('pages/BankerCopilotPage.tsx');

    expect(classic).toContain('TaskMeasurementBar surface="classic"');
    expect(copilot).toContain('TaskMeasurementBar surface="copilot"');
  });

  it('declares comparison regions on both surfaces', () => {
    // A context switch is defined by region traversal. If one surface declared
    // regions and the other did not, its switch count would be structurally
    // zero — a flattering number that means nothing.
    const classic = readSurface('pages/AdminPage.tsx');
    const copilot = readSurface('components/copilot/CopilotHarness.tsx');

    expect(classic).toContain('data-comparison-region');
    expect(copilot).toContain('data-comparison-region');
  });

  it('offers the same task set to both surfaces', () => {
    expect(SHARED_TASK_SET.length).toBeGreaterThan(0);
    SHARED_TASK_SET.forEach((task) => {
      expect(task.taskKey).toBeTruthy();
      expect(task.rationale).toBeTruthy();
    });
  });

  it('keeps time-to-sign pre-registered as suspicious when it falls', () => {
    // Pre-registered in Phase 1, before any data existed, precisely so a fast
    // signature could not be reinterpreted as efficiency after the fact.
    const dwell = COMPARISON_METRICS.find((m) => m.key === 'signatureDwellMs');
    expect(dwell).toBeDefined();
    expect(dwell?.direction).toBe('lowerIsSuspicious');
  });

  it('renders an export affordance on either surface', () => {
    render(
      <FeatureFlagProvider>
        <TaskMeasurementBar surface="classic">
          <div />
        </TaskMeasurementBar>
      </FeatureFlagProvider>
    );

    expect(screen.getByRole('button', { name: /export comparison data/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start measured task/i })).toBeInTheDocument();
  });

  it('offers no batch approval affordance in the queue', () => {
    // Epic §9 risk #1: a banker signing 40 cards an hour makes "human in the
    // loop" theatre. Batch approval is L1-only and Phase 3, not now. The
    // assertion is on rendered controls, not on source text — the source
    // deliberately DISCUSSES the absent feature in a comment.
    const queue = readSurface('components/copilot/TaskQueuePane.tsx');
    expect(queue).not.toMatch(/onClick=\{[^}]*approveAll/i);
    expect(queue).not.toMatch(/<Checkbox/);
    expect(queue).not.toMatch(/label="Approve all"/i);
  });
});
