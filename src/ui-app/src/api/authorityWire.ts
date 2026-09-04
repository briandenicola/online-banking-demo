/**
 * The `authority-service` wire contract, as it is actually serialised.
 *
 * These interfaces were written from `src/authority-service/Contracts/Contracts.cs`
 * and `Controllers/ApprovalsController.cs`, not from a design document. That
 * distinction matters: the docs describe an `ApprovalRequest` shape with fields
 * like `opinions[]` and `signatures[]` that the service does not emit. It emits
 * `agentAssessment`, `signatureSlots`, `callerMaySign`, and a `payload` that is
 * a free-form JSON object.
 *
 * ASP.NET Core's `AddNewtonsoftJson()` applies camelCase by default, so the wire
 * keys are camelCase versions of the C# properties.
 *
 * Everything the UI renders passes through `toApproval()` below. One mapping
 * function, one place to fix when the contract moves.
 */

import { logger } from '../utils/logger';
import {
  Approval,
  ApprovalState,
  AgentAssessment,
  AuthorityRung,
  Escalator,
  EvidenceRef,
  ExecutionState,
  PayloadField,
  PayloadFormat,
  SignatureSlot,
  TerminalReason,
  TERMINAL_REASONS,
} from '../components/copilot/types';

export interface WireFiredEscalator {
  key: string;
  raisedTo: string;
  scope?: string;
  thresholdName?: string | null;
  thresholdValue?: string | null;
  reason: string;
}

export interface WireSignatureSlot {
  ordinal: number;
  minSeniority: number;
  mustDifferFrom: string[];
  signedBy?: string | null;
  signedByUsername?: string | null;
  signedAt?: string | null;
  comment?: string | null;
  filled: boolean;
}

export interface WireApproval {
  id: string;
  status: string;
  actionId: string;
  actionLabel: string;
  requesterId: string;
  requesterUsername?: string | null;
  sessionId?: string | null;
  payload: Record<string, unknown>;
  evidence: Record<string, unknown>;
  agentAssessment?: Record<string, unknown> | null;
  payloadHash: string;
  payloadHashShort: string;
  policyVersion: string;
  policyId: string;
  baseRung: string;
  requiredRung: string;
  requiredSigners: number;
  signaturesCollected: number;
  firedEscalators: WireFiredEscalator[];
  signatureSlots: WireSignatureSlot[];
  createdAt: string;
  expiresAt: string;
  terminalAt?: string | null;
  terminalReason?: string | null;
  terminalDetail?: string | null;
  supersededByApprovalId?: string | null;
  supersedesApprovalId?: string | null;
  executionState: string;
  downstreamRef?: string | null;
  downstreamStatus?: number | null;
  executionError?: string | null;
  callerMaySign: boolean;
  callerMaySignReason?: string | null;
}

export interface WireApprovalList {
  count: number;
  items: WireApproval[];
}

const STATES: ApprovalState[] = ['proposed', 'pending', 'signed', 'executed', 'denied'];

/**
 * Fails LOUDLY on an unknown status rather than defaulting.
 *
 * A status this client does not understand means the lifecycle moved and this
 * file did not. Quietly coercing it to `pending` would render an unknown state
 * as a signable one, which is the single worst available failure mode here.
 */
function toState(raw: string): ApprovalState {
  const value = (raw || '').toLowerCase() as ApprovalState;
  if (STATES.includes(value)) return value;
  logger.error(
    `authorityWire: unknown approval status "${raw}". The lifecycle is ${STATES.join(' → ')} ` +
      'with `denied` the single terminal rejection state. Treating as denied.'
  );
  return 'denied';
}

function toTerminalReason(raw?: string | null): TerminalReason | undefined {
  if (!raw) return undefined;
  const value = raw.toUpperCase() as TerminalReason;
  if (TERMINAL_REASONS.includes(value)) return value;
  logger.error(`authorityWire: unknown terminalReason "${raw}".`);
  return undefined;
}

function toRung(raw: string): AuthorityRung {
  const value = (raw || '').toUpperCase();
  return value === 'L1' || value === 'L2' || value === 'L3' ? value : 'L3';
}

