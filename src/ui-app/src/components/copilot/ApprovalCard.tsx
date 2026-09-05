/**
 * The approval card — L1, and the L2 dual-control / disagreement screen.
 *
 * ============================================================================
 * THIS COMPONENT IS WHERE "AGENTS NEVER APPROVE" IS EITHER TRUE OR DECORATIVE.
 * ============================================================================
 *
 * Three principles it is built on:
 *
 *  1. EVIDENCE ADJACENCY. The payload and the evidence justifying it are on
 *     screen simultaneously. This card is NEVER a modal — a modal hides the
 *     evidence behind the thing you are being asked to trust, which is exactly
 *     backwards.
 *  2. VERIFIABILITY, NOT SUMMARISATION. Material numbers link back to the tool
 *     call that produced them, so the banker can check the agent's claim rather
 *     than read the agent's confidence.
 *  3. FRICTION PROPORTIONAL TO STAKES. A $200 fee reversal and a $450k loan must
 *     not cost the same number of clicks. Uniform friction is how you get
 *     rubber-stamping.
 *
 * Anti-fatigue mechanisms implemented here (§6): the stakes-scaled dwell gate,
 * the material-field disclosure gate (IntersectionObserver, not a checkbox),
 * randomised transcription spot-checks, client-side separation-of-duties that
 * explains itself rather than 403-ing, confidence-inverted friction, and the
 * required written justification for overriding a supervisor agent.
 *
 * NOT implemented, deliberately: any form of "approve all". Batch approval is
 * L1-only, single-action-type, and Phase 3.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  Link,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import GavelIcon from '@mui/icons-material/Gavel';
import {
  Approval,
  AgentAssessment,
  canSignUnderStream,
  SignatureSlot,
  StreamStatus,
} from './types';
import {
  Disagreement,
  countMaterialChanges,
  diffPayloads,
  disagreementOf,
  dwellRequirementMs,
  formatFieldValue,
  isReversible,
  shouldSpotCheck,
  spotCheckExpectedAnswer,
  spotCheckField,
  terminalCopy,
  validateReason,
} from './approvalPolicy';
import { AuthorityRungChip, ApprovalCountdown, ConfidenceBar, PayloadHashChip } from './CopilotPrimitives';
import { getCopilotConfig } from '../../config/copilotConfig';
import { useCopilot, useNow } from './CopilotContext';
import { signingIdentity } from './signingIdentity';

// ---------------------------------------------------------------------------
// Why this rung
// ---------------------------------------------------------------------------

export const EscalatorExplainer: React.FC<{ approval: Approval }> = ({ approval }) => {
  const escalators = approval.firedEscalators;

  return (
    <Box>
      <Typography variant="overline" sx={{ color: 'text.secondary' }}>
        Why this is {approval.requiredRung}
      </Typography>
      {escalators.length === 0 ? (
        <Typography variant="body2">
          Base rung for “{approval.actionLabel}”. No escalators fired.
        </Typography>
      ) : (
        <Stack spacing={0.5} sx={{ mt: 0.5 }}>
          {escalators.map((esc) => (
            <Typography key={esc.key} variant="body2" sx={{ display: 'flex', gap: 1 }}>
              <Box component="span" aria-hidden="true">▲</Box>
              {/* Rendered verbatim. The explanation is part of the audit record
                  and must never be assembled client-side. */}
              <Box component="span">
                {esc.reason}
                {esc.thresholdName ? (
                  <Typography component="span" variant="caption" sx={{ color: 'text.secondary', ml: 0.5 }}>
                    ({esc.thresholdName}
                    {esc.thresholdValue ? ` = ${esc.thresholdValue}` : ''})
                  </Typography>
                ) : null}
              </Box>
            </Typography>
          ))}
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            Base rung {approval.baseRung} → raised to {approval.requiredRung}. Escalators never lower a rung.
          </Typography>
        </Stack>
      )}
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Signature roster
// ---------------------------------------------------------------------------

