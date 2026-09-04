/**
 * Surface comparison instrumentation — Classic Admin vs. Banker Copilot.
 *
 * WHY THIS EXISTS
 * ---------------
 * Phase 5 was changed from "retire the admin tabs" to "keep both and compare"
 * (Brian, 2026-09-04). That turns "the harness is a better experience" from a
 * claim into a hypothesis with a control group. This module is what makes the
 * hypothesis falsifiable: the same banker task is run on both surfaces and the
 * same measurements are taken on both.
 *
 * THE MEASUREMENT TRAP THIS MODULE IS BUILT AROUND
 * ------------------------------------------------
 * Epic §9 risk 1: if a banker signs 40 cards an hour, "human in the loop" is
 * theatre and we have built a slower autonomous system with a liability shield.
 * The epic's instruction is explicit — a FALLING time-to-sign must be treated
 * as a DEFECT, not as adoption.
 *
 * That single sentence inverts how you normally read a latency metric, and it is
 * the reason `MetricDirection` exists below and is attached to every metric.
 * `taskDurationMs` genuinely wants to go down. `signatureDwellMs` going down is
 * the signature of approval fatigue. If those two are rendered on the same
 * dashboard as undifferentiated "durations", someone will eventually celebrate
 * the wrong one, and this whole exercise will have produced a confident false
 * conclusion. Encoding directionality at the point of definition — rather than
 * in a chart config or a slide — is the cheapest available defence.
 *
 * SCOPE / PRIVACY
 * ---------------
 * Everything is buffered in the browser (sessionStorage) and nothing is
 * transmitted. There is no exporter yet, deliberately: the backend contract for
 * this is not mine to design. Export is manual via `exportComparisonData()`.
 *
 * No payload contents, customer data, account numbers, or free-text denial
 * reasons are ever recorded here — only ids, counts, timings, and enum values.
 * If you extend this, keep that property: the whole point is that this file can
 * be safely enabled in a demo environment.
 */

import { logger } from '../utils/logger';

/** The two surfaces under comparison. */
export type SurfaceId = 'classic' | 'copilot';

/**
 * How to read a metric's movement.
 *
 * `lowerIsSuspicious` is the important one and is not a hedge — it is the epic's
 * §9 risk 1 ruling made mechanical. A metric marked this way must never be
 * presented as an improvement when it falls.
 */
export type MetricDirection = 'lowerIsBetter' | 'higherIsBetter' | 'lowerIsSuspicious' | 'neutral';

export interface MetricDefinition {
  key: string;
  label: string;
  unit: 'ms' | 'count' | 'ratio';
  direction: MetricDirection;
  /** Why this metric is worth collecting, and how it can mislead. */
  notes: string;
}

/**
 * The pre-registered metric set.
 *
 * "Pre-registered" is doing real work here: deciding what counts as success
 * AFTER seeing the data is how you talk yourself into any conclusion you like.
 * This list is fixed before the harness exists, which is the only moment at
 * which we are honestly incapable of rigging it.
 */
export const COMPARISON_METRICS: MetricDefinition[] = [
  {
    key: 'taskDurationMs',
    label: 'Time to complete task',
    unit: 'ms',
    direction: 'lowerIsBetter',
    notes:
      'Wall-clock from task start to a recorded outcome. The headline efficiency metric — and the one most vulnerable to rigging, because task selection determines it almost entirely. Only meaningful against the shared task set.',
  },
  {
    key: 'interactionCount',
    label: 'Interactions (clicks + submits)',
    unit: 'count',
    direction: 'lowerIsBetter',
    notes:
      'A proxy for effort. Weak on its own: the harness can win by replacing ten clicks with one long wait, which is not obviously better for the banker.',
  },
  {
    key: 'contextSwitchCount',
    label: 'Context switches',
    unit: 'count',
    direction: 'lowerIsBetter',
    notes:
      'Tab or route changes within a task. This is the specific pain the harness claims to remove ("tab-hunting across 7 admin tabs"), so it is the most direct test of the core claim.',
  },
  {
    key: 'signatureDwellMs',
    label: 'Time spent before signing',
    unit: 'ms',
    direction: 'lowerIsSuspicious',
    notes:
      'Epic §9 risk 1: a FALLING time-to-sign is a defect, not adoption — it is what approval fatigue looks like in a chart. Never present a decrease here as an improvement. Note the enforced dwell gate puts a floor under this, so only movement ABOVE the floor is informative.',
  },
  {
    key: 'signaturesPerHour',
    label: 'Signature rate',
    unit: 'count',
    direction: 'lowerIsSuspicious',
    notes:
      'The harness is supposed to produce FEWER, BETTER approvals. A higher rate is the failure mode, not the win condition.',
  },
  {
    key: 'evidenceOpenRate',
    label: 'Evidence opened before deciding',
    unit: 'ratio',
    direction: 'higherIsBetter',
    notes:
      'Share of decisions where the signer actually expanded the evidence. The closest available proxy for whether a decision was informed rather than reflexive. Proxy, not truth: opening a panel is not reading it.',
  },
  {
    key: 'denialRate',
    label: 'Denial rate',
    unit: 'ratio',
    direction: 'neutral',
    notes:
      'Explicitly neutral. Neither a high nor a low denial rate is self-evidently good, and treating it as a target would corrupt it immediately. Collected as a distribution check: a denial rate near zero on either surface means the human step is not functioning.',
  },
  {
    key: 'reversalRate',
    label: 'Decisions later reversed',
    unit: 'ratio',
    direction: 'lowerIsBetter',
    notes:
      'The only outcome-quality metric in the set. Everything else measures effort or process; this measures whether the decision was right. Lags the session, so it must be joined after the fact.',
  },
];