function toExecutionState(raw: string): ExecutionState {
  switch ((raw || '').toLowerCase()) {
    case 'in_flight':
    case 'inflight':
      return 'in_flight';
    case 'succeeded':
      return 'succeeded';
    case 'failed':
      return 'failed';
    default:
      return 'not_started';
  }
}

/**
 * Field paths whose values are money, rates, dates, or account references.
 *
 * Rendering hints are configuration of a sort, but they are *presentation* and
 * they are keyed on the canonical `<domain>.<entity>.<verb>` payload vocabulary,
 * so they live in code next to the mapper. The consequence of getting this wrong
 * is a mis-rendered magnitude on a card someone signs, so the default is the
 * conservative one: anything unrecognised renders as text, never as currency.
 */
const FORMAT_HINTS: { test: RegExp; format: PayloadFormat; material: boolean }[] = [
  { test: /(^|\.)(amount|principal|balance|limit|fee|total)$/i, format: 'currency', material: true },
  { test: /(^|\.)(rate|apr|dti|ltv|percent|ratio)$/i, format: 'percent', material: true },
  { test: /(^|\.)(accountid|account|fromaccountid|toaccountid|accountref)$/i, format: 'accountRef', material: true },
  { test: /(^|\.)(effectivedate|date|expiresat|scheduledfor)$/i, format: 'date', material: false },
  { test: /(^|\.)(effect|impact|consequence)$/i, format: 'text', material: true },
  { test: /(^|\.)(reversible|irreversible)$/i, format: 'text', material: true },
];

function humanLabel(path: string): string {
  const leaf = path.split('.').pop() || path;
  return leaf
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/^./, (c) => c.toUpperCase());
}

/**
 * Flattens the free-form payload JSON into rendered rows.
 *
 * Depth-first with dotted paths, because the signature binds the canonicalised
 * whole and a banker must be able to see every leaf of it. Arrays render as one
 * row per element so a list of conditions is readable rather than a JSON blob.
 */
export function flattenPayload(
  payload: Record<string, unknown> | undefined,
  prefix = ''
): PayloadField[] {
  if (!payload || typeof payload !== 'object') return [];
  const rows: PayloadField[] = [];

  for (const [key, value] of Object.entries(payload)) {
    const path = prefix ? `${prefix}.${key}` : key;

    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      rows.push(...flattenPayload(value as Record<string, unknown>, path));
      continue;
    }

    const hint = FORMAT_HINTS.find((h) => h.test.test(path));
    rows.push({
      path,
      label: humanLabel(path),
      value,
      format: hint ? hint.format : Array.isArray(value) ? 'json' : 'text',
      material: hint ? hint.material : false,
    });
  }

  return rows;
}

/**
 * The evidence object is free-form; each top-level key becomes a citation row.
 * `sourceToolCallId` is lifted when present so the card can scroll the trace to
 * the tool call that produced the claim — the loop that makes the trace pane a
 * citation index rather than decoration.
 */
function toEvidence(evidence: Record<string, unknown> | undefined): EvidenceRef[] {
  if (!evidence || typeof evidence !== 'object') return [];
  return Object.entries(evidence).map(([key, value]) => {
    const detail = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
    return {
      id: key,
      kind: (typeof detail.kind === 'string' ? detail.kind : 'record') as EvidenceRef['kind'],
      label: typeof detail.label === 'string' ? detail.label : humanLabel(key),
      sourceToolCallId:
        typeof detail.toolCallId === 'string' ? (detail.toolCallId as string) : undefined,
      excerpt:
        typeof detail.summary === 'string'
          ? (detail.summary as string)
          : typeof value === 'string'
            ? value
            : undefined,
      href: typeof detail.href === 'string' ? (detail.href as string) : undefined,
    };
  });
}

