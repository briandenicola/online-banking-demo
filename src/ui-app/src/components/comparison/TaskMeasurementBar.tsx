/**
 * Shared comparison instrumentation for Classic Admin and the Copilot harness.
 *
 * ─── WHY THIS IS ONE COMPONENT AND NOT TWO ───────────────────────────────────
 *
 * In Phase 1 I built the recorder and deliberately left it with zero call sites,
 * because instrumenting the harness first would have rigged the comparison:
 * whichever surface you wire up while you are excited about it gets the careful
 * counting, and the other gets whatever you remember to add later. A "3.2x
 * fewer interactions" number produced that way is marketing, not measurement.
 *
 * So the counting rules are not written twice. They are written HERE, once, and
 * both surfaces are wrapped in the same component. The rules are:
 *
 *   INTERACTION      one click, or one activation, on an element that is
 *                    interactive (button, a, input, select, textarea,
 *                    [role=button], [role=tab], [role=treeitem]) inside the
 *                    measured subtree. Scrolling is not an interaction on
 *                    either surface. Typing is one interaction per FIELD, not
 *                    per keystroke — otherwise the harness, which has a text
 *                    command bar, would lose by construction on a metric that
 *                    means nothing.
 *
 *   CONTEXT SWITCH   the `data-comparison-region` of the interacted element
 *                    differs from the previous one. Classic Admin declares its
 *                    tabs as regions; the harness declares its three panes.
 *                    Neither surface gets to define the boundary more
 *                    favourably than the other: a region is a thing the user
 *                    must move their attention to.
 *
 *   EVIDENCE OPEN    activation of an element carrying
 *                    `data-comparison-evidence`. Both surfaces mark the same
 *                    class of thing: the underlying record behind a claim.
 *
 * Decisions (sign/deny) are reported explicitly, because only the surface knows
 * the dwell time and whether evidence was opened before signing.
 *
 * The metric set — including `lowerIsSuspicious` on time-to-sign — was
 * pre-registered in telemetry/comparison.ts before any data existed, and is not
 * to be reinterpreted after seeing results.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  DecisionKind,
  SHARED_TASK_SET,
  SurfaceId,
  endTask,
  exportComparisonData,
  recordContextSwitch,
  recordDecision,
  recordEvidenceOpen,
  recordInteraction,
  startTask,
} from '../../telemetry/comparison';
import { AuthorityRung, TerminalReason } from '../copilot/types';
import { useFeatureFlags } from '../../contexts/FeatureFlagContext';

const INTERACTIVE_SELECTOR =
  'button, a[href], input, select, textarea, [role="button"], [role="tab"], [role="treeitem"], [role="menuitem"]';

function closestInteractive(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element)) return null;
  return target.closest(INTERACTIVE_SELECTOR) as HTMLElement | null;
}

function regionOf(element: HTMLElement | null): string {
  const host = element?.closest('[data-comparison-region]') as HTMLElement | null;
  return host?.getAttribute('data-comparison-region') || 'unknown';
}

export interface TaskMeasurementApi {
  /** Non-empty while a measured task is running. */
  sessionId?: string;
  recordDecisionOnSurface: (input: {
    approvalId: string;
    decision: DecisionKind;
    requiredRung: AuthorityRung;
    dwellMs: number;
    evidenceOpened: boolean;
    terminalReason?: TerminalReason;
  }) => void;
}

const noopApi: TaskMeasurementApi = { recordDecisionOnSurface: () => undefined };

const TaskMeasurementContext = React.createContext<TaskMeasurementApi>(noopApi);

export const useTaskMeasurement = (): TaskMeasurementApi => React.useContext(TaskMeasurementContext);

export interface TaskMeasurementBarProps {
  surface: SurfaceId;
  children: React.ReactNode;
}

/**
 * Wraps a surface, renders the measurement control strip, and counts via
 * delegated DOM events on the wrapped subtree.
 *
 * Delegation rather than per-control callbacks is the point: it is not possible
 * to instrument one surface more thoroughly than the other, because neither
 * surface's components contain any counting code at all.
 */
