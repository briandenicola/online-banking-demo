/**
 * The task queue — the banker's inbox.
 *
 * Grouped by WHAT IT NEEDS FROM YOU, not by domain, because "what must I do
 * next" is the only question this pane exists to answer.
 *
 * Two anti-fatigue mechanisms live here (§6):
 *
 *  - QUEUE SHAPING. Never more than the configured number of cards in "Needs
 *    you" at once; the rest sit behind "Show N more". An eighty-item wall
 *    induces triage-by-clicking. Sorting is by TTL, not by amount, so urgency is
 *    real rather than salience-driven.
 *  - THE SESSION APPROVAL METER. A persistent, visible count of what you have
 *    signed and how fast. At the soft threshold it interposes a pause card.
 *    Making the rate visible to the person doing it is most of the effect;
 *    hard blocks get worked around with a second browser and the workaround is
 *    worse than the behaviour.
 *
 * NOT here, and not anywhere: a global "approve all". Batch approval is L1-only,
 * one action type, under threshold, and Phase 3.
 */

import React, { useMemo, useState } from 'react';
import {
  Alert,
  AlertTitle,
  Badge,
  Box,
  Button,
  Chip,
  Collapse,
  LinearProgress,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import { Approval, QueueGroupId } from './types';
import { AuthorityRungChip, ApprovalCountdown } from './CopilotPrimitives';
import { getCopilotConfig } from '../../config/copilotConfig';
import { useNow } from './CopilotContext';
import { msUntil } from './approvalPolicy';

const GROUP_LABELS: Record<QueueGroupId, string> = {
  needsYou: 'Needs you',
  awaitingCosigner: 'Waiting on a co-signer',
  running: 'Running',
  doneToday: 'Done today',
};

export interface QueueGroups {
  needsYou: Approval[];
  awaitingCosigner: Approval[];
  running: Approval[];
  doneToday: Approval[];
}

/**
 * Buckets the approval list.
 *
 * `awaitingCosigner` is what the banker sees for their OWN L2 requests. It is
 * read-only to them and it names no prospective signer — the copy is "awaiting a
 * supervisor", because there is no `cosignerId` and there must not be one:
 * naming a reviewer at proposal time lets the requester pick their own.
 */
export function groupApprovals(approvals: Approval[], now: number): QueueGroups {
  const byTtl = (a: Approval, b: Approval) => msUntil(a.expiresAt, now) - msUntil(b.expiresAt, now);

  const open = approvals.filter((a) => a.status === 'proposed' || a.status === 'pending');

  return {
    needsYou: open.filter((a) => a.callerMaySign).sort(byTtl),
    awaitingCosigner: open.filter((a) => !a.callerMaySign).sort(byTtl),
    running: approvals.filter((a) => a.status === 'signed'),
    doneToday: approvals.filter((a) => a.status === 'executed' || a.status === 'denied'),
  };
}

// ---------------------------------------------------------------------------

interface ItemProps {
  approval: Approval;
  selected: boolean;
  onSelect: (id: string) => void;
  actionable: boolean;
}

const TaskQueueItem: React.FC<ItemProps> = ({ approval, selected, onSelect, actionable }) => (
  <Box
    component="button"
    onClick={() => onSelect(approval.id)}
    aria-current={selected}
    sx={{
      display: 'block',
      width: '100%',
      textAlign: 'left',
      border: 0,
      borderLeft: 3,
      borderStyle: 'solid',
      borderColor: selected ? 'primary.main' : 'transparent',
      bgcolor: selected ? 'action.selected' : 'transparent',
      cursor: 'pointer',
      px: 1,
      py: 0.75,
    }}
  >
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {approval.actionLabel}
      </Typography>
      <AuthorityRungChip rung={approval.requiredRung} requiredSigners={approval.requiredSigners} />
    </Stack>
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mt: 0.25, flexWrap: 'wrap' }}>
      <ApprovalCountdown expiresAt={approval.expiresAt} createdAt={approval.createdAt} />
      {!actionable && (
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          {/* Never "assigned to you", never a named prospective signer. */}
          awaiting a supervisor
        </Typography>
      )}
    </Stack>
  </Box>
);

// ---------------------------------------------------------------------------

export interface SessionApprovalMeterProps {
  signedCount: number;
  /** Timestamps of signatures in this session, used for the rate figure. */
  signedAt: number[];
  onAcknowledgePause: () => void;
  paused: boolean;
}

/**
 * The meter.
 *
 * The pause card is dismissible and the dismissal is logged. A hard block would
 * be worked around, and a banker in a genuine queue crunch would resent us for
 * it — but an unexamined rate is exactly how "human in the loop" becomes
 * theatre, so the rate is put in front of the person producing it.
 */
