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
  streamGateReason,
  streamGateReasonBrief,
  SignatureSlot,
  StreamStatus,
} from './types';
import {
  AgreementKind,
  Disagreement,
  countMaterialChanges,
  diffPayloads,
  disagreementOf,
  dwellRequirementMs,
  FactorComparison,
  formatFieldValue,
  isReversible,
  shouldSpotCheck,
  spotCheckExpectedAnswer,
  spotCheckField,
  terminalCopy,
  validateReason,
} from './approvalPolicy';
import { AuthorityRungChip, ApprovalCountdown, PayloadHashChip } from './CopilotPrimitives';
import {
  approvalHeadline,
  subjectAbsence,
  whyThisRung,
  expiryConsequence,
  signingClosed,
  DENY_IS_FINAL,
} from './approvalNarrative';
import { verdictPresentation } from './supervisorVerdict';
import { factorPresentation, FACTOR_COMPARISON_UNAVAILABLE } from './supervisorFactors';
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
        /* §6.4: a base-rung action fires no escalator, so there is no server-authored
           template to render. "No escalators fired" described the code path rather than the
           decision. This map is client-side by Danny's explicit assignment; the escalator
           branch below is still rendered verbatim because THAT text is audit record. */
        <Typography variant="body2">
          {whyThisRung(approval.actionId, approval.requiredRung) ??
            `Base rung for “${approval.actionLabel}”. No escalators fired.`}
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

/**
 * The slot the acting identity would fill: the first unfilled one, and only when
 * the SERVICE says this caller may sign. Eligibility is never computed here —
 * `callerMaySign` is authoritative. This only points at the slot the person is
 * about to affect.
 *
 * "First unfilled" is sound rather than merely convenient: the opening slot
 * carries the lowest `minSeniority` and an empty `mustDifferFrom`, so anyone
 * eligible for a later slot is also eligible for that one. There is no case
 * where a caller skips a slot they could have filled.
 *
 * Note the ordinals are NOT array indices — the demo fixture numbers its slots
 * 1 and 2 — so nothing here may key off `ordinal === 0`.
 */
export function callerSignatureSlot(approval: Approval): SignatureSlot | undefined {
  if (!approval.callerMaySign) return undefined;
  return approval.signatureSlots.find((slot) => !slot.filled);
}

/**
 * What this person is actually about to do, in their words rather than the
 * policy engine's.
 *
 * The previous copy branched on `isL2` alone and so told EVERY L2 signer they
 * were "providing the independent supervisor co-signature ... because you are a
 * different identity from the requester". For the requester filling the opening
 * slot that is simply false, and it contradicted itself in one sentence:
 * Brian, signed in as `banker`, was told his signature counted because he was
 * not `banker`.
 *
 * The truth is in the slots. Whether this signature opens the approval or
 * closes it is a property of how many remain, not of the rung.
 *
 * Returns the sentence that FOLLOWS the bound identity. The identity itself is
 * rendered separately and always, because making the bound identity
 * unmistakable is the reason this banner exists.
 */