const TaskMeasurementBar: React.FC<TaskMeasurementBarProps> = ({ surface, children }) => {
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [taskKey, setTaskKey] = useState(SHARED_TASK_SET[0].taskKey);
  const [exported, setExported] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const lastRegion = useRef<string>('');
  const typedFields = useRef<Set<string>>(new Set());

  // Read through the flag context rather than the module-level mirror so the
  // strip appears and disappears when the flag is toggled at runtime.
  const { isEnabled } = useFeatureFlags();
  const enabled = isEnabled('comparisonInstrumentation');

  const handle = useCallback(
    (element: HTMLElement | null) => {
      if (!element || !sessionId) return;

      const region = regionOf(element);
      const label =
        element.getAttribute('aria-label') || element.textContent?.trim().slice(0, 40) || 'control';
      recordInteraction(sessionId, `${region}:${label}`);

      if (lastRegion.current && region !== lastRegion.current) {
        recordContextSwitch(sessionId, lastRegion.current, region);
      }
      lastRegion.current = region;

      const evidenceHost = element.closest('[data-comparison-evidence]') as HTMLElement | null;
      const evidenceId = evidenceHost?.getAttribute('data-comparison-evidence');
      if (evidenceId) {
        recordEvidenceOpen(sessionId, evidenceId);
      }
    },
    [sessionId]
  );

  useEffect(() => {
    const node = containerRef.current;
    if (!node || !sessionId) return undefined;

    const onClick = (event: Event) => {
      const element = closestInteractive(event.target);
      // Clicking into a text field is not an interaction; the field is counted
      // once on first input below, so a composer and a form are treated alike.
      if (
        !element ||
        element instanceof HTMLTextAreaElement ||
        (element instanceof HTMLInputElement && element.type === 'text')
      ) {
        return;
      }
      handle(element);
    };

    const onInput = (event: Event) => {
      const element = closestInteractive(event.target);
      if (!element) return;
      const key = element.getAttribute('name') || element.getAttribute('aria-label') || 'field';
      if (typedFields.current.has(key)) return;
      typedFields.current.add(key);
      handle(element);
    };

    node.addEventListener('click', onClick, true);
    node.addEventListener('input', onInput, true);
    return () => {
      node.removeEventListener('click', onClick, true);
      node.removeEventListener('input', onInput, true);
    };
  }, [sessionId, handle]);

  const api: TaskMeasurementApi = React.useMemo(
    () => ({
      sessionId,
      recordDecisionOnSurface: (input) => {
        if (!sessionId) return;
        recordDecision(sessionId, input);
      },
    }),
    [sessionId]
  );

  const start = () => {
    typedFields.current = new Set();
    lastRegion.current = '';
    setSessionId(startTask(taskKey, surface));
    setExported(false);
  };

  const stop = (outcome: 'completed' | 'abandoned') => {
    if (!sessionId) return;
    endTask(sessionId, outcome);
    setSessionId(undefined);
  };

  const exportNow = () => {
    const data = exportComparisonData();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `surface-comparison-${Date.now()}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setExported(true);
  };

  return (
    <TaskMeasurementContext.Provider value={api}>
      {enabled && (
        <Box sx={{ px: 2, py: 1, borderBottom: 1, borderColor: 'divider', bgcolor: 'action.hover' }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography variant="caption" sx={{ fontWeight: 700 }}>
              Surface comparison
            </Typography>
            <Chip
              size="small"
              variant="outlined"
              label={surface === 'copilot' ? 'Copilot harness' : 'Classic Admin'}
            />
            <TextField
              select
              size="small"
              value={taskKey}
              onChange={(event) => setTaskKey(event.target.value)}
              disabled={Boolean(sessionId)}
              label="Measured task"
              sx={{ minWidth: 280 }}
            >
              {SHARED_TASK_SET.map((task) => (
                <MenuItem key={task.taskKey} value={task.taskKey}>
                  {task.label}
                </MenuItem>
              ))}
            </TextField>
            {sessionId ? (
              <>
                <Button size="small" variant="contained" onClick={() => stop('completed')}>
                  Finish task
                </Button>
                <Button size="small" onClick={() => stop('abandoned')}>
                  Gave up
                </Button>
              </>
            ) : (
              <Button size="small" variant="outlined" onClick={start}>
                Start measured task
              </Button>
            )}
            <Box sx={{ flexGrow: 1 }} />
            <Tooltip title="Downloads raw per-event data for both surfaces, including the pre-registered metric directions.">
              {/* Explicit aria-label: MUI's Tooltip would otherwise supply the
                  accessible name from its title, which describes the data
                  rather than naming the control. */}
              <Button size="small" onClick={exportNow} aria-label="Export comparison data">
                {exported ? 'Exported ✓' : 'Export comparison data'}
              </Button>
            </Tooltip>
          </Stack>
          {sessionId && (
            <Alert severity="info" sx={{ mt: 1, py: 0 }}>
              Measuring. Both surfaces are counted by the same delegated rules — see
              components/comparison/TaskMeasurementBar.tsx.
            </Alert>
          )}
        </Box>
      )}
      <Box ref={containerRef} sx={{ display: 'contents' }}>
        {children}
      </Box>
    </TaskMeasurementContext.Provider>
  );
};

export default TaskMeasurementBar;
