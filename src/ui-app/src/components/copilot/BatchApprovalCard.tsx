/**
 * Batch approval — L1 ONLY, one action type, under threshold, hard-capped.
 *
 * ============================================================================
 * THE L2 EXCLUSION HERE IS STRUCTURAL, NOT A DISABLED BUTTON.
 * ============================================================================
 *
 * This card can only ever be handed a `BatchGroup`, and a `BatchGroup` is built
 * by `batchableGroups()`, which admits an item only if `isBatchEligible()` — L1,
 * a single required signer, and the service says the caller may sign. There is
 * no code path that puts an L2 item in front of this component, and this
 * component re-applies the same filter defensively so that even a hand-built
 * group cannot smuggle one in. Batching a second opinion defeats the second
 * opinion: L2 exists because a *different human* must look at *this* item, and a
 * sign-all gesture is precisely the reflexive click it defends against.
 *
 * What batching legitimately buys: ten identical $12 fee reversals signed once
 * instead of ten times. What it must never become: forty heterogeneous items
 * behind one click, which is autonomy laundering with a human's name attached.
 * Hence: one action type per group, a cap enforced in config as a ceiling that
 * cannot be raised, and every item's material fields rendered in a scannable
 * table — never a count, never "and 9 more".
 */

import React, { useMemo, useState } from 'react';
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Checkbox,
  Chip,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import { Approval, PayloadField, StreamStatus, canSignUnderStream } from './types';
import { BatchGroup, formatFieldValue, isBatchEligible } from './approvalPolicy';
import { PayloadHashChip } from './CopilotPrimitives';
import { useCopilot } from './CopilotContext';

type ItemOutcome = 'idle' | 'signing' | 'signed' | 'error';

export interface BatchApprovalCardProps {
  group: BatchGroup;
  streamStatus: StreamStatus;
  onBatchSigned?: (signedCount: number) => void;
}

/** The union of material field paths across the batch, in first-seen order. */
function materialColumns(items: Approval[]): PayloadField[] {
  const seen = new Map<string, PayloadField>();
  for (const item of items) {
    for (const field of item.payload) {
      if (field.material && !seen.has(field.path)) seen.set(field.path, field);
    }
  }
  return Array.from(seen.values());
}