export function signingAttestation(
  approval: Approval,
  identityId?: string,
  now: number = Date.now()
): string {
  // A closed record has no future signature to describe. Previously this keyed only on the
  // SLOTS, so a lapsed L1 with its single slot still unfilled reached the `slots.length <= 1`
  // branch and told a banker "Yours is the only signature needed" about a dead record.
  if (signingClosed(approval, now)) return '';

  const slots = approval.signatureSlots;
  const remaining = slots.filter((slot) => !slot.filled).length;

  // Nothing derivable — say only what we know, which is who is signing.
  if (remaining === 0) return '';

  if (slots.length <= 1) {
    return 'Yours is the only signature needed — this goes ahead once you sign.';
  }

  if (remaining === 1) {
    const first = slots.find((slot) => slot.filled);
    const who = first?.signedByUsername;
    const position = slots.length === 2 ? 'the second signature' : 'the final signature';
    return who
      ? `You are ${position} — ${who} signed first. Once you sign, this goes ahead.`
      : `You are ${position}. Once you sign, this goes ahead.`;
  }

  const others = remaining - 1;
  const wait =
    others === 1
      ? 'It does not go ahead until a second person signs'
      : `It does not go ahead until ${others} more people sign`;

  // Only claim the caller is the requester when we can actually check it. The
  // identity id is the local part of the signed-in email and the record carries
  // a username; when they do not correspond we fall back to the neutral wording,
  // which is true either way.
  const callerIsRequester =
    Boolean(identityId) &&
    Boolean(approval.requesterUsername) &&
    identityId!.toLowerCase() === approval.requesterUsername!.toLowerCase();

  if (callerIsRequester) {
    return `You raised this request, so you are signing it first. ${wait}, and that person cannot be you.`;
  }
  return `You are signing first. ${wait}.`;
}

export const SignatureRoster: React.FC<{ approval: Approval; activeIdentityLabel?: string }> = ({
  approval,
  activeIdentityLabel,
}) => {
  // The slot the acting identity would fill. Shared with the attestation banner
  // so the two can never disagree about which signature the click binds.
  const callerSlotOrdinal = callerSignatureSlot(approval)?.ordinal;

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
  /** "You are signing" is false once the record is closed; the disclosure still matters. */
  heading?: string;
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
const PayloadTable: React.FC<PayloadTableProps> = ({ approval, onMaterialSeen, heading }) => {
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
        {heading ?? 'You are signing'}
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
            <Box key={item.id}>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'baseline' }}>
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

              {/*
                PROVISIONAL PRESENTATION — the plumbing is the point here, not the
                design. Danny's card specification will decide how a finding
                should read; this exists so the values are on screen instead of
                discarded, and so that spec has real data to land against. It
                reuses `formatFieldValue`, the payload rows' formatter, rather
                than inventing a second display vocabulary. Replaceable in one
                place.
              */}
              {item.findings.length > 0 && (
                <Stack spacing={0.25} sx={{ mt: 0.25, ml: 2.5 }}>
                  {item.findings.map((field) => (
                    <Stack
                      key={`${item.id}:${field.path}`}
                      direction="row"
                      spacing={1}
                      sx={{ alignItems: 'baseline' }}
                    >
                      <Typography
                        variant="caption"
                        sx={{ minWidth: 120, color: 'text.secondary' }}
                      >
                        {field.label}
                      </Typography>
                      <Typography variant="caption">{formatFieldValue(field)}</Typography>
                    </Stack>
                  ))}
                </Stack>
              )}
            </Box>
          ))}
        </Stack>
      </Collapse>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Agent opinions
// ---------------------------------------------------------------------------

/**
 * The caveat travels with the number, because the number is the misleading part.
 *
 * Measured across 42 runs: min 0.83, median 0.94, max 0.98. The coin-flip case —
 * identical bytes producing opposite verdicts — sat at 0.82-0.96, overlapping the
 * rock-solid one. So it never goes low and it does not separate a stable case
 * from an unstable one, while being shown to a human deciding whether to sign.
 * It is displayed as PROSE and nothing else: no bar, no colour scale, no rank,
 * no threshold (ruling §P7.2).
 */
export const SELF_REPORTED_CONFIDENCE_CAVEAT =
  "The model's own stated confidence. It is not a reliability measure: observed 0.83-0.98 across every run, and identical inputs have produced opposite verdicts at overlapping values. Nothing on this screen is ranked, ordered or gated on it.";

/**
 * Attribution (§P7.1): which decider, which model, which exact bytes.
 *
 * The record cannot be reproducible — the call is nondeterministic — so it claims
 * to be ATTRIBUTABLE instead. `mode` is the field that separates a judgement from
 * a script, which is the exact confusion this whole feature was built to end, and
 * the deployment id is how a reader sees for themselves that the "independent"
 * second opinion came from the same base model as the primary.
 */
