/**
 * Approval presentation policy — the rules the approval surface enforces.
 *
 * Everything here is CLIENT-SIDE MIRRORING of a server-side rule, with one
 * exception (the dwell gate, which is purely a UI control and has no server
 * counterpart). The distinction matters and is worth stating once:
 *
 *   - Denial-reason validation, signing eligibility, separation of duties, and
 *     the payload hash are all enforced by `authority-service`. Mirrored here
 *     ONLY so the banker learns the rule instead of hitting a 403, and so the
 *     UI feels responsive. Never for enforcement. The API returns 400/403 on
 *     invalid input regardless of anything in this file.
 *
 *   - The dwell gate and the disclosure gate exist only here, because they
 *     regulate human attention, and attention is not a thing a backend can
 *     measure. They are the anti-fatigue mechanisms (§6) that scale cost with
 *     stakes.
 */

import {
  AgentAssessment,
  Approval,
  PayloadField,
  TerminalReason,
} from './types';
import { getCopilotConfig } from '../../config/copilotConfig';

// ---------------------------------------------------------------------------
// Terminal reasons — all four must render distinctly
// ---------------------------------------------------------------------------

export interface TerminalCopy {
  /** Short badge text. Never the bare word "Denied". */
  badge: string;
  headline: string;
  /** Answers "did something half-happen?" in the first sentence. Always. */
  body: string;
  severity: 'error' | 'warning' | 'info';
  /** True when the banker did nothing wrong and the ground moved under them. */
  blameless: boolean;
}

/**
 * The four denial causes share one status, so branching on status alone renders
 * a policy-driven void as a rejection. Each gets its own copy, and each names
 * the cause.
 */
export function terminalCopy(
  reason: TerminalReason | undefined,
  detail?: string
): TerminalCopy {
  switch (reason) {
    case 'HUMAN_DENIED':
      return {
        badge: 'DENIED BY A REVIEWER',
        headline: 'A reviewer denied this request.',
        body: detail
          ? `Nothing was executed. Reason given: “${detail}”`
          : 'Nothing was executed.',
        severity: 'error',
        blameless: false,
      };

    case 'POLICY_RUNG_ESCALATED':
      return {
        badge: 'POLICY CHANGED — SIGNATURE VOID',
        headline: 'The approval policy changed while this was pending.',
        body:
          (detail ? `${detail} ` : '') +
          'Any signature already given no longer counts and has NOT been applied. ' +
          'Nothing was executed. This is not a rejection of your judgement — the ' +
          'threshold moved, so the request needs re-approval at the higher rung.',
        severity: 'warning',
        blameless: true,
      };

    case 'PAYLOAD_SUPERSEDED':
      return {
        badge: 'SUPERSEDED — THE PROPOSAL CHANGED',
        headline: 'Your signature no longer counts — the proposal changed.',
        body:
          'Nothing was executed. The agent revised its plan, so the payload you ' +
          'reviewed is not the payload that would run. A new signature is required ' +
          'against the new payload.',
        severity: 'warning',
        blameless: true,
      };

    case 'TTL_EXPIRED':
      return {
        badge: 'SIGNATURE WINDOW CLOSED',
        headline: 'This expired before it was signed, so it was denied.',
        body:
          'Nothing was executed. Expiry is always a denial — there is no ' +
          'configuration in which a countdown reaching zero causes an action to occur.',
        severity: 'info',
        blameless: true,
      };

    default:
      return {
        badge: 'TERMINAL — REASON MISSING',
        headline: 'This request ended without a recorded reason.',
        body:
          'Nothing was executed. A denial without a terminalReason is a defect: ' +
          'report it rather than re-proposing blindly.',
        severity: 'error',
        blameless: true,
      };
  }
}

// ---------------------------------------------------------------------------
// Reversibility and dwell
// ---------------------------------------------------------------------------

/**
 * Reversibility is read from the payload, not guessed from the action id.
 *
 * Default when absent is IRREVERSIBLE. Guessing "probably reversible" biases the
 * default toward less friction on exactly the items we know least about.
 */