export const SessionApprovalMeter: React.FC<SessionApprovalMeterProps> = ({
  signedCount,
  signedAt,
  onAcknowledgePause,
  paused,
}) => {
  const config = getCopilotConfig();
  const limit = config.sessionSignatureSoftLimit;
  const pct = Math.min(100, (signedCount / limit) * 100);

  const meanSeconds = useMemo(() => {
    if (signedAt.length < 2) return null;
    const span = signedAt[signedAt.length - 1] - signedAt[0];
    return Math.round(span / (signedAt.length - 1) / 1000);
  }, [signedAt]);

  return (
    <Box sx={{ p: 1, borderTop: 1, borderColor: 'divider' }}>
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        Signed this session {signedCount} of {limit}
      </Typography>
      <LinearProgress
        variant="determinate"
        value={pct}
        color={pct >= 100 ? 'warning' : 'primary'}
        sx={{ height: 6, borderRadius: 3, mt: 0.5 }}
      />
      <Collapse in={paused}>
        <Alert severity="warning" sx={{ mt: 1 }}>
          <AlertTitle>Take a moment</AlertTitle>
          You&apos;ve signed {signedCount} items
          {meanSeconds !== null ? `, averaging ${meanSeconds} seconds each` : ''}. A falling
          time-to-sign is what approval fatigue looks like — it is not efficiency.
          <Box sx={{ mt: 1 }}>
            <Button size="small" onClick={onAcknowledgePause}>
              I&apos;ve read this — continue
            </Button>
          </Box>
        </Alert>
      </Collapse>
    </Box>
  );
};

// ---------------------------------------------------------------------------

export interface TaskQueuePaneProps {
  approvals: Approval[];
  selectedId?: string;
  onSelect: (id: string) => void;
  meter: SessionApprovalMeterProps;
}

const TaskQueuePane: React.FC<TaskQueuePaneProps> = ({ approvals, selectedId, onSelect, meter }) => {
  const config = getCopilotConfig();
  const now = useNow();
  const groups = useMemo(() => groupApprovals(approvals, now), [approvals, now]);
  const [expandedAll, setExpandedAll] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<QueueGroupId, boolean>>({
    needsYou: true,
    awaitingCosigner: false,
    running: false,
    doneToday: false,
  });

  const needsYouVisible = expandedAll
    ? groups.needsYou
    : groups.needsYou.slice(0, config.queueVisibleLimit);
  const hiddenCount = groups.needsYou.length - needsYouVisible.length;

  const renderGroup = (id: QueueGroupId, items: Approval[], actionable: boolean) => (
    <Box key={id}>
      <Box
        component="button"
        onClick={() => setOpenGroups((prev) => ({ ...prev, [id]: !prev[id] }))}
        aria-expanded={openGroups[id]}
        sx={{
          display: 'flex',
          width: '100%',
          alignItems: 'center',
          gap: 1,
          border: 0,
          background: 'none',
          cursor: 'pointer',
          px: 1,
          py: 0.5,
        }}
      >
        <Typography variant="overline" sx={{ color: 'text.secondary' }}>
          {GROUP_LABELS[id]}
        </Typography>
        <Badge badgeContent={items.length} color={id === 'needsYou' ? 'warning' : 'default'} showZero />
      </Box>
      <Collapse in={openGroups[id]}>
        {items.length === 0 ? (
          <Typography variant="caption" sx={{ pl: 1, color: 'text.secondary' }}>
            Nothing here.
          </Typography>
        ) : (
          (id === 'needsYou' ? needsYouVisible : items).map((approval) => (
            <TaskQueueItem
              key={approval.id}
              approval={approval}
              selected={approval.id === selectedId}
              onSelect={onSelect}
              actionable={actionable}
            />
          ))
        )}
        {id === 'needsYou' && hiddenCount > 0 && (
          <Button size="small" onClick={() => setExpandedAll(true)} sx={{ ml: 1 }}>
            Show {hiddenCount} more
          </Button>
        )}
      </Collapse>
    </Box>
  );

  return (
    <Paper
      variant="outlined"
      component="section"
      aria-label="Task queue"
      sx={{ display: 'flex', flexDirection: 'column', height: '100%', minWidth: 0 }}
    >
      <Box sx={{ p: 1, borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          Task queue
        </Typography>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          Sorted by time remaining, never by amount.
        </Typography>
      </Box>

      <Box sx={{ flexGrow: 1, overflowY: 'auto' }}>
        {renderGroup('needsYou', groups.needsYou, true)}
        {renderGroup('awaitingCosigner', groups.awaitingCosigner, false)}
        {renderGroup('running', groups.running, false)}
        {renderGroup('doneToday', groups.doneToday, false)}
      </Box>

      <Box sx={{ px: 1, pb: 1 }}>
        <Chip
          size="small"
          variant="outlined"
          label="No batch approval — L1 only, Phase 3"
          sx={{ width: '100%' }}
        />
      </Box>

      <SessionApprovalMeter {...meter} />
    </Paper>
  );
};

export default TaskQueuePane;
