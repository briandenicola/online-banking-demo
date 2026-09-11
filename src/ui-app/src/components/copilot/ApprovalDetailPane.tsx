/**
 * The selected approval, given the centre pane.
 *
 * Why this exists: the centre is the largest pane on the surface, and until now
 * it sat empty reading "No run selected" while the thing the banker had actually
 * clicked was crammed into the narrow right-hand column — 1000-odd pixels of
 * signature slots, payload hash, escalators and denial input squeezed into a
 * ~340px scroll window. People do not scroll a column they did not expect to
 * have to scroll, and an unread payload hash is an unverified signature.
 *
 * The rule is deliberately stateless and can be said in one sentence: the centre
 * shows the run trace whenever a run exists, and otherwise shows the approval you
 * selected. There is no timer, no "recently viewed", nothing to get out of sync.
 *
 * This is a LAYOUT wrapper only. It renders `ApprovalCard` unchanged, so every
 * field — rung, payload hash, signature slots, fired escalators, terminal reason,
 * the denial-reason input and the "Signing paused" banner — is the same component
 * the right-hand dock renders. Nothing is dropped or truncated to make it fit;
 * the pane scrolls instead.
 */

import React from 'react';
import { Box, Paper, Typography } from '@mui/material';
import ApprovalCard from './ApprovalCard';
import { Approval, StreamStatus } from './types';

export interface ApprovalDetailPaneProps {
  approval: Approval;
  streamStatus: StreamStatus;
  onSigned?: (dwellMs: number, evidenceOpened: boolean) => void;
  onDenied?: (dwellMs: number, evidenceOpened: boolean) => void;
}

const ApprovalDetailPane: React.FC<ApprovalDetailPaneProps> = ({
  approval,
  streamStatus,
  onSigned,
  onDenied,
}) => (
  <Paper
    variant="outlined"
    component="section"
    aria-label="Selected approval"
    data-testid="approval-detail-pane"
    sx={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      minWidth: 0,
      minHeight: 0,
      // See TracePane: a lone child of a flex Region is content-width without this.
      flexGrow: 1,
    }}
  >
    <Box sx={{ borderBottom: 1, borderColor: 'divider', p: 1 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
        Selected approval
      </Typography>
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        Start a task in the command bar and the plan and trace take this pane; this approval
        stays open beside it.
      </Typography>
    </Box>

    {/*
      `minHeight: 0` is what allows this to shrink inside the flex column rather
      than pushing the command bar off the bottom of the surface — the same trap
      that hid the command bar behind the footer.
    */}
    <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: 'auto', p: 1.5 }}>
      <ApprovalCard
        approval={approval}
        streamStatus={streamStatus}
        onSigned={onSigned}
        onDenied={onDenied}
      />
    </Box>
  </Paper>
);

export default ApprovalDetailPane;