export function isReversible(approval: Approval): boolean {
  const field = approval.payload.find((f) => /(^|\.)reversible$/i.test(f.path));
  if (!field) return false;
  if (typeof field.value === 'boolean') return field.value;
  if (typeof field.value === 'string') return /^(true|yes|y)$/i.test(field.value.trim());
  return false;
}

export type DisagreementKind = 'none' | 'verdict' | 'confidence' | 'both';

export interface Disagreement {
  kind: DisagreementKind;
  summary: string;
  divergentFactors: string[];
}

/**
 * Detects divergence between the primary and supervisor assessments.
 *
 * Client-side derivation is acceptable here — and only here — because it is
 * descriptive rather than authoritative: it decides how loudly to render two
 * verdicts that are both already on screen. It grants nothing and gates nothing.
 */
export function disagreementOf(assessments: AgentAssessment[]): Disagreement {
  const primary = assessments.find((a) => a.role === 'primary');
  const supervisor = assessments.find((a) => a.role === 'supervisor');

  if (!primary || !supervisor) {
    return { kind: 'none', summary: '', divergentFactors: [] };
  }

  const verdictDiffers =
    (primary.verdict || '').toUpperCase() !== (supervisor.verdict || '').toUpperCase();

  const pc = typeof primary.confidence === 'number' ? primary.confidence : undefined;
  const sc = typeof supervisor.confidence === 'number' ? supervisor.confidence : undefined;
  const confidenceDiffers = pc !== undefined && sc !== undefined && Math.abs(pc - sc) >= 0.2;

  const divergentFactors: string[] = [];
  const supervisorFactors = supervisor.keyFactors || [];
  const primaryFactors = primary.keyFactors || [];
  for (const factor of supervisorFactors) {
    const match = primaryFactors.find((f) => f.label === factor.label);
    if (!match || Boolean(match.concern) !== Boolean(factor.concern)) {
      divergentFactors.push(factor.label);
    }
  }

  const kind: DisagreementKind = verdictDiffers && confidenceDiffers
    ? 'both'
    : verdictDiffers
      ? 'verdict'
      : confidenceDiffers
        ? 'confidence'
        : 'none';

  const summary =
    kind === 'none'
      ? 'Independent review reached the same verdict.'
      : verdictDiffers
        ? `Primary recommends ${primary.verdict}. Supervisor recommends ${supervisor.verdict}.`
        : 'The two agents agree on the verdict but differ sharply in confidence.';

  return { kind, summary, divergentFactors };
}

export interface DwellContext {
  approval: Approval;
  disagreement: DisagreementKind;
  /** True when this approval replaced another — dwell resets to full, no credit carried. */
  supersedes: boolean;
}

/**
 * Minimum ms the material fields must have been visible before `Sign` enables.
 *
 * The single mechanism worth defending hardest: it is the only anti-fatigue
 * control that scales cost with consequence. Uniform friction produces either
 * rubber-stamping or a shadow process where the real work happens elsewhere.
 */
export function dwellRequirementMs(ctx: DwellContext): number {
  const { dwellMs } = getCopilotConfig();
  const { approval, disagreement, supersedes } = ctx;

  let base: number;
  if (approval.requiredRung === 'L2' || approval.requiredSigners > 1) {
    base = disagreement === 'none' ? dwellMs.l2Agree : dwellMs.l2Disagree;
  } else {
    base = isReversible(approval) ? dwellMs.l1Reversible : dwellMs.l1Irreversible;
  }

  // A re-proposed payload resets to full and then some: "I already read the old
  // one" is exactly the shortcut a sloppy re-plan (or an attacker) would exploit.
  return supersedes ? Math.round(base * dwellMs.resupersededMultiplier) : base;
}

// ---------------------------------------------------------------------------
// Denial reason validation — MIRROR ONLY
// ---------------------------------------------------------------------------