/**
 * The shared task set, pre-registered alongside the metrics and for the same
 * reason: chosen before the harness exists, at the one moment we are honestly
 * incapable of picking tasks that flatter it.
 *
 * Every task here must be genuinely performable on BOTH surfaces. A task that
 * only exists in one place measures nothing except that it only exists in one
 * place.
 *
 * `review-flagged-txn` is deliberately Classic Admin's BEST case — it lives in a
 * single tab, so the harness has no tab-hunting to save. If the harness cannot
 * at least draw there, that is a real finding and it belongs in the report.
 */
export interface SharedTask {
  taskKey: string;
  label: string;
  /** Why this task is in the set, including which surface it favours. */
  rationale: string;
}

export const SHARED_TASK_SET: SharedTask[] = [
  {
    taskKey: 'review-flagged-txn',
    label: 'Triage a flagged transaction',
    rationale:
      "Classic Admin's best case: entirely within the Flagged Transactions tab, so there is no tab-hunting for the harness to remove. Included precisely because it is unfavourable to the harness.",
  },
  {
    taskKey: 'review-account-application',
    label: 'Review a pending account application',
    rationale:
      'Mid-difficulty. Mostly one tab, but verification usually requires cross-referencing the customer, which is where Classic starts to cost something.',
  },
  {
    taskKey: 'investigate-velocity-pattern',
    label: 'Decide whether three flags are one pattern or three incidents',
    rationale:
      'The messiest task, requiring correlation across three separate tabs in Classic. The harness should win here by the widest margin — and if it does not, it cannot win anywhere.',
  },
];

export type ComparisonEventType =
  | 'task.start'
  | 'task.end'
  | 'interaction'
  | 'contextSwitch'
  | 'evidenceOpen'
  | 'decision';

export type TaskOutcome = 'completed' | 'abandoned' | 'error';

/** Mirrors the ratified approval lifecycle. No `expired`, no `void`. */
export type DecisionKind = 'signed' | 'denied';

export type TerminalReason =
  | 'HUMAN_DENIED'
  | 'POLICY_RUNG_ESCALATED'
  | 'PAYLOAD_SUPERSEDED'
  | 'TTL_EXPIRED';

export interface ComparisonEvent {
  type: ComparisonEventType;
  surface: SurfaceId;
  /** Correlates every event within one attempt at one task. */
  sessionId: string;
  /** Shared across the SAME task performed on BOTH surfaces — the join key. */
  taskKey: string;
  at: number;
  detail?: Record<string, string | number | boolean>;
}

export interface DecisionRecord {
  sessionId: string;
  surface: SurfaceId;
  approvalId: string;
  requiredRung: 'L1' | 'L2' | 'L3';
  decision: DecisionKind;
  terminalReason?: TerminalReason;
  /** Time the material payload fields were visible before the decision. */
  dwellMs: number;
  evidenceOpened: boolean;
  at: number;
}

export interface TaskSession {
  sessionId: string;
  taskKey: string;
  surface: SurfaceId;
  startedAt: number;
  endedAt?: number;
  outcome?: TaskOutcome;
  interactionCount: number;
  contextSwitchCount: number;
  evidenceOpenCount: number;
  decisions: DecisionRecord[];
}

