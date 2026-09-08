/**
 * The three-pane work surface.
 *
 * Left: what needs you. Centre: what the agent is doing. Right: what it made,
 * with the approval docked beneath it.
 *
 * The proportions are deliberate. The trace is the widest pane because the whole
 * argument for this surface is that the reasoning is inspectable; if the trace
 * were a sidebar we would be saying "trust it, here is a receipt". The approval
 * is docked under the artifact rather than floating over everything, so the
 * evidence stays visible while you decide.
 *
 * Below ~1200px the artifact pane folds under the trace, and below ~900px the
 * queue collapses to a drawer. The one thing that never collapses or moves is
 * the approval dock — a control whose position changes with viewport is a
 * control people mis-click.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Button, Drawer, Snackbar, Stack, useMediaQuery, useTheme } from '@mui/material';
import ErrorBoundary from '../ErrorBoundary';
import TaskQueuePane from './TaskQueuePane';
import TracePane from './TracePane';
import ArtifactCanvas from './ArtifactCanvas';
import CommandBar from './CommandBar';
import { L3RefusalCard } from './ApprovalCard';
import { useApproval, useApprovals, useCopilot, useRun } from './CopilotContext';
import { getCopilotConfig } from '../../config/copilotConfig';
import { useTaskMeasurement } from '../comparison/TaskMeasurementBar';

const Region: React.FC<{ id: string; children: React.ReactNode; sx?: object }> = ({
  id,
  children,
  sx,
}) => (
  <Box data-comparison-region={id} sx={{ minWidth: 0, minHeight: 0, ...sx }}>
    {children}
  </Box>
);

const CopilotHarness: React.FC = () => {
  const config = getCopilotConfig();
  const theme = useTheme();
  const wide = useMediaQuery(theme.breakpoints.up('lg'));
  // Deliberately phrased as "is it narrow?" rather than "is it wide enough?".
  // `useMediaQuery` returns false before it can measure, so the up() form would
  // collapse the banker's inbox into a drawer whenever the viewport is not yet
  // known — hiding the primary work list by default. Matching AppShell's
  // `down('md')` convention also keeps the two breakpoints from drifting.
  const narrow = useMediaQuery(theme.breakpoints.down('md'));

  const {
    activeRunId,
    selectedApprovalId,
    selectApproval,
    submitIntent,
    refreshApprovals,
    streamStatus,
    lastError,
  } = useCopilot();

  const run = useRun(activeRunId);
  const approvals = useApprovals();
  const selected = useApproval(selectedApprovalId);
  const measurement = useTaskMeasurement();

  const [queueOpen, setQueueOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [signedAt, setSignedAt] = useState<number[]>([]);
  const [pauseAcknowledgedAt, setPauseAcknowledgedAt] = useState(0);
  const [refused, setRefused] = useState<string | undefined>(undefined);

  useEffect(() => {
    refreshApprovals().catch(() => undefined);
  }, [refreshApprovals]);

  // Auto-select the most urgent thing that needs a human, but only when nothing
  // is selected — re-pointing the dock underneath someone mid-read is exactly
  // how a wrong signature happens.
  useEffect(() => {
    if (selectedApprovalId) return;
    const next = approvals.find((a) => a.status === 'pending' && a.callerMaySign);
    if (next) selectApproval(next.id);
  }, [approvals, selectedApprovalId, selectApproval]);

  const paused = useMemo(() => {
    const recent = signedAt.filter((t) => Date.now() - t < config.sessionSignatureWindowMs);
    return recent.length >= config.sessionSignatureSoftLimit && pauseAcknowledgedAt < (recent[recent.length - 1] || 0);
  }, [signedAt, pauseAcknowledgedAt, config.sessionSignatureSoftLimit, config.sessionSignatureWindowMs]);

  const onSubmit = useCallback(
    async (intent: string) => {
      setBusy(true);
      setRefused(undefined);
      try {
        await submitIntent(intent);
      } finally {
        setBusy(false);
      }
    },
    [submitIntent]
  );

  const onSigned = useCallback(
    (dwellMs: number, evidenceOpened: boolean) => {
      setSignedAt((prev) => [...prev, Date.now()]);
      if (selected) {
        measurement.recordDecisionOnSurface({
          approvalId: selected.id,
          decision: 'signed',
          requiredRung: selected.requiredRung,
          dwellMs,
          evidenceOpened,
        });
      }
      refreshApprovals().catch(() => undefined);
    },
    [selected, measurement, refreshApprovals]
  );

  const onDenied = useCallback(
    (dwellMs: number, evidenceOpened: boolean) => {
      if (selected) {
        measurement.recordDecisionOnSurface({
          approvalId: selected.id,
          decision: 'denied',
          requiredRung: selected.requiredRung,
          dwellMs,
          evidenceOpened,
          terminalReason: 'HUMAN_DENIED',
        });
      }
      refreshApprovals().catch(() => undefined);
    },
    [selected, measurement, refreshApprovals]
  );

  const queue = (
    <TaskQueuePane
      approvals={approvals}
      selectedId={selectedApprovalId}
      onSelect={selectApproval}
      meter={{
        signedCount: signedAt.length,
        signedAt,
        paused,
        onAcknowledgePause: () => setPauseAcknowledgedAt(Date.now()),
      }}
    />
  );

  /**
   * Fill whatever space the shell hands down; never state the viewport maths.
   *
   * This was `calc(100vh - 64px)`, then a measured equivalent. Both were the
   * same mistake in different clothes: a child computing how much room its
   * ancestors had left. The comparison bar and the demo banner both sit above
   * this surface, so any arithmetic here goes stale the moment the chrome
   * changes, and the command bar — the only way to type anything — drops below
   * the fold.
   *
   * The shell now constrains itself to the viewport when a full-bleed surface
   * is mounted, so this only has to claim the remainder. `minHeight: 0` is what
   * lets a flex child actually shrink; without it the internal panes push the
   * surface past the space it was given.
   */
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        flexGrow: 1,
        minHeight: 0,
        overflow: 'hidden',
      }}
    >
      <Box sx={{ flexGrow: 1, display: 'flex', gap: 1, p: 1, minHeight: 0 }}>
        {!narrow ? (
          <Region id="queue" sx={{ width: 300, flexShrink: 0 }}>
            <ErrorBoundary section="Task queue">{queue}</ErrorBoundary>
          </Region>
        ) : (
          <Drawer open={queueOpen} onClose={() => setQueueOpen(false)}>
            <Box sx={{ width: 300, height: '100%' }} data-comparison-region="queue">
              <ErrorBoundary section="Task queue">{queue}</ErrorBoundary>
            </Box>
          </Drawer>
        )}

        <Box
          sx={{
            flexGrow: 1,
            display: 'flex',
            flexDirection: wide ? 'row' : 'column',
            gap: 1,
            minWidth: 0,
            minHeight: 0,
          }}
        >
          <Region id="trace" sx={{ flex: wide ? 1.6 : 1, display: 'flex', minHeight: 0 }}>
            <ErrorBoundary section="Trace">
              <TracePane run={run} />
            </ErrorBoundary>
          </Region>

          <Region id="artifact" sx={{ flex: 1, display: 'flex', minHeight: 0 }}>
            <ErrorBoundary section="Artifacts and approvals">
              {refused ? (
                <L3RefusalCard intent={refused} />
              ) : (
                <ArtifactCanvas
                  run={run}
                  approval={selected}
                  streamStatus={streamStatus}
                  onSigned={onSigned}
                  onDenied={onDenied}
                />
              )}
            </ErrorBoundary>
          </Region>
        </Box>
      </Box>

      <Region id="command">
        {narrow && (
          <Button size="small" onClick={() => setQueueOpen(true)} sx={{ ml: 1 }}>
            Queue ({approvals.length})
          </Button>
        )}
        <CommandBar onSubmit={onSubmit} busy={busy} streamStatus={streamStatus} />
      </Region>

      <Snackbar
        open={Boolean(lastError)}
        message={lastError}
        autoHideDuration={8000}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      />
      <Stack sx={{ display: 'none' }} aria-hidden="true" />
    </Box>
  );
};

export default CopilotHarness;
