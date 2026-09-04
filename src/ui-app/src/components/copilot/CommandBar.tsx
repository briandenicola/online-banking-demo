/**
 * The command bar.
 *
 * Deliberately a thin strip at the bottom, not a chat column. The visual weight
 * of an input box tells people what the product is: a big centred composer says
 * "converse with me", a thin bar says "state your intent and then read the work".
 * We are building the second thing.
 *
 * It also carries the stream status indicator, because connection state belongs
 * next to the thing that depends on it.
 */

import React, { useState } from 'react';
import { Box, Button, Chip, Stack, TextField, Tooltip } from '@mui/material';
import { StreamStatus } from './types';

const STATUS_COPY: Record<StreamStatus, { label: string; color: 'default' | 'success' | 'warning' | 'error' }> = {
  idle: { label: 'Idle', color: 'default' },
  connecting: { label: 'Connecting', color: 'warning' },
  live: { label: 'Live', color: 'success' },
  reconnecting: { label: 'Reconnecting', color: 'warning' },
  resumed: { label: 'Live (resumed)', color: 'success' },
  degraded: { label: 'Degraded', color: 'warning' },
  failed: { label: 'Disconnected', color: 'error' },
  closed: { label: 'Closed', color: 'default' },
};

export const StreamStatusIndicator: React.FC<{ status: StreamStatus }> = ({ status }) => {
  const copy = STATUS_COPY[status];
  return (
    <Tooltip
      title={
        status === 'failed'
          ? 'Live updates are unavailable. The run continues on the server; signing is disabled until the trace is trustworthy again.'
          : 'Live trace connection state.'
      }
    >
      <Chip size="small" color={copy.color} variant="outlined" label={copy.label} role="status" />
    </Tooltip>
  );
};

export interface CommandBarProps {
  onSubmit: (intent: string) => void;
  busy: boolean;
  streamStatus: StreamStatus;
  disabled?: boolean;
}

const CommandBar: React.FC<CommandBarProps> = ({ onSubmit, busy, streamStatus, disabled }) => {
  const [value, setValue] = useState('');

  const submit = () => {
    const intent = value.trim();
    if (!intent || busy || disabled) return;
    onSubmit(intent);
    setValue('');
  };

  return (
    <Box
      component="form"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      sx={{ p: 1, borderTop: 1, borderColor: 'divider' }}
    >
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <StreamStatusIndicator status={streamStatus} />
        <TextField
          fullWidth
          size="small"
          value={value}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          placeholder="What do you need? e.g. review the flagged wires from overnight"
          slotProps={{ htmlInput: { 'aria-label': 'Describe the task' } }}
        />
        <Button type="submit" variant="contained" disabled={busy || disabled || value.trim().length === 0}>
          {busy ? 'Working…' : 'Start'}
        </Button>
      </Stack>
    </Box>
  );
};

export default CommandBar;