const STORAGE_KEY = 'copilot_comparison_buffer_v1';
const MAX_EVENTS = 5000;

interface Buffer {
  events: ComparisonEvent[];
  sessions: Record<string, TaskSession>;
}

function emptyBuffer(): Buffer {
  return { events: [], sessions: {} };
}

function loadBuffer(): Buffer {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return emptyBuffer();
    const parsed = JSON.parse(raw) as Buffer;
    if (!parsed || !Array.isArray(parsed.events) || typeof parsed.sessions !== 'object') {
      return emptyBuffer();
    }
    return parsed;
  } catch {
    return emptyBuffer();
  }
}

function saveBuffer(buffer: Buffer): void {
  try {
    // Drop oldest events past the cap rather than failing the write. Losing the
    // head of a very long session is strictly better than silently recording
    // nothing once sessionStorage fills.
    if (buffer.events.length > MAX_EVENTS) {
      buffer.events = buffer.events.slice(buffer.events.length - MAX_EVENTS);
    }
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(buffer));
  } catch {
    logger.warn('comparison: unable to persist buffer (storage full or unavailable)');
  }
}

let enabled = false;

/** Wired to the `comparisonInstrumentation` flag by ComparisonInstrumentation. */
export function setComparisonEnabled(value: boolean): void {
  enabled = value;
}

export function isComparisonEnabled(): boolean {
  return enabled;
}