export interface ReasonValidation {
  valid: boolean;
  message?: string;
}

/**
 * Mirrors the server's denial-reason rules for responsiveness.
 *
 * Trimmed length + distinct characters + letter count. That stops lazy input
 * ("aaaaaaaaaaaaaaaaaaaa", twenty spaces) without pretending to stop determined
 * garbage — which is the honest limit of any such rule. The server is the
 * enforcement point and always returns 400 on invalid input.
 */
export function validateReason(raw: string, minLength?: number): ReasonValidation {
  const min = minLength ?? getCopilotConfig().denialReasonMinLength;
  const text = (raw || '').trim();

  if (text.length < min) {
    return { valid: false, message: `Give at least ${min} characters — this is the audit record.` };
  }

  const distinct = new Set(text.toLowerCase().replace(/\s+/g, '')).size;
  if (distinct < 5) {
    return { valid: false, message: 'Write an actual reason, not a filler string.' };
  }

  const letters = (text.match(/[a-z]/gi) || []).length;
  if (letters < min / 2) {
    return { valid: false, message: 'Write an actual reason, not a filler string.' };
  }

  return { valid: true };
}

// ---------------------------------------------------------------------------
// Randomised verification spot-check
// ---------------------------------------------------------------------------

/**
 * Deterministic per approval, random across approvals.
 *
 * Deterministic matters: if this rerolled on every render, a card could flip in
 * and out of demanding a transcription while the banker was reading it, which
 * would read as a bug and teach people to distrust the surface. Hashing the id
 * gives a stable answer that is still unpredictable before the card appears.
 */