const BatchApprovalCard: React.FC<BatchApprovalCardProps> = ({ group, streamStatus, onBatchSigned }) => {
  const { sign } = useCopilot();

  // Defence in depth: even if a group were hand-built, an L2 item cannot survive
  // this filter. The structural guarantee does not rely on the caller.
  const items = useMemo(() => group.items.filter(isBatchEligible), [group.items]);

  const columns = useMemo(() => materialColumns(items), [items]);
  const [included, setIncluded] = useState<Set<string>>(() => new Set(items.map((i) => i.id)));
  const [outcomes, setOutcomes] = useState<Record<string, ItemOutcome>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>(undefined);

  const streamSafe = canSignUnderStream(streamStatus);
  const selectedIds = items.filter((i) => included.has(i.id) && outcomes[i.id] !== 'signed').map((i) => i.id);
  const canSign = !busy && streamSafe && selectedIds.length > 0;

  if (items.length < 2) {
    // Not a batch. Refuse to render batch chrome around a single item — that
    // would train the sign-all reflex for no efficiency gain.
    return null;
  }

  const toggle = (id: string) => {
    setIncluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSignAll = async () => {
    setBusy(true);
    setError(undefined);
    let signed = 0;
    for (const item of items) {
      if (!included.has(item.id) || outcomes[item.id] === 'signed') continue;
      setOutcomes((prev) => ({ ...prev, [item.id]: 'signing' }));
      try {
        // Each item carries its OWN payload hash. A batch is N independent
        // signatures against N distinct payloads, not one signature over a
        // digest of the set — if one item's payload moved, the server rejects
        // that one and the rest still stand.
        await sign(item.id, item.payloadHash);
        setOutcomes((prev) => ({ ...prev, [item.id]: 'signed' }));
        signed += 1;
      } catch {
        setOutcomes((prev) => ({ ...prev, [item.id]: 'error' }));
      }
    }
    setBusy(false);
    if (signed > 0 && onBatchSigned) onBatchSigned(signed);
    if (signed === 0) setError('None of the selected items were accepted.');
  };

  return (
    <Paper variant="outlined" sx={{ p: 2, borderColor: 'info.main' }} aria-label={`Batch: ${group.actionLabel}`}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', mb: 0.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 800, letterSpacing: 0.5 }}>
          BATCH — L1 ONLY
        </Typography>
        <Chip size="small" color="info" variant="outlined" label={`${items.length} items · one action type`} />
        <Box sx={{ flexGrow: 1 }} />
        <Chip size="small" variant="outlined" label={group.actionId} />
      </Stack>

      <Typography variant="body2" sx={{ mb: 0.5 }}>
        {group.actionLabel} — every item below is a single-signer L1 action. Review each row before
        signing; the material fields are shown, not summarised.
      </Typography>

      {/* Why this cannot include an L2 item, said out loud. Invisible constraints
          teach nobody, and this one is load-bearing. */}
      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 1 }}>
        Anything requiring a supervisor co-signature is never eligible for a batch — a second opinion
        cannot be batched, so those stay as individual cards.
      </Typography>

      <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            <Box component="th" sx={{ textAlign: 'left', borderBottom: 1, borderColor: 'divider', p: 0.5 }}>
              include
            </Box>
            {columns.map((col) => (
              <Box
                key={col.path}
                component="th"
                sx={{ textAlign: 'left', borderBottom: 1, borderColor: 'divider', p: 0.5 }}
              >
                {col.label}
              </Box>
            ))}
            <Box component="th" sx={{ textAlign: 'left', borderBottom: 1, borderColor: 'divider', p: 0.5 }}>
              payload
            </Box>
            <Box component="th" sx={{ textAlign: 'left', borderBottom: 1, borderColor: 'divider', p: 0.5 }}>
              status
            </Box>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const outcome = outcomes[item.id] || 'idle';
            const byPath = new Map(item.payload.map((f) => [f.path, f]));
            return (
              <Box component="tr" key={item.id} sx={{ opacity: outcome === 'signed' ? 0.6 : 1 }}>
                <Box component="td" sx={{ borderBottom: 1, borderColor: 'divider', p: 0.5 }}>
                  <Checkbox
                    size="small"
                    checked={included.has(item.id) && outcome !== 'signed'}
                    disabled={busy || outcome === 'signed'}
                    onChange={() => toggle(item.id)}
                    slotProps={{ input: { 'aria-label': `include ${item.actionLabel}` } }}
                  />
                </Box>
                {columns.map((col) => {
                  const field = byPath.get(col.path);
                  return (
                    <Box component="td" key={col.path} sx={{ borderBottom: 1, borderColor: 'divider', p: 0.5 }}>
                      {field ? formatFieldValue(field) : '—'}
                    </Box>
                  );
                })}
                <Box component="td" sx={{ borderBottom: 1, borderColor: 'divider', p: 0.5 }}>
                  <PayloadHashChip hash={item.payloadHash} hashShort={item.payloadHashShort} />
                </Box>
                <Box component="td" sx={{ borderBottom: 1, borderColor: 'divider', p: 0.5 }}>
                  {outcome === 'signed' ? (
                    <Chip size="small" color="success" variant="outlined" label="signed" />
                  ) : outcome === 'signing' ? (
                    <Chip size="small" variant="outlined" label="signing…" />
                  ) : outcome === 'error' ? (
                    <Chip size="small" color="error" variant="outlined" label="rejected" />
                  ) : (
                    <Chip size="small" variant="outlined" label="◷ awaiting" />
                  )}
                </Box>
              </Box>
            );
          })}
        </tbody>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}

      {!streamSafe && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          <AlertTitle>Signing paused</AlertTitle>
          Live updates are interrupted — batch signing is disabled until the connection is verified,
          for the same reason a single signature is: an item&apos;s payload may have moved.
        </Alert>
      )}

      <Stack direction="row" spacing={1} sx={{ mt: 1.5, justifyContent: 'flex-end', alignItems: 'center' }}>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          {selectedIds.length} selected
        </Typography>
        <Button variant="contained" disabled={!canSign} onClick={handleSignAll}>
          {/* Never "Approve all". Signing, and only for the selected L1 items. */}
          Sign {selectedIds.length} item{selectedIds.length === 1 ? '' : 's'}
        </Button>
      </Stack>
    </Paper>
  );
};

export default BatchApprovalCard;
