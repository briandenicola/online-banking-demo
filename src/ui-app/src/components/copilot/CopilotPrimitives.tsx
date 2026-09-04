/**
 * Small shared pieces of the Copilot surface.
 *
 * Two MUI v9 traps are avoided throughout this folder and are worth naming once
 * here, because `tsc --noEmit` does NOT catch either and only `craco build`
 * does: `<Switch inputProps={...} />` must be `slotProps={{ input: ... }}`, and
 * `<Stack alignItems="center">` is no longer a valid direct prop — it goes in
 * `sx`. Every Stack in this folder follows the second rule.
 */

import React from 'react';
import { Box, Chip, LinearProgress, Tooltip, Typography } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import CircleIcon from '@mui/icons-material/Circle';
import ReplayIcon from '@mui/icons-material/Replay';
import BlockIcon from '@mui/icons-material/Block';
import { AuthorityRung, NodeStatus } from './types';
import { countdownLabel, countdownSeverity, msUntil } from './approvalPolicy';
import { useNow } from './CopilotContext';

// ---------------------------------------------------------------------------

interface RungChipProps {
  rung: AuthorityRung;
  requiredSigners?: number;
  size?: 'small' | 'medium';
}

/**
 * Colour is never the only signal — every chip carries the rung text and, at L2,
 * the signer count. Red-only encoding fails for a meaningful share of bankers
 * and for anyone looking at a projected screen.
 */
export const AuthorityRungChip: React.FC<RungChipProps> = ({ rung, requiredSigners, size = 'small' }) => {
  const label =
    rung === 'L2'
      ? `L2 · ${requiredSigners ?? 2} signers`
      : rung === 'L3'
        ? 'L3 · outside the harness'
        : 'L1 · one signer';
  const color = rung === 'L1' ? 'info' : rung === 'L2' ? 'warning' : 'error';

  return <Chip size={size} color={color} variant="outlined" label={label} />;
};

// ---------------------------------------------------------------------------

interface CountdownProps {
  expiresAt: string;
  createdAt?: string;
  size?: 'small' | 'medium';
}

/**
 * The TTL countdown.
 *
 * Copy is invariant: "expires in MM:SS → DENIED". Never "auto-approves", never a
 * bare timer. There is no configuration in which reaching zero causes an action
 * to occur, and the label says so on every render so nobody has to remember it.
 *
 * The ticking digits are `aria-hidden` behind a `role="timer"` — announcing a
 * countdown continuously makes a page unusable with a screen reader. The text
 * alternative names the absolute expiry time instead.
 */
export const ApprovalCountdown: React.FC<CountdownProps> = ({ expiresAt, createdAt, size = 'small' }) => {
  const now = useNow();
  const remaining = msUntil(expiresAt, now);
  const total = createdAt
    ? Math.max(1, new Date(expiresAt).getTime() - new Date(createdAt).getTime())
    : remaining;
  const severity = countdownSeverity(remaining, total);

  // warning.main / error.main rather than the light tones: the light tones do not
  // clear 4.5:1 against background.paper in this theme.
  const color =
    severity === 'critical' ? 'error.main' : severity === 'warning' ? 'warning.main' : 'text.secondary';

  const absolute = new Date(expiresAt).toLocaleTimeString();

  if (remaining <= 0) {
    return (
      <Typography variant={size === 'small' ? 'caption' : 'body2'} sx={{ color: 'text.secondary', fontWeight: 600 }}>
        signature window closed — DENIED
      </Typography>
    );
  }

  return (
    <Box role="timer" aria-live="off" sx={{ display: 'inline-flex' }}>
      <Typography
        variant={size === 'small' ? 'caption' : 'body2'}
        aria-hidden="true"
        sx={{ color, fontWeight: severity === 'normal' ? 400 : 700, fontVariantNumeric: 'tabular-nums' }}
      >
        ◷ {countdownLabel(remaining)}
      </Typography>
      <Box component="span" sx={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
        {`Expires at ${absolute}; expiry denies this request.`}
      </Box>
    </Box>
  );
};

// ---------------------------------------------------------------------------

interface PayloadHashProps {
  hash: string;
  hashShort: string;
  label?: string;
}

/**
 * The payload hash, on every approval surface without exception.
 *
 * The signature binds THIS hash — not the intent, not the title, not the agent's
 * summary. Showing it is what makes "the payload changed" a checkable claim
 * rather than a thing the banker has to take on faith, and it is the most
 * legible security property in the system.
 *
 * The short form is server-computed (`payloadHashShort`). The client never
 * truncates a hash itself: a client-side truncation rule that drifts from the
 * server's produces two different "same" hashes.
 */
export const PayloadHashChip: React.FC<PayloadHashProps> = ({ hash, hashShort, label = 'payload' }) => (
  <Tooltip title={hash || 'no hash supplied'}>
    <Chip
      size="small"
      variant="outlined"
      label={`${label} ${hashShort || '—'}`}
      sx={{ fontFamily: 'monospace', letterSpacing: 0.3 }}
    />
  </Tooltip>
);

// ---------------------------------------------------------------------------

const GLYPHS: Record<NodeStatus, { icon: React.ReactNode; label: string }> = {
  pending: { icon: <RadioButtonUncheckedIcon fontSize="inherit" />, label: 'pending' },
  running: { icon: <CircleIcon fontSize="inherit" color="primary" />, label: 'running' },
  complete: { icon: <CheckCircleIcon fontSize="inherit" color="success" />, label: 'complete' },
  failed: { icon: <ErrorIcon fontSize="inherit" color="error" />, label: 'failed' },
  retrying: { icon: <ReplayIcon fontSize="inherit" color="warning" />, label: 'retrying' },
  skipped: { icon: <BlockIcon fontSize="inherit" />, label: 'superseded' },
};

/** Glyph AND label, always. State is never conveyed by colour or motion alone. */
export const NodeStatusGlyph: React.FC<{ status: NodeStatus }> = ({ status }) => {
  const glyph = GLYPHS[status];
  return (
    <Box component="span" aria-label={glyph.label} sx={{ display: 'inline-flex', fontSize: '1rem' }}>
      {glyph.icon}
    </Box>
  );
};

// ---------------------------------------------------------------------------

interface ConfidenceBarProps {
  value: number;
  label?: string;
}

/**
 * Confidence rendered as a comparable bar, not a decimal buried in prose.
 *
 * The uncomfortable case this exists for: the supervisor agent being MORE
 * confident in the opposite direction. That fact is the most decision-relevant
 * thing on an L2 disagreement screen and it must be visible at a glance.
 */
export const ConfidenceBar: React.FC<ConfidenceBarProps> = ({ value, label }) => {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <Box sx={{ minWidth: 140 }}>
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        {label ? `${label} ` : ''}
        confidence {value.toFixed(2)}
      </Typography>
      <LinearProgress
        variant="determinate"
        value={pct}
        aria-label={`confidence ${pct} percent`}
        sx={{ height: 6, borderRadius: 3 }}
      />
    </Box>
  );
};

// ---------------------------------------------------------------------------

/** Visually hidden, for live-region announcements and text alternatives. */
export const visuallyHidden = {
  position: 'absolute' as const,
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap' as const,
  border: 0,
};
