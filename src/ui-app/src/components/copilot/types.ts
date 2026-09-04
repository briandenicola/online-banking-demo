/**
 * Banker Copilot — domain and stream types.
 *
 * ============================================================================
 * THIS FILE IS THE CLIENT SIDE OF A RATIFIED CONTRACT. IT IS NOT A LOCAL MODEL.
 * ============================================================================
 *
 * `CopilotEventEnvelope` below is the envelope ratified in epic §8.0 as the
 * SINGLE trace schema — it serves both this live stream and the offline eval
 * replay in #333. It is stated in `docs/design/banker-copilot-ui.md` §4.2 and
 * restated here only because TypeScript cannot import from Markdown.
 *
 * The rule that follows, and the reason this comment is shouting: **do not add
 * a frontend-only event kind, a frontend-only field, or a "convenience"
 * parallel type.** Phase 1 lost hours to a privilege escalation that lived in
 * the seam between two independently-stated role models, each of which was
 * internally correct. Duplication is the bug. If the client needs a shape the
 * envelope does not have, the envelope changes and the service changes with it.
 *
 * Approval types are the same story from the other direction: the wire shape is
 * whatever `authority-service`'s `ApprovalResponse` actually serialises (see
 * `src/authority-service/Contracts/Contracts.cs`), NOT what any document says it
 * should be. `api/authorityWire.ts` holds that shape verbatim and maps it here.
 */

// ---------------------------------------------------------------------------
// Lifecycle — epic §5.1 / §5.1.1
// ---------------------------------------------------------------------------

/**
 * The whole lifecycle. There is no `expired` state and no `void` state: both
 * collapse into `denied` carrying a `terminalReason`.
 */
export type ApprovalState = 'proposed' | 'pending' | 'signed' | 'executed' | 'denied';

/**
 * Closed enum, MANDATORY whenever state === 'denied'.
 *
 * All four share one status, so a UI that renders a bare "Denied" has silently
 * told a banker whose signature was voided by a policy change that they were
 * rejected. Every surface here branches on all four.
 *
 * Never aggregate a denial count across these (§5.1.1(c)): only HUMAN_DENIED is
 * evidence about the agent.
 */
export type TerminalReason =
  | 'HUMAN_DENIED'
  | 'POLICY_RUNG_ESCALATED'
  | 'PAYLOAD_SUPERSEDED'
  | 'TTL_EXPIRED';

export const TERMINAL_REASONS: TerminalReason[] = [
  'HUMAN_DENIED',
  'POLICY_RUNG_ESCALATED',
  'PAYLOAD_SUPERSEDED',
  'TTL_EXPIRED',
];

export type AuthorityRung = 'L1' | 'L2' | 'L3';

export type ExecutionState = 'not_started' | 'in_flight' | 'succeeded' | 'failed';

// ---------------------------------------------------------------------------
// Trace tree
// ---------------------------------------------------------------------------

export type RunStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type NodeStatus = 'pending' | 'running' | 'complete' | 'failed' | 'retrying' | 'skipped';

export interface ToolCall {
  id: string;
  name: string;
  args?: Record<string, unknown>;
  status: NodeStatus;
  startedAt: string;
  durationMs?: number;
  resultSummary?: string;
  error?: string;
  /** 1-based. >1 renders the retry chip. */
  attempt: number;
  /** §8.0: lifted onto tool frames so agent decisions correlate with OTEL spans. */
  traceId?: string;
  spanId?: string;
  /** Which subagent owns this call, when it was not made by the root plan. */
  subagentId?: string;
  stepId?: string;
}

export interface SubagentRun {
  id: string;
  parentStepId: string;
  parentSubagentId?: string;
  /** §8.0: lets the fan-out tree be reconstructed offline. */
  parentRunId?: string;
  name: string;
  role: 'specialist' | 'supervisor';
  status: NodeStatus;
  confidence?: number;
  verdictSummary?: string;
  startedAt: string;
  durationMs?: number;
  toolCallIds: string[];
  childIds: string[];
  depth: number;
  toolCallCount?: number;
  note?: string;
}

export interface PlanStep {
  id: string;
  index: number;
  title: string;
  status: NodeStatus;
  startedAt?: string;
  durationMs?: number;
  summary?: string;
  error?: string;
  toolCallIds: string[];
  subagentIds: string[];
  /** Set when a re-plan dropped this step. Superseded steps are shown, never removed. */
  supersededReason?: string;
}