/**
 * The signature roster.
 *
 * READ THE UNFILLED-SLOT COPY BEFORE CHANGING IT. An unfilled slot renders as
 * "awaiting a supervisor — must be a different person", NEVER "assigned to
 * <name>" and never with a prospective-signer avatar. There is no `cosignerId`
 * on the record by design: naming a co-signer at proposal time would let the
 * requesting banker choose their own reviewer, which is precisely the
 * self-dealing L2 exists to prevent. Presentation must not reintroduce a field
 * the data model deliberately omits.
 */
/**
 * Copy for a slot nobody has filled yet.
 *
 * Derived from the slot's stated rule rather than from any identity, and
 * deliberately vague about WHO: "a supervisor", not a name and not "you".
 */
export function unfilledSlotCopy(slot: SignatureSlot): string {
  const seniority = slot.minSeniority > 1 ? 'Awaiting a supervisor' : 'Awaiting a signature';
  return slot.mustDifferFrom.length > 0
    ? `${seniority} — must be a different person`
    : `${seniority} — anyone eligible under this policy`;
}

export const SignatureRoster: React.FC<{ approval: Approval; activeIdentityLabel?: string }> = ({
  approval,
  activeIdentityLabel,
}) => {
  // The slot the acting identity would fill: the first unfilled one, and only
  // when the SERVICE says this caller may sign. We never compute eligibility
  // here — `callerMaySign` is authoritative — we only point at the slot the
  // person is about to affect, so a two-session demo cannot leave anyone unsure
  // which signature their click binds.
  const callerSlotOrdinal =
    approval.callerMaySign
      ? approval.signatureSlots.find((slot) => !slot.filled)?.ordinal
      : undefined;

  return (
    <Box>
      <Typography variant="overline" sx={{ color: 'text.secondary' }}>
        Signatures
      </Typography>
      <Stack spacing={0.5} sx={{ mt: 0.5 }}>
        {approval.signatureSlots.map((slot) => (
          <Stack
            key={slot.ordinal}
            direction="row"
            spacing={1}
            sx={{ alignItems: 'center', flexWrap: 'wrap' }}
          >
            <Typography variant="body2" sx={{ minWidth: 24 }}>
              {slot.ordinal}.
            </Typography>
            {slot.filled ? (
              <>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {slot.signedByUsername || slot.signedBy}
                </Typography>
                <Chip size="small" color="success" variant="outlined" label="signed" />
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  {slot.signedAt ? new Date(slot.signedAt).toLocaleTimeString() : ''}
                </Typography>
              </>
            ) : (
              <>
                {/* A RULE, never a person. There is no `cosignerId` in the
                    domain — naming a reviewer at proposal time would let the
                    requester choose who checks their work, which is the
                    self-dealing pattern L2 exists to prevent. So the copy
                    describes eligibility, and the service decides who qualifies. */}
                <Typography variant="body2">{unfilledSlotCopy(slot)}</Typography>
                <Chip size="small" variant="outlined" label="◷ awaiting" />
                {slot.ordinal === callerSlotOrdinal && (
                  // Points at the acting identity's own slot — a "you", derived
                  // from `callerMaySign`, NOT a prospective assignment of anyone
                  // else. It disappears the moment the caller cannot sign.
                  <Chip
                    size="small"
                    color="primary"
                    variant="filled"
                    label={
                      activeIdentityLabel
                        ? `← you (${activeIdentityLabel}) sign here`
                        : '← you sign here'
                    }
                  />
                )}
              </>
            )}
          </Stack>
        ))}
        {approval.requiredSigners > 1 && (
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            You cannot sign twice. Separation of duties means different people, not different proofs —
            re-authenticating as yourself does not satisfy the second slot.
          </Typography>
        )}
      </Stack>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Payload rows, with the disclosure gate
// ---------------------------------------------------------------------------

interface PayloadTableProps {
  approval: Approval;
  onMaterialSeen: (path: string) => void;
  onEvidenceOpen?: (evidenceId: string) => void;
}

/**
 * Renders the payload the signature binds to.
 *
 * Material rows register with an IntersectionObserver: the `Sign` button will
 * not enable until each has actually been in the viewport. Not checkbox
 * theatre — an actual visibility precondition. If the payload is long enough to
 * scroll, you scroll it.
 */
const PayloadTable: React.FC<PayloadTableProps> = ({ approval, onMaterialSeen }) => {
  const rowRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') {
      // jsdom and older browsers have no observer. Failing OPEN here is correct:
      // a dwell gate that silently blocks signing forever in an environment we
      // did not anticipate turns a safety mechanism into an outage.
      approval.payload.filter((f) => f.material).forEach((f) => onMaterialSeen(f.path));
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const path = (entry.target as HTMLElement).dataset.path;
            if (path) onMaterialSeen(path);
          }
        });
      },
      { threshold: 0.9 }
    );

    Object.values(rowRefs.current).forEach((el) => {
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [approval.payload, onMaterialSeen]);

  return (
    <Box>
      <Typography variant="overline" sx={{ color: 'text.secondary' }}>
        You are signing
      </Typography>
      <Stack spacing={0.25} sx={{ mt: 0.5 }}>
        {approval.payload.map((field) => (
          <Stack
            key={field.path}
            direction="row"
            spacing={2}
            data-path={field.path}
            ref={(el: HTMLElement | null) => {
              if (field.material) rowRefs.current[field.path] = el;
            }}
            sx={{
              alignItems: 'baseline',
              py: 0.25,
              px: 0.5,
              borderRadius: 1,
              bgcolor: field.material ? 'action.hover' : 'transparent',
            }}
          >
            <Typography variant="body2" sx={{ minWidth: 160, color: 'text.secondary' }}>
              {field.label}
            </Typography>
            <Typography variant="body2" sx={{ fontWeight: field.material ? 700 : 400 }}>
              {formatFieldValue(field)}
            </Typography>
            {field.material && (
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                material
              </Typography>
            )}
          </Stack>
        ))}
      </Stack>
      <Stack direction="row" spacing={1} sx={{ mt: 1, justifyContent: 'flex-end' }}>
        <PayloadHashChip hash={approval.payloadHash} hashShort={approval.payloadHashShort} />
      </Stack>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

const EvidenceList: React.FC<{ approval: Approval; onOpen: (id: string) => void; defaultOpen: boolean }> = ({
  approval,
  onOpen,
  defaultOpen,
}) => {
  const [open, setOpen] = useState(defaultOpen);
  const { highlightNode } = useCopilot();

  if (approval.evidence.length === 0) return null;

  return (
    <Box>
      <Button size="small" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? 'Hide evidence' : `Evidence (${approval.evidence.length})`}
      </Button>
      <Collapse in={open}>
        <Stack spacing={0.5} sx={{ mt: 0.5 }}>
          {approval.evidence.map((item) => (
            <Stack key={item.id} direction="row" spacing={1} sx={{ alignItems: 'baseline' }}>
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                ▸
              </Typography>
              <Typography variant="body2">{item.label}</Typography>
              {item.sourceToolCallId && (
                <Link
                  component="button"
                  variant="caption"
                  onClick={() => {
                    // The trace is the citation index for the recommendation.
                    // Without this link it is ornamental.
                    highlightNode(item.sourceToolCallId);
                    onOpen(item.id);
                  }}
                >
                  show in trace
                </Link>
              )}
              {item.excerpt && (
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  {item.excerpt}
                </Typography>
              )}
            </Stack>
          ))}
        </Stack>
      </Collapse>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Agent opinions
// ---------------------------------------------------------------------------

const OpinionColumn: React.FC<{
  assessment: AgentAssessment;
  divergentFactors: string[];
  independent?: boolean;
}> = ({ assessment, divergentFactors, independent }) => (
  <Paper variant="outlined" sx={{ p: 1.5, flex: 1, minWidth: 260 }}>
    <Typography variant="overline" sx={{ color: 'text.secondary' }}>
      {assessment.role === 'supervisor' ? 'Supervisor agent' : 'Primary agent'}
      {independent ? ' (independent)' : ''}
    </Typography>
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1, flexWrap: 'wrap' }}>
      <Chip
        size="small"
        label={assessment.verdict || 'no verdict'}
        color={
          (assessment.verdict || '').toUpperCase() === 'DECLINE'
            ? 'error'
            : (assessment.verdict || '').toUpperCase() === 'APPROVE'
              ? 'success'
              : 'warning'
        }
      />
      {typeof assessment.confidence === 'number' && <ConfidenceBar value={assessment.confidence} />}
    </Stack>
    {assessment.rationale && <Typography variant="body2">{assessment.rationale}</Typography>}
    {assessment.keyFactors && assessment.keyFactors.length > 0 && (
      <Stack spacing={0.25} sx={{ mt: 1 }}>
        {assessment.keyFactors.map((factor) => (
          <Stack key={factor.label} direction="row" spacing={1} sx={{ alignItems: 'baseline' }}>
            <Typography variant="caption" sx={{ minWidth: 110, color: 'text.secondary' }}>
              {factor.label}
            </Typography>
            <Typography variant="caption" sx={{ fontWeight: factor.concern ? 700 : 400 }}>
              {factor.value}
              {factor.concern ? ' ✗' : ' ✓'}
            </Typography>
            {divergentFactors.includes(factor.label) && (
              <Typography variant="caption" sx={{ color: 'error.main', fontWeight: 700 }}>
                ← DIVERGENT
              </Typography>
            )}
          </Stack>
        ))}
      </Stack>
    )}
  </Paper>
);

/**
 * The disagreement banner.
 *
 * Full width above both columns, never a chip: when two independent reviews
 * reach opposite conclusions, that is the single most decision-relevant fact on
 * the screen. Doubled warning glyphs and the word DISAGREE carry it without
 * relying on the red.
 */
const DisagreementBanner: React.FC<{ disagreement: Disagreement }> = ({ disagreement }) => {
  if (disagreement.kind === 'none') return null;
  return (
    <Alert severity="error" icon={<WarningAmberIcon />} role="alert" sx={{ mb: 1 }}>
      <AlertTitle sx={{ fontWeight: 800 }}>
        ⚠⚠ THE TWO AGENTS DISAGREE. A HUMAN MUST DECIDE.
      </AlertTitle>
      {disagreement.summary}
      {disagreement.divergentFactors.length > 0 && (
        <Typography variant="body2" sx={{ mt: 0.5 }}>
          They diverge on: {disagreement.divergentFactors.join(', ')}.
        </Typography>
      )}
    </Alert>
  );
};

// ---------------------------------------------------------------------------
// The terminal (denied / executed) rendering
// ---------------------------------------------------------------------------

export const TerminalApprovalCard: React.FC<{ approval: Approval }> = ({ approval }) => {
  const copy = terminalCopy(approval.terminalReason, approval.terminalDetail);
  const { openApproval } = useCopilot();
  const [loadingReplacement, setLoadingReplacement] = useState(false);
  const diff =
    approval.previousPayload && approval.previousPayload.length > 0
      ? diffPayloads(approval.previousPayload, approval.payload)
      : [];

  const handleReview = async () => {
    if (!approval.supersededByApprovalId) return;
    setLoadingReplacement(true);
    try {
      await openApproval(approval.supersededByApprovalId);
    } finally {
      setLoadingReplacement(false);
    }
  };

  return (
    <Paper variant="outlined" sx={{ p: 2, borderColor: `${copy.severity}.main` }}>
      <Alert severity={copy.severity} sx={{ mb: 1 }}>
        <AlertTitle>{copy.badge}</AlertTitle>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {copy.headline}
        </Typography>
        {/* "Nothing was executed" leads, always. The banker's first fear on
            seeing this card is "did something half-happen?" — answer it before
            explaining anything else. */}
        <Typography variant="body2">{copy.body}</Typography>
      </Alert>

      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
        <PayloadHashChip hash={approval.payloadHash} hashShort={approval.payloadHashShort} />
        {approval.supersededByApprovalId && (
          <Chip size="small" variant="outlined" label={`replaced by ${approval.supersededByApprovalId}`} />
        )}
      </Stack>

      {diff.length > 0 && (
        <Box sx={{ mt: 1.5 }}>
          <Typography variant="overline" sx={{ color: 'text.secondary' }}>
            What changed — {countMaterialChanges(diff)} material change(s)
          </Typography>
          <Stack spacing={0.25}>
            {diff.map((row) => (
              <Stack key={row.path} direction="row" spacing={2} sx={{ alignItems: 'baseline' }}>
                <Typography variant="caption" sx={{ minWidth: 140, color: 'text.secondary' }}>
                  {row.label}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{
                    fontWeight: row.kind === 'unchanged' ? 400 : 700,
                    color: row.kind === 'unchanged' ? 'text.secondary' : 'warning.main',
                  }}
                >
                  {row.kind === 'unchanged'
                    ? String(row.next ?? '')
                    : `${String(row.previous ?? '—')} → ${String(row.next ?? '—')}`}
                </Typography>
                {row.kind !== 'unchanged' && (
                  <Typography variant="caption" sx={{ color: 'warning.main' }}>
                    {row.kind.toUpperCase()}
                  </Typography>
                )}
              </Stack>
            ))}
          </Stack>
        </Box>
      )}

      {/* The path forward. A blameless void (policy change, payload supersede)
          that only NAMES its replacement is a dead end; the banker did nothing
          wrong and must be able to reach the re-approval in one click, not hunt
          for an id. Only rendered when the server actually supplied a pointer —
          a fabricated link would be worse than none. */}
      {approval.supersededByApprovalId && (
        <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap' }}>
          <Button
            variant="contained"
            size="small"
            disabled={loadingReplacement}
            onClick={handleReview}
          >
            {loadingReplacement ? 'Loading…' : 'Review the new approval'}
          </Button>
          {copy.blameless && (
            <Typography variant="caption" sx={{ color: 'text.secondary', alignSelf: 'center' }}>
              A fresh signature is required against the new payload — reading this one does not carry over.
            </Typography>
          )}
        </Stack>
      )}
    </Paper>
  );
};