const AssessmentAttribution: React.FC<{ assessment: AgentAssessment }> = ({ assessment }) => {
  const parts: string[] = [];
  if (assessment.mode) parts.push(`mode ${assessment.mode}`);
  if (assessment.modelDeployment) parts.push(assessment.modelDeployment);
  if (assessment.promptSha256) parts.push(`prompt ${shortSha(assessment.promptSha256)}`);
  if (assessment.responseSha256) parts.push(`reply ${shortSha(assessment.responseSha256)}`);
  if (parts.length === 0) return null;
  return (
    <Typography
      variant="caption"
      data-testid={`assessment-attribution-${assessment.role ?? 'unknown'}`}
      sx={{ display: 'block', mt: 1, color: 'text.secondary', fontFamily: 'monospace' }}
    >
      {parts.join(' · ')}
    </Typography>
  );
};

function shortSha(sha: string): string {
  const hex = sha.startsWith('sha256:') ? sha.slice(7) : sha;
  return hex.slice(0, 8);
}

const OpinionColumn: React.FC<{
  assessment: AgentAssessment;
  divergentFactors: string[];
  factorComparison: FactorComparison;
  independent?: boolean;
}> = ({ assessment, divergentFactors, factorComparison, independent }) => {
  // Label, colour and rank all come from the ONE lookup keyed on the server's own
  // vocabulary. The previous inline ternary compared against 'APPROVE' and
  // 'DECLINE' — one of which the server never emits and the other of which it
  // emitted for the WRONG verdict — and swept everything else, `decline`
  // included, into the same amber "warning" arm.
  const verdict = verdictPresentation(assessment.verdict);
  return (
  <Paper variant="outlined" sx={{ p: 1.5, flex: 1, minWidth: 260 }}>
    <Typography variant="overline" sx={{ color: 'text.secondary' }}>
      {assessment.role === 'supervisor' ? 'Supervisor agent' : 'Primary agent'}
      {independent ? ' (independent)' : ''}
    </Typography>
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1, flexWrap: 'wrap' }}>
      <Tooltip title={verdict.description}>
        <Chip
          size="small"
          label={verdict.label}
          color={verdict.color}
          variant={verdict.variant}
          aria-label={verdict.description}
          data-testid={`verdict-chip-${assessment.role ?? 'unknown'}`}
          data-verdict-color={verdict.color}
          data-verdict-severity={verdict.severity}
        />
      </Tooltip>
      {typeof assessment.selfReportedConfidence === 'number' && (
        <Tooltip title={SELF_REPORTED_CONFIDENCE_CAVEAT}>
          <Typography
            variant="caption"
            data-testid={`self-reported-confidence-${assessment.role ?? 'unknown'}`}
            aria-label={`self-reported confidence ${assessment.selfReportedConfidence.toFixed(2)}. ${SELF_REPORTED_CONFIDENCE_CAVEAT}`}
            sx={{ color: 'text.secondary' }}
          >
            self-reported confidence {assessment.selfReportedConfidence.toFixed(2)}
          </Typography>
        </Tooltip>
      )}
    </Stack>
    {assessment.failure && (
      <Alert
        severity="error"
        variant="outlined"
        role="alert"
        sx={{ mb: 1, py: 0 }}
        data-testid={`assessment-failure-${assessment.role ?? 'unknown'}`}
        data-failure={assessment.failure}
      >
        <Typography variant="caption" sx={{ fontWeight: 800 }}>
          NO ASSESSMENT WAS FORMED — {assessment.failure}
          {assessment.failureReason ? ` (${assessment.failureReason})` : ''}
        </Typography>
      </Alert>
    )}
    {assessment.rationale && <Typography variant="body2">{assessment.rationale}</Typography>}
    {assessment.unverified && assessment.unverified.length > 0 && (
      <Stack spacing={0.25} sx={{ mt: 1 }}>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 700 }}>
          Could not be established from the evidence:
        </Typography>
        {assessment.unverified.map((item) => (
          <Typography key={item} variant="caption" data-testid="unverified-row" sx={{ color: 'warning.main' }}>
            ? {item}
          </Typography>
        ))}
      </Stack>
    )}
    {assessment.keyFactors && assessment.keyFactors.length > 0 && (
      <Stack spacing={0.25} sx={{ mt: 1 }}>
        {assessment.keyFactors.map((factor) => {
          const f = factorPresentation(factor);
          // A failed supervisor call is not a factor. It is rendered as the failure it
          // is — error-coloured, bold, ahead of any real factor in weight — and never
          // with a tick, a value, or a divergence flag.
          if (f.unavailable) {
            return (
              <Typography
                key={factor.label}
                variant="caption"
                data-testid="factor-unavailable"
                aria-label={f.description}
                sx={{ color: 'error.main', fontWeight: 700 }}
              >
                ⚠ {f.text}
              </Typography>
            );
          }
          return (
            <Stack key={factor.label} direction="row" spacing={1} sx={{ alignItems: 'baseline' }}>
              <Typography
                variant="caption"
                data-testid="factor-row"
                aria-label={f.description}
                sx={{
                  // Without a measured value the statement IS the row, so it is not
                  // squeezed into a 110px label column with nothing beside it.
                  minWidth: f.value ? 110 : undefined,
                  color: f.value ? 'text.secondary' : 'text.primary',
                  fontWeight: factor.concern === true ? 700 : 400,
                }}
              >
                {f.text}
                {/* No glyph when the agent did not classify the factor. A ✓ on an
                    unstated judgement is an assertion nobody made. */}
                {f.value ? null : f.glyph ? ` ${f.glyph}` : null}
              </Typography>
              {f.value && (
                <Typography variant="caption" sx={{ fontWeight: factor.concern === true ? 700 : 400 }}>
                  {f.value}
                  {f.glyph ? ` ${f.glyph}` : null}
                </Typography>
              )}
              {divergentFactors.includes(factor.label) && (
                <Typography variant="caption" sx={{ color: 'error.main', fontWeight: 700 }}>
                  ← DIVERGENT
                </Typography>
              )}
            </Stack>
          );
        })}
        {/* Where the ← DIVERGENT flags would have been. A divergence indicator that
            renders nothing looks exactly like one that compared the two sides and
            found them consistent — "we could not check" wearing the face of "we
            checked and it was fine". So when the comparison could not run, the card
            says so in its place, in the same register as the row it replaces.
            Informational, not error-coloured: nothing failed here, the primary
            simply stated no factors to compare against, and `error.main` is
            reserved for a supervisor call that actually failed. */}
        {independent && factorComparison === 'primary_stated_no_factors' && (
          <Typography
            variant="caption"
            data-testid="factor-comparison-unavailable"
            aria-label={FACTOR_COMPARISON_UNAVAILABLE}
            sx={{ color: 'info.main', fontWeight: 700, mt: 0.5 }}
          >
            ℹ {FACTOR_COMPARISON_UNAVAILABLE}
          </Typography>
        )}
      </Stack>
    )}
    <AssessmentAttribution assessment={assessment} />
  </Paper>
  );
};