export interface PlanRevision {
  version: number;
  at: string;
  reason: string;
  addedStepIds: string[];
  removedStepIds: string[];
  /** Set when this revision stopped an outstanding signature counting. */
  supersededApprovalId?: string;
}

export interface ActorRef {
  id: string;
  displayName: string;
  role: 'banker' | 'supervisor' | 'agent';
}

// ---------------------------------------------------------------------------
// Approvals
// ---------------------------------------------------------------------------

export type PayloadFormat = 'currency' | 'percent' | 'date' | 'text' | 'accountRef' | 'json';

export interface PayloadField {
  path: string;
  label: string;
  value: unknown;
  format?: PayloadFormat;
  /**
   * Fields a human MUST read. Drives the disclosure gate: `Sign` stays disabled
   * until every material row has actually been in the viewport.
   */
  material?: boolean;
}

export interface Escalator {
  key: string;
  /** Rung this escalator raised the action TO. Escalators only ever raise. */
  raisedTo: AuthorityRung;
  scope?: string;
  thresholdName?: string;
  thresholdValue?: string;
  /**
   * Server-supplied plain-language sentence, rendered verbatim. Never assembled
   * client-side: the explanation is part of the audit record.
   */
  reason: string;
}

/**
 * One required signature.
 *
 * NOTE THE ABSENCE. There is no `cosignerId` and no prospective-signer field of
 * any name, because naming a co-signer at proposal time lets a banker choose
 * their own reviewer — the exact self-dealing L2 exists to prevent. `signedBy`
 * is populated only AFTER someone signs. Until then the slot renders as
 * "awaiting a supervisor", never "assigned to <name>". Presentation must not
 * reintroduce a field the data model deliberately omits.
 */
export interface SignatureSlot {
  ordinal: number;
  minSeniority: number;
  /** Identities this slot may NOT be filled by. A set-membership test, not a count. */
  mustDifferFrom: string[];
  signedBy?: string;
  signedByUsername?: string;
  signedAt?: string;
  comment?: string;
  filled: boolean;
}

export interface AgentKeyFactor {
  label: string;
  value: string;
  concern?: boolean;
}

export interface AgentAssessment {
  agentId?: string;
  agentName?: string;
  role?: 'primary' | 'supervisor';
  verdict?: string;
  confidence?: number;
  rationale?: string;
  keyFactors?: AgentKeyFactor[];
  citedEvidenceIds?: string[];
}

export interface EvidenceRef {
  id: string;
  kind: 'document' | 'tool_result' | 'record' | 'policy';
  label: string;
  sourceToolCallId?: string;
  excerpt?: string;
  href?: string;
}

export interface Approval {
  id: string;
  status: ApprovalState;
  actionId: string;
  actionLabel: string;
  requesterId: string;
  requesterUsername?: string;
  sessionId?: string;
  /** Rendered rows, derived from `rawPayload` with formatting and materiality. */
  payload: PayloadField[];
  rawPayload: Record<string, unknown>;
  evidence: EvidenceRef[];
  /** Primary always; supervisor present only at L2 once it has formed an opinion. */
  assessments: AgentAssessment[];
  /** The signature binds to THIS hash — not to the intent. Always rendered. */
  payloadHash: string;
  /** Server-computed truncation. Never truncate the hash client-side. */
  payloadHashShort: string;
  policyVersion: string;
  policyId: string;
  baseRung: AuthorityRung;
  requiredRung: AuthorityRung;
  requiredSigners: number;
  signaturesCollected: number;
  firedEscalators: Escalator[];
  signatureSlots: SignatureSlot[];
  createdAt: string;
  expiresAt: string;
  terminalAt?: string;
  terminalReason?: TerminalReason;
  terminalDetail?: string;
  supersededByApprovalId?: string;
  supersedesApprovalId?: string;
  executionState: ExecutionState;
  downstreamRef?: string;
  downstreamStatus?: number;
  executionError?: string;
  /**
   * Server-computed. The client NEVER infers signing eligibility — separation of
   * duties is decided by the service that holds the signing key. The client
   * mirrors it so the banker learns the rule instead of hitting a 403.
   */
  callerMaySign: boolean;
  callerMaySignReason?: string;
  /** Set when this approval replaced another; drives the field-level diff. */
  previousPayload?: PayloadField[];
  previousPayloadHash?: string;
}