// ---------------------------------------------------------------------------
// L3 refusal
// ---------------------------------------------------------------------------

export const L3RefusalCard: React.FC<{ intent: string; onOpenClassicAdmin?: () => void }> = ({
  intent,
  onOpenClassicAdmin,
}) => (
  <Paper variant="outlined" sx={{ p: 2, borderColor: 'error.main' }}>
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1 }}>
      <GavelIcon color="error" />
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
        ⛔ Outside the harness — L3
      </Typography>
    </Stack>
    <Typography variant="body2">“{intent}” is an L3 action.</Typography>
    <Typography variant="body2" sx={{ mt: 0.5 }}>
      The agent may not perform this, and may not propose it.{' '}
      {/* The reassuring, verifiable detail. Keep it. */}
      <strong>No plan was formed and no tools were called.</strong>
    </Typography>
    <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 1 }}>
      L3 actions: deletions · role promotion · adverse action notices · changes to the Copilot&apos;s
      own policy or capability allowlist.
    </Typography>
    {onOpenClassicAdmin && (
      <Button size="small" sx={{ mt: 1 }} onClick={onOpenClassicAdmin}>
        Open Classic Admin → User Management
      </Button>
    )}
  </Paper>
);

// ---------------------------------------------------------------------------
// The card itself
// ---------------------------------------------------------------------------