export function shouldSpotCheck(approvalId: string, rate?: number): boolean {
  const configured = rate ?? getCopilotConfig().spotCheckRate;
  if (configured <= 0) return false;
  if (configured >= 1) return true;

  let hash = 2166136261;
  for (let i = 0; i < approvalId.length; i += 1) {
    hash ^= approvalId.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const normalised = (hash >>> 0) / 4294967295;
  return normalised < configured;
}

/** The field a spot-check asks about: the last material account reference. */
export function spotCheckField(approval: Approval): PayloadField | undefined {
  return (
    approval.payload.find((f) => f.material && f.format === 'accountRef') ||
    approval.payload.find((f) => f.material && f.format === 'currency')
  );
}

export function spotCheckExpectedAnswer(field: PayloadField): string {
  const text = String(field.value ?? '');
  return text.slice(-4);
}

// ---------------------------------------------------------------------------
// Payload diff — field level, not text
// ---------------------------------------------------------------------------

export type DiffKind = 'unchanged' | 'changed' | 'added' | 'removed';

export interface PayloadDiffRow {
  path: string;
  label: string;
  previous?: unknown;
  next?: unknown;
  kind: DiffKind;
  material: boolean;
  format?: PayloadField['format'];
}

export function diffPayloads(
  previous: PayloadField[],
  next: PayloadField[]
): PayloadDiffRow[] {
  const rows: PayloadDiffRow[] = [];
  const prevByPath = new Map(previous.map((f) => [f.path, f]));
  const seen = new Set<string>();

  for (const field of next) {
    seen.add(field.path);
    const before = prevByPath.get(field.path);
    const kind: DiffKind = !before
      ? 'added'
      : JSON.stringify(before.value) === JSON.stringify(field.value)
        ? 'unchanged'
        : 'changed';
    rows.push({
      path: field.path,
      label: field.label,
      previous: before?.value,
      next: field.value,
      kind,
      material: Boolean(field.material || before?.material),
      format: field.format,
    });
  }

  for (const field of previous) {
    if (seen.has(field.path)) continue;
    rows.push({
      path: field.path,
      label: field.label,
      previous: field.value,
      kind: 'removed',
      material: Boolean(field.material),
      format: field.format,
    });
  }

  return rows;
}

export function countMaterialChanges(rows: PayloadDiffRow[]): number {
  return rows.filter((r) => r.material && r.kind !== 'unchanged').length;
}

// ---------------------------------------------------------------------------
// Value formatting
// ---------------------------------------------------------------------------

/**
 * A mis-rendered magnitude on an approval card is a real-world loss event, so
 * this is deliberately conservative: anything that is not unambiguously a number
 * renders as its raw text rather than being coerced into a currency string.
 */
export function formatFieldValue(field: PayloadField): string {
  const { value, format } = field;

  if (value === null || value === undefined) return '—';
  if (Array.isArray(value)) return value.map((v) => String(v)).join(' · ');

  if (format === 'currency') {
    const numeric = typeof value === 'number' ? value : Number(String(value));
    if (!Number.isFinite(numeric)) return String(value);
    return numeric.toLocaleString(undefined, {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
    });
  }

  if (format === 'percent') {
    const numeric = typeof value === 'number' ? value : Number(String(value));
    if (!Number.isFinite(numeric)) return String(value);
    // Values <= 1 are treated as ratios, above as already-percent. Stated rather
    // than silent, because guessing wrong here is an order-of-magnitude error.
    return numeric <= 1 ? `${(numeric * 100).toFixed(2)}%` : `${numeric.toFixed(2)}%`;
  }

  if (format === 'date') {
    const parsed = new Date(String(value));
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
  }

  if (format === 'accountRef') {
    const text = String(value);
    // Same `····8891` masking convention as the transactions tabs.
    return text.length > 4 ? `····${text.slice(-4)}` : text;
  }

  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/** Remaining ms against the SERVER-anchored expiry. Never a client-computed TTL. */
export function msUntil(iso: string, now: number = Date.now()): number {
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return 0;
  return Math.max(0, target - now);
}

export function formatCountdown(ms: number): string {
  const total = Math.floor(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/** Copy is ALWAYS "expires in MM:SS → DENIED". Never "auto-approves". */
export function countdownLabel(ms: number): string {
  return `expires in ${formatCountdown(ms)} → DENIED`;
}

export function countdownSeverity(
  remainingMs: number,
  totalMs: number
): 'normal' | 'warning' | 'critical' {
  if (totalMs <= 0) return 'normal';
  const fraction = remainingMs / totalMs;
  if (fraction <= 0.1) return 'critical';
  if (fraction <= 0.25) return 'warning';
  return 'normal';
}

// ---------------------------------------------------------------------------
// Batch eligibility — L1 ONLY, structurally
// ---------------------------------------------------------------------------

/**
 * Whether a single approval may enter a batch.
 *
 * The L2 exclusion is NOT a disabled button — it is a set-membership test that
 * an L2 item simply fails, so no batch UI can ever form around one. Batching a
 * second opinion defeats the second opinion: the whole point of L2 is that a
 * different human looked at THIS item, and a "sign all" gesture is exactly the
 * reflexive click L2 exists to prevent (§6.1, epic O-invariant).
 *
 * The rung already encodes "under threshold": an item that resolved to L1 with a
 * single signer is, by definition, one no escalator raised. So batchability is
 * read off the rung the server computed, never off a dollar amount re-derived on
 * the client — the same reason `callerMaySign` is mirrored and never inferred.
 */
export function isBatchEligible(approval: Approval): boolean {
  // Every condition is a POSITIVE assertion, so anything unexpected — a new
  // lifecycle status, an absent server field, an unknown rung — fails CLOSED.
  // In particular:
  //  - status is an allow-list of the two OPEN states, never `!== 'denied'`;
  //  - `callerMaySign === true` (the server-supplied authorization gate) rejects
  //    a missing/undefined field: a missing gate is never consent;
  //  - rung/signers together forbid L2, which must be un-batchable by construction.
  // See approvalPolicy.test.ts for the per-condition tamper pins.
  return (
    (approval.status === 'pending' || approval.status === 'proposed') &&
    approval.requiredRung === 'L1' &&
    approval.requiredSigners === 1 &&
    approval.callerMaySign === true
  );
}

export interface BatchGroup {
  actionId: string;
  actionLabel: string;
  items: Approval[];
}

/**
 * Groups batch-eligible approvals by action type, capped, sorted by TTL.
 *
 * SINGLE action type per group: heterogeneous batching is autonomy laundering.
 * Only groups of two or more are returned — a "batch of one" is just a card, and
 * offering a batch affordance for it trains the sign-all reflex for no gain.
 */
export function batchableGroups(approvals: Approval[], cap: number, now: number = Date.now()): BatchGroup[] {
  const byAction = new Map<string, Approval[]>();
  for (const approval of approvals) {
    if (!isBatchEligible(approval)) continue;
    const list = byAction.get(approval.actionId) || [];
    list.push(approval);
    byAction.set(approval.actionId, list);
  }

  const groups: BatchGroup[] = [];
  for (const [actionId, list] of Array.from(byAction.entries())) {
    if (list.length < 2) continue;
    const sorted = [...list].sort((a, b) => msUntil(a.expiresAt, now) - msUntil(b.expiresAt, now));
    groups.push({
      actionId,
      actionLabel: sorted[0].actionLabel,
      // The cap is a hard slice, not a warning. The remaining items stay as
      // individual cards; they are not silently dropped, just not batched.
      items: sorted.slice(0, Math.max(1, cap)),
    });
  }
  // Most-pressing group first — the one with the soonest-expiring lead item.
  return groups.sort(
    (a, b) => msUntil(a.items[0].expiresAt, now) - msUntil(b.items[0].expiresAt, now)
  );
}

// ---------------------------------------------------------------------------
// Denial counts — grouped by reason, NEVER an undifferentiated total
// ---------------------------------------------------------------------------

export interface DenialBreakdown {
  byReason: Record<TerminalReason, number>;
  /** HUMAN_DENIED only. The one bucket that is evidence about the agent. */
  humanDenied: number;
  /** Everything a policy/TTL/payload change caused — the banker did nothing wrong. */
  systemVoided: number;
  total: number;
}

/**
 * Counts denials, split by cause.
 *
 * §5.1.1(c): a single "N denied" figure silently merges a colleague's rejection
 * with a policy void, and reading the void as a rejection is the exact harm O9
 * flags. Only `HUMAN_DENIED` is evidence about the agent's judgement; the other
 * three are evidence about the ground moving. They must never be summed into one
 * number anywhere the UI renders a count.
 */
export function denialCountsByReason(approvals: Approval[]): DenialBreakdown {
  const byReason: Record<TerminalReason, number> = {
    HUMAN_DENIED: 0,
    POLICY_RUNG_ESCALATED: 0,
    PAYLOAD_SUPERSEDED: 0,
    TTL_EXPIRED: 0,
  };

  for (const approval of approvals) {
    if (approval.status !== 'denied') continue;
    // A denial with no reason is a defect (the store already logs it); count it
    // as HUMAN_DENIED would be a lie, so it lands nowhere and the totals below
    // will visibly not add up, which is the honest signal.
    if (approval.terminalReason && approval.terminalReason in byReason) {
      byReason[approval.terminalReason] += 1;
    }
  }

  const humanDenied = byReason.HUMAN_DENIED;
  const systemVoided =
    byReason.POLICY_RUNG_ESCALATED + byReason.PAYLOAD_SUPERSEDED + byReason.TTL_EXPIRED;

  return { byReason, humanDenied, systemVoided, total: humanDenied + systemVoided };
}

/** Short human label for a terminal reason, for counts and chips. */
export function terminalReasonShortLabel(reason: TerminalReason): string {
  switch (reason) {
    case 'HUMAN_DENIED':
      return 'denied by a reviewer';
    case 'POLICY_RUNG_ESCALATED':
      return 'voided by a policy change';
    case 'PAYLOAD_SUPERSEDED':
      return 'superseded — payload changed';
    case 'TTL_EXPIRED':
      return 'expired unsigned';
    default:
      return reason;
  }
}