// ---------------------------------------------------------------------------
// Stream envelope — epic §8.0, ratified. Do not extend unilaterally.
// ---------------------------------------------------------------------------

export type CopilotEventKind =
  | 'run.started'
  | 'plan.proposed'
  | 'plan.revised'
  | 'step.started'
  | 'step.completed'
  | 'step.failed'
  | 'tool.started'
  | 'tool.completed'
  | 'tool.failed'
  | 'subagent.spawned'
  | 'subagent.progress'
  | 'subagent.completed'
  | 'approval.required'
  | 'approval.updated'
  | 'approval.terminal'
  | 'artifact.created'
  | 'artifact.updated'
  | 'run.error'
  | 'run.done'
  | 'heartbeat';

export const COPILOT_EVENT_KINDS: CopilotEventKind[] = [
  'run.started',
  'plan.proposed',
  'plan.revised',
  'step.started',
  'step.completed',
  'step.failed',
  'tool.started',
  'tool.completed',
  'tool.failed',
  'subagent.spawned',
  'subagent.progress',
  'subagent.completed',
  'approval.required',
  'approval.updated',
  'approval.terminal',
  'artifact.created',
  'artifact.updated',
  'run.error',
  'run.done',
  'heartbeat',
];

/**
 * Every frame shares this envelope.
 *
 * `seq` is monotonic and gapless per run. That property is load-bearing twice
 * over: it is how this client detects a gap and resyncs, and it is how #333
 * replays a run deterministically offline.
 */
export interface CopilotEventEnvelope<K extends CopilotEventKind, P> {
  id: string;
  seq: number;
  runId: string;
  sessionId?: string;
  kind: K;
  /** Server clock, ISO 8601. Never trust the client clock for TTLs. */
  ts: string;
  payload: P;
}

export interface RunStartedPayload {
  taskId: string;
  title: string;
  intent: string;
  actor: ActorRef;
  startedAt: string;
}

export interface PlanStepSeed {
  id: string;
  index: number;
  title: string;
  status: NodeStatus;
}

export interface PlanProposedPayload {
  version: number;
  steps: PlanStepSeed[];
}

export interface PlanRevisedPayload extends PlanRevision {
  steps: PlanStepSeed[];
}

export interface StepStartedPayload {
  stepId: string;
  index: number;
  title: string;
}

export interface StepCompletedPayload {
  stepId: string;
  durationMs: number;
  summary?: string;
}

export interface StepFailedPayload {
  stepId: string;
  error: string;
  willRetry: boolean;
}

export interface ToolStartedPayload {
  toolCallId: string;
  stepId: string;
  subagentId?: string;
  name: string;
  args?: Record<string, unknown>;
  attempt: number;
  traceId?: string;
  spanId?: string;
}

export interface ToolCompletedPayload {
  toolCallId: string;
  durationMs: number;
  resultSummary?: string;
  result?: unknown;
}

export interface ToolFailedPayload {
  toolCallId: string;
  error: string;
  attempt: number;
  willRetry: boolean;
}

export interface SubagentSpawnedPayload {
  subagentId: string;
  parentStepId: string;
  parentSubagentId?: string;
  parentRunId?: string;
  name: string;
  role: 'specialist' | 'supervisor';
  depth: number;
}

export interface SubagentProgressPayload {
  subagentId: string;
  note?: string;
  toolCallCount: number;
}

export interface SubagentCompletedPayload {
  subagentId: string;
  status: 'complete' | 'failed';
  confidence?: number;
  verdictSummary?: string;
  durationMs: number;
}

/**
 * §8.0 requires `policyVersion` and the resolved rung on this frame, copied from
 * the approval rather than re-derived, so replay can answer "was the rung
 * correct?" — the highest-value eval question in the system.
 */
export interface ApprovalRequiredPayload {
  approval: Approval;
  policyVersion: string;
  requiredRung: AuthorityRung;
}

export interface ApprovalUpdatedPayload {
  approval: Approval;
}

/**
 * Fired when an approval reaches ANY terminal state — the four denial reasons
 * and `executed` alike.
 *
 * Deliberately NOT named `approval.voided`: there is no `void` lifecycle state,
 * and an event named for one would reintroduce in the client exactly the
 * distinction §5.1.1 collapsed into `terminalReason`.
 */