function toAssessments(raw: Record<string, unknown> | null | undefined): AgentAssessment[] {
  if (!raw || typeof raw !== 'object') return [];

  // Two shapes are tolerated: a single assessment, or `{ primary, supervisor }`
  // once Phase 3 lights up the supervisor agent. Anything else is ignored rather
  // than guessed at.
  const single = (value: Record<string, unknown>, role: 'primary' | 'supervisor'): AgentAssessment => ({
    agentId: typeof value.agentId === 'string' ? value.agentId : undefined,
    agentName: typeof value.agentName === 'string' ? value.agentName : undefined,
    role,
    verdict: typeof value.verdict === 'string' ? value.verdict : undefined,
    confidence:
      typeof value.confidence === 'number'
        ? value.confidence
        : typeof value.confidence === 'string'
          ? Number(value.confidence)
          : undefined,
    rationale: typeof value.rationale === 'string' ? value.rationale : undefined,
    keyFactors: Array.isArray(value.keyFactors)
      ? (value.keyFactors as AgentAssessment['keyFactors'])
      : undefined,
    citedEvidenceIds: Array.isArray(value.citedEvidenceIds)
      ? (value.citedEvidenceIds as string[])
      : undefined,
  });

  const out: AgentAssessment[] = [];
  const primary = raw.primary as Record<string, unknown> | undefined;
  const supervisor = raw.supervisor as Record<string, unknown> | undefined;

  if (primary && typeof primary === 'object') out.push(single(primary, 'primary'));
  if (supervisor && typeof supervisor === 'object') out.push(single(supervisor, 'supervisor'));
  if (out.length === 0) out.push(single(raw, 'primary'));

  return out;
}

function toEscalators(raw: WireFiredEscalator[] | undefined): Escalator[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((e) => ({
    key: e.key,
    raisedTo: toRung(e.raisedTo),
    scope: e.scope,
    thresholdName: e.thresholdName || undefined,
    thresholdValue: e.thresholdValue || undefined,
    reason: e.reason,
  }));
}

function toSlots(raw: WireSignatureSlot[] | undefined): SignatureSlot[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((s) => ({
    ordinal: s.ordinal,
    minSeniority: s.minSeniority,
    mustDifferFrom: Array.isArray(s.mustDifferFrom) ? s.mustDifferFrom : [],
    signedBy: s.signedBy || undefined,
    signedByUsername: s.signedByUsername || undefined,
    signedAt: s.signedAt || undefined,
    comment: s.comment || undefined,
    filled: Boolean(s.filled),
  }));
}

export function toApproval(wire: WireApproval): Approval {
  const status = toState(wire.status);
  const terminalReason = toTerminalReason(wire.terminalReason);

  if (status === 'denied' && !terminalReason) {
    // Not a crash, but not silent either: a denial without a reason means the UI
    // is about to render a bare "Denied" to someone who may have done nothing
    // wrong, which is the exact failure §5.1.1 exists to prevent.
    logger.error(
      `authorityWire: approval ${wire.id} is denied with no terminalReason. ` +
        'terminalReason is mandatory on every denial (epic §5.1.1).'
    );
  }

  return {
    id: wire.id,
    status,
    actionId: wire.actionId,
    actionLabel: wire.actionLabel,
    requesterId: wire.requesterId,
    requesterUsername: wire.requesterUsername || undefined,
    sessionId: wire.sessionId || undefined,
    payload: flattenPayload(wire.payload),
    rawPayload: wire.payload || {},
    evidence: toEvidence(wire.evidence),
    assessments: toAssessments(wire.agentAssessment),
    payloadHash: wire.payloadHash,
    payloadHashShort: wire.payloadHashShort,
    policyVersion: wire.policyVersion,
    policyId: wire.policyId,
    baseRung: toRung(wire.baseRung),
    requiredRung: toRung(wire.requiredRung),
    requiredSigners: wire.requiredSigners,
    signaturesCollected: wire.signaturesCollected,
    firedEscalators: toEscalators(wire.firedEscalators),
    signatureSlots: toSlots(wire.signatureSlots),
    createdAt: wire.createdAt,
    expiresAt: wire.expiresAt,
    terminalAt: wire.terminalAt || undefined,
    terminalReason,
    terminalDetail: wire.terminalDetail || undefined,
    supersededByApprovalId: wire.supersededByApprovalId || undefined,
    supersedesApprovalId: wire.supersedesApprovalId || undefined,
    executionState: toExecutionState(wire.executionState),
    downstreamRef: wire.downstreamRef || undefined,
    downstreamStatus: wire.downstreamStatus ?? undefined,
    executionError: wire.executionError || undefined,
    callerMaySign: Boolean(wire.callerMaySign),
    callerMaySignReason: wire.callerMaySignReason || undefined,
  };
}