/**
 * The disagreement banner.
 *
 * Full width above both columns, never a chip: when two independent reviews
 * reach opposite conclusions, that is the single most decision-relevant fact on
 * the screen. Doubled warning glyphs and the word DISAGREE carry it without
 * relying on the red.
 */
const BANNER: Record<AgreementKind, { severity: 'error' | 'warning' | 'success'; glyph: string }> = {
  // `not_comparable` is error-severity ON PURPOSE, and it is not the mildest arm.
  // The mild default is what caused the original defect: two ABSENT verdicts
  // rendered "Independent review reached the same verdict". A dead pipeline must
  // never be able to display as consensus, and it must not display as a shrug
  // either — it is a broken control on an L2 banking action.
  diverge: { severity: 'error', glyph: '⚠⚠' },
  not_comparable: { severity: 'error', glyph: '⛔' },
  not_reviewed: { severity: 'warning', glyph: '⛔' },
  agree: { severity: 'success', glyph: '✓' },
};

const DisagreementBanner: React.FC<{ disagreement: Disagreement; showUnreviewed: boolean }> = ({
  disagreement,
  showUnreviewed,
}) => {
  // On an L1 card nobody promised an independent review, so its absence is not
  // news. Everywhere a second opinion is expected, its absence is the headline.
  if (disagreement.kind === 'not_reviewed' && !showUnreviewed) return null;
  const banner = BANNER[disagreement.kind];
  return (
    <Alert
      severity={banner.severity}
      icon={<WarningAmberIcon />}
      role="alert"
      sx={{ mb: 1 }}
      data-testid="agreement-banner"
      data-agreement={disagreement.kind}
    >
      <AlertTitle sx={{ fontWeight: 800 }}>
        {banner.glyph} {disagreement.title}
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
  // Terminality is NOT a status. An unswept record stays `pending` with `callerMaySign: true`
  // after its window closes, which is exactly how the signing affordance survived on a record
  // that could never be signed.
  const closure = signingClosed(approval, now);
  const disagreement = useMemo(() => disagreementOf(approval), [approval]);
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

  // The evidence panel opens whenever the two positions did not concur — which
  // includes the case where one of them does not exist.
  //
  // What used to be here: `lowestConfidence < 0.75 || ...`. That was a numeric
  // threshold on self-reported confidence deciding what a banker is shown, i.e.
  // something hidden or revealed because a number crossed a line, on a number
  // measured at 0.83-0.98 that never crossed it. Ruled out (§P7.2(2)): the
  // threshold is gone rather than retuned, because there is no honest value for
  // it. `concurs` is true only for a stated `agree`.
  const evidenceDefaultOpen = !disagreement.concurs;

  // An override justification is required whenever a supervisor opinion was
  // expected and the two did not concur. `not_comparable` counts: signing past a
  // review that never happened deserves at least as much of a stated reason as
  // signing past one that disagreed.
  const overrideRequired =
    isL2 && !disagreement.concurs && approval.assessments.some((a) => a.role === 'supervisor');
  const overrideValid = !overrideRequired || validateReason(override, config.overrideJustificationMinLength).valid;

  const streamSafe = canSignUnderStream(streamStatus);
  const spotOk = !spotField || spotSatisfied;

  const blockedReason = !approval.callerMaySign
    ? approval.callerMaySignReason || 'You may not sign this request.'
    : !streamSafe
      ? streamGateReasonBrief(streamStatus)
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
      aria-label={
        closure ? `${closure.header}: ${approval.actionLabel}` : `Signature required: ${approval.actionLabel}`
      }
    >
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', mb: 0.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 800, letterSpacing: 0.5 }}>
          {closure ? closure.header : 'SIGNATURE REQUIRED'}
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        <AuthorityRungChip rung={approval.requiredRung} requiredSigners={approval.requiredSigners} />
      </Stack>

      {/* WHO is about to sign, and WHAT their signature does. In the two-session
          co-signature demo this is the line that stops a supervisor signing while
          unsure which browser identity the click binds to, so the identity stays
          first and bold in every case. Display only — eligibility is
          `callerMaySign`, and this banner is suppressed when the service says
          this caller may not sign, so it can never read as an invitation the
          policy engine would refuse.

          The second sentence is derived from the SLOTS, not the rung. Branching
          on `isL2` alone told the requester they were the independent
          co-signature, which is false and was self-contradictory. */}
      {/* The outcome, stated before anything else on a closed record. A banker's first
          question on a dead approval is whether any of it happened. */}
      {closure && (
        <Alert severity={closure.kind === 'signed' || closure.kind === 'executed' ? 'success' : 'info'}
               sx={{ mb: 1 }}>
          <Typography variant="body2">{closure.note}</Typography>
        </Alert>
      )}

      {!closure && approval.callerMaySign && identity.known && (
        <Alert severity={isL2 ? 'warning' : 'info'} icon={false} sx={{ py: 0.25, mb: 0.5 }}>
          <Typography variant="body2">
            Signing as <strong>{identity.displayName}</strong>
            {identity.email ? ` · ${identity.email}` : ''}.{' '}
            {signingAttestation(approval, identity.id)}
          </Typography>
        </Alert>
      )}

      <Typography variant="body1" sx={{ fontWeight: 600 }}>
        {approvalHeadline(approval)}
      </Typography>
      {subjectAbsence(approval) && (
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.25 }}>
          {subjectAbsence(approval)}
        </Typography>
      )}
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
      {/* §3.8 — the countdown chip states a mechanism; this states the consequence, with a
          wall-clock time, and closes the "does it fire anyway?" question a banker would
          otherwise have to ask someone. */}
      {expiryConsequence(approval, now) && (
        <Typography variant="body2" sx={{ color: 'text.secondary', mb: 0.5 }}>
          {expiryConsequence(approval, now)}
        </Typography>
      )}

      <Divider sx={{ my: 1 }} />
      <EscalatorExplainer approval={approval} />

      <Divider sx={{ my: 1 }} />
      <PayloadTable
        approval={approval}
        onMaterialSeen={onMaterialSeen}
        heading={closure ? 'What was proposed' : undefined}
      />

      {approval.assessments.length > 0 && (
        <>
          <Divider sx={{ my: 1 }} />
          <DisagreementBanner disagreement={disagreement} showUnreviewed={isL2} />
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1}>
            {approval.assessments.map((assessment) => (
              <OpinionColumn
                key={`${assessment.role}-${assessment.agentId || assessment.agentName || 'agent'}`}
                assessment={assessment}
                divergentFactors={disagreement.divergentFactors}
                factorComparison={disagreement.factorComparison}
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

      {!closure && overrideRequired && (
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

      {!closure && denying && (
        <Box sx={{ mt: 1 }}>
          {/* Priority 3 / option A. Brian burned three approvals learning this by doing it.
              The warning has to precede the irreversible click, not confirm it afterwards. */}
          <Alert severity="warning" sx={{ mb: 1 }}>
            {DENY_IS_FINAL}
          </Alert>
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

      {!closure && !streamSafe && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          {streamGateReason(streamStatus)} Signing against a payload we cannot confirm is current
          is the exact risk the payload hash exists to prevent.
        </Alert>
      )}

      {/* Every signing affordance is gated on `closure`, not just the Sign button. A dead
          record that still offers Deny is the same lie in a different font. */}
      {!closure && (
      <>
      {/* THREE VERBS, NOT TWO. Brian authorised counter-propose (option B); Danny's ruling is
          that the row must be built to hold it now and rebuilt never. The leading slot is that
          third verb's place — deliberately empty rather than a disabled button, because
          shipping a dead control teaches a banker that the card lies about what it can do.
          Sign and Deny stay grouped at the trailing edge so the destructive pair keeps its
          existing muscle memory when the third verb arrives to their left. */}
      <Stack
        direction="row"
        spacing={1}
        sx={{ mt: 1.5, justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' }}
      >
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }} />
        <Stack
          direction={highStakes ? 'row-reverse' : 'row'}
          spacing={1}
          sx={{ justifyContent: 'flex-end', alignItems: 'center', flexWrap: 'wrap' }}
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
      </Stack>
      </>
      )}

      {!closure && blockedReason && (
        <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}>
          {blockedReason}
        </Typography>
      )}
    </Paper>
  );
};

export default ApprovalCard;