function newSessionId(): string {
  return `cmp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function record(event: ComparisonEvent): void {
  if (!enabled) return;
  const buffer = loadBuffer();
  buffer.events.push(event);
  saveBuffer(buffer);
}

/**
 * Begin a measured attempt at a task.
 *
 * `taskKey` must be identical for the same task on both surfaces — it is the
 * only thing that makes the two runs comparable. Use the shared task-set ids
 * (see docs/design/banker-copilot-ui.md §11.2), not free-text descriptions.
 */
export function startTask(taskKey: string, surface: SurfaceId): string {
  const sessionId = newSessionId();
  if (!enabled) return sessionId;

  const buffer = loadBuffer();
  buffer.sessions[sessionId] = {
    sessionId,
    taskKey,
    surface,
    startedAt: Date.now(),
    interactionCount: 0,
    contextSwitchCount: 0,
    evidenceOpenCount: 0,
    decisions: [],
  };
  buffer.events.push({ type: 'task.start', surface, sessionId, taskKey, at: Date.now() });
  saveBuffer(buffer);
  return sessionId;
}

function mutateSession(sessionId: string, fn: (s: TaskSession) => void): void {
  if (!enabled) return;
  const buffer = loadBuffer();
  const session = buffer.sessions[sessionId];
  if (!session) return;
  fn(session);
  saveBuffer(buffer);
}

export function recordInteraction(sessionId: string, label: string): void {
  mutateSession(sessionId, (s) => {
    s.interactionCount += 1;
  });
  const buffer = loadBuffer();
  const session = buffer.sessions[sessionId];
  if (session) {
    record({
      type: 'interaction',
      surface: session.surface,
      sessionId,
      taskKey: session.taskKey,
      at: Date.now(),
      detail: { label },
    });
  }
}

/**
 * A tab change, route change, or pane switch inside a task.
 *
 * This is the metric that most directly tests the harness's central claim, so
 * it must be counted the same way on both surfaces: one increment per
 * user-initiated change of what is on screen. An agent-driven update to the
 * trace pane is NOT a context switch — the banker did not go anywhere.
 */
export function recordContextSwitch(sessionId: string, from: string, to: string): void {
  mutateSession(sessionId, (s) => {
    s.contextSwitchCount += 1;
  });
  const buffer = loadBuffer();
  const session = buffer.sessions[sessionId];
  if (session) {
    record({
      type: 'contextSwitch',
      surface: session.surface,
      sessionId,
      taskKey: session.taskKey,
      at: Date.now(),
      detail: { from, to },
    });
  }
}

export function recordEvidenceOpen(sessionId: string, evidenceId: string): void {
  mutateSession(sessionId, (s) => {
    s.evidenceOpenCount += 1;
  });
  const buffer = loadBuffer();
  const session = buffer.sessions[sessionId];
  if (session) {
    record({
      type: 'evidenceOpen',
      surface: session.surface,
      sessionId,
      taskKey: session.taskKey,
      at: Date.now(),
      detail: { evidenceId },
    });
  }
}

export function recordDecision(
  sessionId: string,
  decision: Omit<DecisionRecord, 'sessionId' | 'surface' | 'at'>
): void {
  mutateSession(sessionId, (s) => {
    s.decisions.push({ ...decision, sessionId, surface: s.surface, at: Date.now() });
  });
  const buffer = loadBuffer();
  const session = buffer.sessions[sessionId];
  if (session) {
    record({
      type: 'decision',
      surface: session.surface,
      sessionId,
      taskKey: session.taskKey,
      at: Date.now(),
      detail: {
        approvalId: decision.approvalId,
        decision: decision.decision,
        requiredRung: decision.requiredRung,
        dwellMs: decision.dwellMs,
        evidenceOpened: decision.evidenceOpened,
        ...(decision.terminalReason ? { terminalReason: decision.terminalReason } : {}),
      },
    });
  }
}

export function endTask(sessionId: string, outcome: TaskOutcome): void {
  mutateSession(sessionId, (s) => {
    s.endedAt = Date.now();
    s.outcome = outcome;
  });
  const buffer = loadBuffer();
  const session = buffer.sessions[sessionId];
  if (session) {
    record({
      type: 'task.end',
      surface: session.surface,
      sessionId,
      taskKey: session.taskKey,
      at: Date.now(),
      detail: { outcome, durationMs: (session.endedAt || Date.now()) - session.startedAt },
    });
  }
}

export interface SurfaceSummary {
  surface: SurfaceId;
  taskCount: number;
  completedCount: number;
  medianTaskDurationMs: number | null;
  medianInteractionCount: number | null;
  medianContextSwitchCount: number | null;
  medianSignatureDwellMs: number | null;
  signedCount: number;
  deniedCount: number;
  evidenceOpenRate: number | null;
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

/**
 * Median, not mean, throughout.
 *
 * Task timings are right-skewed — one participant answering the phone mid-task
 * moves a mean by seconds and a median by nothing. With the sample sizes a demo
 * comparison can realistically reach, a mean is mostly reporting the worst
 * outlier.
 */
export function summarise(surface: SurfaceId): SurfaceSummary {
  const buffer = loadBuffer();
  const sessions = Object.values(buffer.sessions).filter((s) => s.surface === surface);
  const finished = sessions.filter((s) => typeof s.endedAt === 'number');

  const decisions = sessions.flatMap((s) => s.decisions);
  const withEvidence = decisions.filter((d) => d.evidenceOpened).length;

  return {
    surface,
    taskCount: sessions.length,
    completedCount: finished.filter((s) => s.outcome === 'completed').length,
    medianTaskDurationMs: median(
      finished.map((s) => (s.endedAt as number) - s.startedAt)
    ),
    medianInteractionCount: median(sessions.map((s) => s.interactionCount)),
    medianContextSwitchCount: median(sessions.map((s) => s.contextSwitchCount)),
    medianSignatureDwellMs: median(
      decisions.filter((d) => d.decision === 'signed').map((d) => d.dwellMs)
    ),
    signedCount: decisions.filter((d) => d.decision === 'signed').length,
    deniedCount: decisions.filter((d) => d.decision === 'denied').length,
    evidenceOpenRate: decisions.length === 0 ? null : withEvidence / decisions.length,
  };
}

export interface ComparisonExport {
  exportedAt: string;
  metrics: MetricDefinition[];
  sessions: TaskSession[];
  events: ComparisonEvent[];
  summaries: SurfaceSummary[];
  /** Carried in the export so a reader cannot separate the numbers from the caveats. */
  interpretationWarnings: string[];
}

export function exportComparisonData(): ComparisonExport {
  const buffer = loadBuffer();
  return {
    exportedAt: new Date().toISOString(),
    metrics: COMPARISON_METRICS,
    sessions: Object.values(buffer.sessions),
    events: buffer.events,
    summaries: [summarise('classic'), summarise('copilot')],
    interpretationWarnings: [
      'A FALLING signatureDwellMs or a RISING signaturesPerHour on the Copilot surface is a DEFECT (epic §9 risk 1), not adoption. Do not present either as an improvement.',
      'Task duration is only comparable within the same taskKey. Comparing across different tasks measures the tasks, not the surfaces.',
      'Participant order must be counterbalanced. Whichever surface a participant sees second benefits from having already understood the task.',
      'The Copilot author is not a neutral measurer. Task selection and scoring should be reviewed by someone who does not own the harness.',
      'Sample sizes reachable in a demo do not support significance claims. Report medians and spreads; do not report p-values.',
    ],
  };
}

export function resetComparisonData(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* nothing useful to do */
  }
}