export interface ApprovalCardProps {
  approval: Approval;
  streamStatus: StreamStatus;
  onSigned?: (dwellMs: number, evidenceOpened: boolean) => void;
  onDenied?: (dwellMs: number, evidenceOpened: boolean) => void;
}

const ApprovalCard: React.FC<ApprovalCardProps> = ({ approval, streamStatus, onSigned, onDenied }) => {
  const config = getCopilotConfig();
  const { sign, deny } = useCopilot();
  const now = useNow();
  const identity = useMemo(() => signingIdentity(), []);

  const [seenMaterial, setSeenMaterial] = useState<Set<string>>(() => new Set());
  const [openedAt] = useState(() => Date.now());
  const [evidenceOpened, setEvidenceOpened] = useState(false);
  const [denying, setDenying] = useState(false);
  const [denialReason, setDenialReason] = useState('');
  const [override, setOverride] = useState('');
  const [spotAnswer, setSpotAnswer] = useState('');
  const [spotSatisfied, setSpotSatisfied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>(undefined);

  const terminal = approval.status === 'denied' || approval.status === 'executed';
  const disagreement = useMemo(() => disagreementOf(approval.assessments), [approval.assessments]);
  const isL2 = approval.requiredRung === 'L2' || approval.requiredSigners > 1;

  const dwellMs = useMemo(
    () =>
      dwellRequirementMs({
        approval,
        disagreement: disagreement.kind,
        supersedes: Boolean(approval.supersedesApprovalId),
      }),
    [approval, disagreement.kind]
  );

  const materialPaths = useMemo(
    () => approval.payload.filter((f) => f.material).map((f) => f.path),
    [approval.payload]
  );

  const onMaterialSeen = useCallback((path: string) => {
    setSeenMaterial((prev) => {
      if (prev.has(path)) return prev;
      const next = new Set(prev);
      next.add(path);
      return next;
    });
  }, []);

  const disclosureSatisfied = materialPaths.every((p) => seenMaterial.has(p));
  const elapsed = now - openedAt;
  const dwellRemaining = Math.max(0, dwellMs - elapsed);
  const dwellSatisfied = dwellRemaining === 0;

  const spotCheckRequired = shouldSpotCheck(approval.id) && !isL2;
  const spotField = spotCheckRequired ? spotCheckField(approval) : undefined;
  const spotExpected = spotField ? spotCheckExpectedAnswer(spotField) : '';

  // Low agent confidence already escalates the rung; it should also force the
  // evidence panel open. The cases where the agent is least sure are exactly the
  // ones a fatigued human waves through, because they look like every other card.
  const lowestConfidence = approval.assessments.reduce<number>(
    (min, a) => (typeof a.confidence === 'number' ? Math.min(min, a.confidence) : min),
    1
  );
  const evidenceDefaultOpen = lowestConfidence < 0.75 || disagreement.kind !== 'none';

  const overrideRequired =
    isL2 && disagreement.kind !== 'none' && approval.assessments.some((a) => a.role === 'supervisor');
  const overrideValid = !overrideRequired || validateReason(override, config.overrideJustificationMinLength).valid;

  const streamSafe = canSignUnderStream(streamStatus);
  const spotOk = !spotField || spotSatisfied;

  const blockedReason = !approval.callerMaySign
    ? approval.callerMaySignReason || 'You may not sign this request.'
    : !streamSafe
      ? 'Reconnecting — cannot verify this is still the current payload.'
      : !disclosureSatisfied
        ? 'Scroll through the material fields above before signing.'
        : !dwellSatisfied
          ? `Enabled in 0:${String(Math.ceil(dwellRemaining / 1000)).padStart(2, '0')}`
          : !spotOk
            ? 'Answer the verification question above.'
            : !overrideValid
              ? 'State why you are overriding the supervisor agent.'
              : undefined;

  const canSign = !terminal && !busy && !blockedReason;

  if (terminal) return <TerminalApprovalCard approval={approval} />;

  const handleSign = async () => {
    setBusy(true);
    setError(undefined);
    try {
      // The hash the card DISPLAYED rides along. If the payload moved between
      // render and click the server rejects, which is the whole point of showing
      // it.
      await sign(approval.id, approval.payloadHash, overrideRequired ? override : undefined);
      if (onSigned) onSigned(Date.now() - openedAt, evidenceOpened);
    } catch (e) {
      setError(
        (e as { response?: { data?: { message?: string } } }).response?.data?.message ||
          'The signature was not accepted.'
      );
    } finally {
      setBusy(false);
    }
  };

  const handleDeny = async () => {
    const validation = validateReason(denialReason, config.denialReasonMinLength);
    if (!validation.valid) {
      setError(validation.message);
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      await deny(approval.id, denialReason);
      if (onDenied) onDenied(Date.now() - openedAt, evidenceOpened);
    } catch (e) {
      setError(
        (e as { response?: { data?: { message?: string } } }).response?.data?.message ||
          'The denial was not accepted.'
      );
    } finally {
      setBusy(false);
    }
  };

  // Variance in presentation for high-stakes items (§6.3): rubber-stamping is
  // muscle memory built on visual sameness. Bounded to accent + button order, so
  // it never crosses into a usability defect.
  const highStakes = isL2 || !isReversible(approval);

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        borderWidth: highStakes ? 2 : 1,
        borderColor: highStakes ? 'warning.main' : 'divider',
      }}
      aria-label={`Signature required: ${approval.actionLabel}`}
    >
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', mb: 0.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 800, letterSpacing: 0.5 }}>
          SIGNATURE REQUIRED
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        <AuthorityRungChip rung={approval.requiredRung} requiredSigners={approval.requiredSigners} />
      </Stack>

      {/* WHO is about to sign. In the two-session co-signature demo this is the
          line that stops a supervisor signing while unsure which browser identity
          the click binds to. Display only — eligibility is `callerMaySign`, and
          this banner is suppressed when the service says this caller may not sign,
          so it can never read as an invitation the policy engine would refuse. */}
      {approval.callerMaySign && identity.known && (
        <Alert severity={isL2 ? 'warning' : 'info'} icon={false} sx={{ py: 0.25, mb: 0.5 }}>
          <Typography variant="body2">
            Signing as <strong>{identity.displayName}</strong>
            {identity.email ? ` · ${identity.email}` : ''}
            {isL2 ? (
              <>
                {' '}— you are providing the{' '}
                <strong>independent supervisor co-signature</strong>. It counts only because you are
                a different identity from the requester
                {approval.requesterUsername ? ` (${approval.requesterUsername})` : ''}.
              </>
            ) : null}
          </Typography>
        </Alert>
      )}

      <Typography variant="body1" sx={{ fontWeight: 600 }}>
        {approval.actionLabel}
      </Typography>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', my: 0.5, flexWrap: 'wrap' }}>
        <ApprovalCountdown expiresAt={approval.expiresAt} createdAt={approval.createdAt} />
        <Chip size="small" variant="outlined" label={approval.actionId} />
        <Chip
          size="small"
          variant="outlined"
          color={isReversible(approval) ? 'default' : 'warning'}
          label={isReversible(approval) ? 'reversible' : 'irreversible ⚠'}
        />
      </Stack>

      <Divider sx={{ my: 1 }} />
      <EscalatorExplainer approval={approval} />

      <Divider sx={{ my: 1 }} />
      <PayloadTable approval={approval} onMaterialSeen={onMaterialSeen} />

      {approval.assessments.length > 0 && (
        <>
          <Divider sx={{ my: 1 }} />
          <DisagreementBanner disagreement={disagreement} />
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1}>
            {approval.assessments.map((assessment) => (
              <OpinionColumn
                key={`${assessment.role}-${assessment.agentId || assessment.agentName || 'agent'}`}
                assessment={assessment}
                divergentFactors={disagreement.divergentFactors}
                independent={assessment.role === 'supervisor'}
              />
            ))}
          </Stack>
          {isL2 && (
            <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}>
              The supervisor agent formed its opinion without visibility into the primary&apos;s
              recommendation.
            </Typography>
          )}
        </>
      )}

      <Divider sx={{ my: 1 }} />
      <EvidenceList
        approval={approval}
        defaultOpen={evidenceDefaultOpen}
        onOpen={() => setEvidenceOpened(true)}
      />

      <Divider sx={{ my: 1 }} />
      <SignatureRoster approval={approval} activeIdentityLabel={identity.known ? identity.displayName : undefined} />

      {spotField && !spotSatisfied && (
        <Alert severity="info" sx={{ mt: 1 }}>
          <AlertTitle>Quick verification</AlertTitle>
          Enter the last 4 characters of <strong>{spotField.label}</strong> shown above.
          <Stack direction="row" spacing={1} sx={{ mt: 1, alignItems: 'center' }}>
            <TextField
              size="small"
              value={spotAnswer}
              onChange={(e) => setSpotAnswer(e.target.value)}
              slotProps={{ htmlInput: { 'aria-label': 'verification answer' } }}
            />
            <Button
              size="small"
              onClick={() => {
                if (spotAnswer.trim() === spotExpected) {
                  setSpotSatisfied(true);
                  setError(undefined);
                } else {
                  // A wrong answer never blocks — it re-renders and resets
                  // attention. Punishing a typo teaches people to hate the tool.
                  setSpotAnswer('');
                  setSeenMaterial(new Set());
                  setError('That does not match. The material fields are highlighted again.');
                }
              }}
            >
              Check
            </Button>
          </Stack>
        </Alert>
      )}

      {overrideRequired && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="body2" sx={{ fontWeight: 600, color: 'error.main' }}>
            ⚠ You are overriding the supervisor agent&apos;s verdict. State why:
          </Typography>
          <TextField
            fullWidth
            multiline
            minRows={2}
            size="small"
            value={override}
            onChange={(e) => setOverride(e.target.value)}
            placeholder={`At least ${config.overrideJustificationMinLength} characters — stored on your signature.`}
          />
        </Box>
      )}

      {denying && (
        <Box sx={{ mt: 1 }}>
          <TextField
            fullWidth
            multiline
            minRows={2}
            size="small"
            label="Reason for denial"
            value={denialReason}
            onChange={(e) => setDenialReason(e.target.value)}
            placeholder={`At least ${config.denialReasonMinLength} characters. This is the audit record and the training signal.`}
          />
        </Box>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}

      {!streamSafe && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          Live updates are interrupted. Signing is disabled until the connection is verified —
          signing against a payload we cannot confirm is current is the exact risk the payload hash
          exists to prevent.
        </Alert>
      )}

      <Stack
        direction={highStakes ? 'row-reverse' : 'row'}
        spacing={1}
        sx={{ mt: 1.5, justifyContent: 'flex-end', alignItems: 'center', flexWrap: 'wrap' }}
      >
        {/* Denial has the same visual weight as signing. A UI where denial is
            harder than approval has its thumb on the scale. */}
        <Button
          color="error"
          variant="outlined"
          disabled={busy}
          onClick={() => (denying ? handleDeny() : setDenying(true))}
        >
          {denying ? 'Confirm denial' : 'Deny'}
        </Button>
        <Tooltip title={blockedReason || ''}>
          <Box component="span">
            <Button variant="contained" disabled={!canSign} onClick={handleSign}>
              {/* Never the word "Approve". That is reserved for a thing agents
                  may never do; using it as a generic button label cheapens the
                  distinction this whole epic teaches. */}
              Sign — {approval.actionLabel}
              {!dwellSatisfied && dwellRemaining > 0
                ? ` (enabled in 0:${String(Math.ceil(dwellRemaining / 1000)).padStart(2, '0')})`
                : ''}
            </Button>
          </Box>
        </Tooltip>
      </Stack>

      {blockedReason && (
        <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}>
          {blockedReason}
        </Typography>
      )}
    </Paper>
  );
};

export default ApprovalCard;