export interface ApprovalTerminalPayload {
  approvalId: string;
  state: 'denied' | 'executed';
  /** Mandatory when state === 'denied'. */
  terminalReason?: TerminalReason;
  terminalDetail?: string;
  terminalAt: string;
  previousPayloadHash?: string;
  supersededByApprovalId?: string;
  /** Both endpoints of a rung transition — replay cannot judge one endpoint. */
  fromRung?: AuthorityRung;
  toRung?: AuthorityRung;
  policyVersion?: string;
}

export type ArtifactKind = 'decision_memo' | 'payload' | 'comparison' | 'evidence_bundle';

export interface ArtifactPayload {
  artifactId: string;
  kind: ArtifactKind;
  title: string;
  revision: number;
  content: unknown;
}

export interface RunErrorPayload {
  code: string;
  message: string;
  recoverable: boolean;
  stepId?: string;
}

export interface RunDonePayload {
  status: 'completed' | 'failed' | 'cancelled';
  durationMs: number;
  finalArtifactIds: string[];
  /** Terminal seq — the client asserts it saw every seq up to this. */
  finalSeq: number;
}

export interface HeartbeatPayload {
  serverTs: string;
}

/**
 * The discriminated union. A new kind added server-side without a client handler
 * is a COMPILE error rather than a silent no-op — that is the point of writing
 * it this way rather than as a loose `{ kind: string }`.
 */
export type CopilotEvent =
  | CopilotEventEnvelope<'run.started', RunStartedPayload>
  | CopilotEventEnvelope<'plan.proposed', PlanProposedPayload>
  | CopilotEventEnvelope<'plan.revised', PlanRevisedPayload>
  | CopilotEventEnvelope<'step.started', StepStartedPayload>
  | CopilotEventEnvelope<'step.completed', StepCompletedPayload>
  | CopilotEventEnvelope<'step.failed', StepFailedPayload>
  | CopilotEventEnvelope<'tool.started', ToolStartedPayload>
  | CopilotEventEnvelope<'tool.completed', ToolCompletedPayload>
  | CopilotEventEnvelope<'tool.failed', ToolFailedPayload>
  | CopilotEventEnvelope<'subagent.spawned', SubagentSpawnedPayload>
  | CopilotEventEnvelope<'subagent.progress', SubagentProgressPayload>
  | CopilotEventEnvelope<'subagent.completed', SubagentCompletedPayload>
  | CopilotEventEnvelope<'approval.required', ApprovalRequiredPayload>
  | CopilotEventEnvelope<'approval.updated', ApprovalUpdatedPayload>
  | CopilotEventEnvelope<'approval.terminal', ApprovalTerminalPayload>
  | CopilotEventEnvelope<'artifact.created', ArtifactPayload>
  | CopilotEventEnvelope<'artifact.updated', ArtifactPayload>
  | CopilotEventEnvelope<'run.error', RunErrorPayload>
  | CopilotEventEnvelope<'run.done', RunDonePayload>
  | CopilotEventEnvelope<'heartbeat', HeartbeatPayload>;

export type StreamStatus =
  | 'idle'
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'resumed'
  | 'degraded'
  | 'closed'
  | 'failed';

/**
 * Statuses in which it is safe to sign.
 *
 * Only `live` and `resumed` qualify. On anything else the sign/deny controls
 * disable, because a stale payload signed during a network partition is exactly
 * the TOCTOU the payload hash exists to prevent — and a UI that permits it has
 * quietly undone the control it renders.
 */
export function canSignUnderStream(status: StreamStatus): boolean {
  return status === 'live' || status === 'resumed';
}

// ---------------------------------------------------------------------------
// Artifacts, runs, queue
// ---------------------------------------------------------------------------

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  title: string;
  revision: number;
  content: unknown;
}

export interface RunState {
  runId: string;
  sessionId?: string;
  title: string;
  intent?: string;
  status: RunStatus;
  startedAt?: string;
  durationMs?: number;
  planVersion: number;
  stepIds: string[];
  steps: Record<string, PlanStep>;
  subagents: Record<string, SubagentRun>;
  toolCalls: Record<string, ToolCall>;
  /** Subagents parented by the run itself — the supervisor rail lives here. */
  rootSubagentIds: string[];
  revisions: PlanRevision[];
  artifacts: Record<string, Artifact>;
  artifactIds: string[];
  approvalIds: string[];
  error?: RunErrorPayload;
  lastSeq: number;
  finalSeq?: number;
}

export type QueueGroupId = 'needsYou' | 'awaitingCosigner' | 'running' | 'doneToday';

export type TraceDensity = 'summary' | 'detailed' | 'raw';
