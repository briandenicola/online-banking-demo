/**
 * Copilot state — an external mutable store, not React state.
 *
 * NO REDUX, NO ZUSTAND, NO NEW DEPENDENCY. This repo uses plain React Context
 * and a CRA/craco build; adding a state library for one surface is not a trade
 * worth making. `useSyncExternalStore` is the React-blessed way to do exactly
 * this, ships in React 18+, and is tearing-safe under concurrent rendering.
 *
 * WHY EVENTS DO NOT GO THROUGH `setState`
 * ---------------------------------------
 * At 50–200 events/sec a `setState` per event is a re-render storm. Frames land
 * in a pending buffer and a single animation frame applies them, so a burst of
 * 40 events in 16ms produces ONE render pass. Components subscribe to narrow
 * slices (one node, one approval, the stream status), so a tool call completing
 * inside step 3 re-renders step 3 — not the run, and above all not the approval
 * dock, which is the highest-stakes component on screen and should be quietest.
 *
 * THE REDUCER IS PURE: `(state, event) => state`.
 * That is what makes the whole event protocol testable without a network, and
 * what gives us a deterministic fixture player for demos on a bad conference
 * network. All operations are idempotent upserts keyed by id — never
 * push-append — so a duplicate frame that slips past the seq check is harmless.
 */

import {
  Approval,
  Artifact,
  CopilotEvent,
  NodeStatus,
  PlanStep,
  RunState,
  StreamStatus,
  SubagentRun,
  ToolCall,
} from '../components/copilot/types';
import { logger } from '../utils/logger';

export interface CopilotState {
  runs: Record<string, RunState>;
  runIds: string[];
  approvals: Record<string, Approval>;
  approvalIds: string[];
  activeRunId?: string;
  stream: {
    status: StreamStatus;
    lastSeq: number;
    /** True while replaying buffered/snapshot frames — suppresses attention animations. */
    isDraining: boolean;
    /** Set when a gap could not be closed. A trace with holes must never look complete. */
    incomplete: boolean;
  };
}

export function emptyState(): CopilotState {
  return {
    runs: {},
    runIds: [],
    approvals: {},
    approvalIds: [],
    stream: { status: 'idle', lastSeq: 0, isDraining: false, incomplete: false },
  };
}

function emptyRun(runId: string, sessionId?: string): RunState {
  return {
    runId,
    sessionId,
    title: runId,
    status: 'queued',
    planVersion: 0,
    stepIds: [],
    steps: {},
    subagents: {},
    toolCalls: {},
    rootSubagentIds: [],
    revisions: [],
    artifacts: {},
    artifactIds: [],
    approvalIds: [],
    lastSeq: 0,
  };
}

function withRun(state: CopilotState, event: CopilotEvent): CopilotState {
  if (state.runs[event.runId]) return state;
  return {
    ...state,
    runs: { ...state.runs, [event.runId]: emptyRun(event.runId, event.sessionId) },
    runIds: state.runIds.includes(event.runId) ? state.runIds : [...state.runIds, event.runId],
    activeRunId: state.activeRunId || event.runId,
  };
}

function updateRun(
  state: CopilotState,
  runId: string,
  fn: (run: RunState) => RunState
): CopilotState {
  const run = state.runs[runId];
  if (!run) return state;
  return { ...state, runs: { ...state.runs, [runId]: fn(run) } };
}

function upsertStep(run: RunState, id: string, patch: Partial<PlanStep>): RunState {
  const existing = run.steps[id];
  const step: PlanStep = existing
    ? { ...existing, ...patch }
    : {
        id,
        index: patch.index ?? run.stepIds.length,
        title: patch.title ?? id,
        status: patch.status ?? 'pending',
        toolCallIds: [],
        subagentIds: [],
        ...patch,
      };
  return {
    ...run,
    steps: { ...run.steps, [id]: step },
    stepIds: run.stepIds.includes(id) ? run.stepIds : [...run.stepIds, id],
  };
}

function upsertTool(run: RunState, id: string, patch: Partial<ToolCall>): RunState {
  const existing = run.toolCalls[id];
  const tool: ToolCall = existing
    ? { ...existing, ...patch }
    : {
        id,
        name: patch.name ?? id,
        status: patch.status ?? 'running',
        startedAt: patch.startedAt ?? new Date(0).toISOString(),
        attempt: patch.attempt ?? 1,
        ...patch,
      };

  let next: RunState = { ...run, toolCalls: { ...run.toolCalls, [id]: tool } };

  if (tool.subagentId && next.subagents[tool.subagentId]) {
    const parent = next.subagents[tool.subagentId];
    if (!parent.toolCallIds.includes(id)) {
      next = {
        ...next,
        subagents: {
          ...next.subagents,
          [tool.subagentId]: { ...parent, toolCallIds: [...parent.toolCallIds, id] },
        },
      };
    }
  } else if (tool.stepId && next.steps[tool.stepId]) {
    const parent = next.steps[tool.stepId];
    if (!parent.toolCallIds.includes(id)) {
      next = {
        ...next,
        steps: { ...next.steps, [tool.stepId]: { ...parent, toolCallIds: [...parent.toolCallIds, id] } },
      };
    }
  }

  return next;
}

function upsertSubagent(run: RunState, id: string, patch: Partial<SubagentRun>): RunState {
  const existing = run.subagents[id];
  const subagent: SubagentRun = existing
    ? { ...existing, ...patch }
    : {
        id,
        parentStepId: patch.parentStepId ?? '',
        name: patch.name ?? id,
        role: patch.role ?? 'specialist',
        status: patch.status ?? 'running',
        startedAt: patch.startedAt ?? new Date(0).toISOString(),
        toolCallIds: [],
        childIds: [],
        depth: patch.depth ?? 1,
        ...patch,
      };

  let next: RunState = { ...run, subagents: { ...run.subagents, [id]: subagent } };

  if (subagent.parentSubagentId && next.subagents[subagent.parentSubagentId]) {
    const parent = next.subagents[subagent.parentSubagentId];
    if (!parent.childIds.includes(id)) {
      next = {
        ...next,
        subagents: {
          ...next.subagents,
          [subagent.parentSubagentId]: { ...parent, childIds: [...parent.childIds, id] },
        },
      };
    }
  } else if (subagent.parentStepId && next.steps[subagent.parentStepId]) {
    const parent = next.steps[subagent.parentStepId];
    if (!parent.subagentIds.includes(id)) {
      next = {
        ...next,
        steps: {
          ...next.steps,
          [subagent.parentStepId]: { ...parent, subagentIds: [...parent.subagentIds, id] },
        },
      };
    }
  } else if (!next.rootSubagentIds.includes(id)) {
    // The supervisor agent has no parent step: it renders as a SIBLING of the
    // root plan, not a child of it. That visual separation is the UI's assertion
    // that its opinion was formed independently, so the data model has to keep
    // it separate too.
    next = { ...next, rootSubagentIds: [...next.rootSubagentIds, id] };
  }

  return next;
}

function upsertArtifact(run: RunState, artifact: Artifact): RunState {
  const existing = run.artifacts[artifact.id];
  // Revisions only move forward. A late-arriving older revision after a
  // reconnect must not overwrite a newer one.
  if (existing && existing.revision > artifact.revision) return run;
  return {
    ...run,
    artifacts: { ...run.artifacts, [artifact.id]: artifact },
    artifactIds: run.artifactIds.includes(artifact.id)
      ? run.artifactIds
      : [...run.artifactIds, artifact.id],
  };
}

function putApproval(state: CopilotState, approval: Approval): CopilotState {
  return {
    ...state,
    approvals: { ...state.approvals, [approval.id]: approval },
    approvalIds: state.approvalIds.includes(approval.id)
      ? state.approvalIds
      : [...state.approvalIds, approval.id],
  };
}

/**
 * The reducer. Pure, exhaustive over `CopilotEventKind`.
 *
 * The `switch` has no `default` that swallows: a new kind added server-side
 * without a handler here is a compile error, which is the entire reason the
 * envelope is a discriminated union rather than `{ kind: string }`.
 */
export function reduce(state: CopilotState, event: CopilotEvent): CopilotState {
  const base = withRun(state, event);
  const stamped = updateRun(base, event.runId, (run) => ({
    ...run,
    lastSeq: Math.max(run.lastSeq, event.seq),
  }));

  switch (event.kind) {
    case 'run.started': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) => ({
        ...run,
        title: p.title,
        intent: p.intent,
        status: 'running',
        startedAt: p.startedAt,
      }));
    }

    case 'plan.proposed': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        p.steps.reduce(
          (acc, seed) => upsertStep(acc, seed.id, seed),
          { ...run, planVersion: p.version }
        )
      );
    }

    case 'plan.revised': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) => {
        // Removed steps are marked skipped, NOT deleted. Vanishing steps destroy
        // trust: the banker who watched step 4 appear must be able to see what
        // happened to it.
        let next = { ...run, planVersion: p.version, revisions: [...run.revisions, {
          version: p.version,
          at: p.at,
          reason: p.reason,
          addedStepIds: p.addedStepIds,
          removedStepIds: p.removedStepIds,
          supersededApprovalId: p.supersededApprovalId,
        }] };

        for (const removedId of p.removedStepIds) {
          next = upsertStep(next, removedId, {
            status: 'skipped' as NodeStatus,
            supersededReason: p.reason,
          });
        }
        for (const seed of p.steps) {
          next = upsertStep(next, seed.id, seed);
        }
        return next;
      });
    }

    case 'step.started': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertStep(run, p.stepId, {
          index: p.index,
          title: p.title,
          status: 'running',
          startedAt: event.ts,
        })
      );
    }

    case 'step.completed': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertStep(run, p.stepId, {
          status: 'complete',
          durationMs: p.durationMs,
          summary: p.summary,
        })
      );
    }

    case 'step.failed': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertStep(run, p.stepId, {
          status: p.willRetry ? 'retrying' : 'failed',
          error: p.error,
        })
      );
    }

    case 'tool.started': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertTool(run, p.toolCallId, {
          name: p.name,
          args: p.args,
          status: 'running',
          startedAt: event.ts,
          attempt: p.attempt,
          stepId: p.stepId,
          subagentId: p.subagentId,
          traceId: p.traceId,
          spanId: p.spanId,
        })
      );
    }

    case 'tool.completed': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertTool(run, p.toolCallId, {
          status: 'complete',
          durationMs: p.durationMs,
          resultSummary: p.resultSummary,
        })
      );
    }

    case 'tool.failed': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertTool(run, p.toolCallId, {
          status: p.willRetry ? 'retrying' : 'failed',
          error: p.error,
          attempt: p.attempt,
        })
      );
    }

    case 'subagent.spawned': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertSubagent(run, p.subagentId, {
          parentStepId: p.parentStepId,
          parentSubagentId: p.parentSubagentId,
          parentRunId: p.parentRunId,
          name: p.name,
          role: p.role,
          depth: p.depth,
          status: 'running',
          startedAt: event.ts,
        })
      );
    }

    case 'subagent.progress': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertSubagent(run, p.subagentId, { note: p.note, toolCallCount: p.toolCallCount })
      );
    }

    case 'subagent.completed': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertSubagent(run, p.subagentId, {
          status: p.status,
          confidence: p.confidence,
          verdictSummary: p.verdictSummary,
          durationMs: p.durationMs,
        })
      );
    }

    case 'approval.required': {
      const p = event.payload;
      const withApproval = putApproval(stamped, p.approval);
      return updateRun(withApproval, event.runId, (run) => ({
        ...run,
        status: 'awaiting_approval',
        approvalIds: run.approvalIds.includes(p.approval.id)
          ? run.approvalIds
          : [...run.approvalIds, p.approval.id],
      }));
    }

    case 'approval.updated': {
      return putApproval(stamped, event.payload.approval);
    }

    case 'approval.terminal': {
      const p = event.payload;
      const existing = stamped.approvals[p.approvalId];
      if (!existing) return stamped;
      if (p.state === 'denied' && !p.terminalReason) {
        logger.error(
          `copilotStore: approval.terminal for ${p.approvalId} is a denial with no ` +
            'terminalReason. All four denial causes share one status; without the reason ' +
            'the UI cannot tell a policy void from a human rejection.'
        );
      }
      return putApproval(stamped, {
        ...existing,
        status: p.state,
        terminalReason: p.terminalReason,
        terminalDetail: p.terminalDetail,
        terminalAt: p.terminalAt,
        supersededByApprovalId: p.supersededByApprovalId,
        previousPayloadHash: p.previousPayloadHash,
        callerMaySign: false,
      });
    }

    case 'artifact.created':
    case 'artifact.updated': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) =>
        upsertArtifact(run, {
          id: p.artifactId,
          kind: p.kind,
          title: p.title,
          revision: p.revision,
          content: p.content,
        })
      );
    }

    case 'run.error': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) => ({
        ...run,
        error: p,
        status: p.recoverable ? run.status : 'failed',
      }));
    }

    case 'run.done': {
      const p = event.payload;
      return updateRun(stamped, event.runId, (run) => ({
        ...run,
        status: p.status,
        durationMs: p.durationMs,
        finalSeq: p.finalSeq,
      }));
    }

    case 'heartbeat':
      return stamped;
  }
}

type Listener = () => void;

export interface CopilotStore {
  getSnapshot(): CopilotState;
  subscribe(listener: Listener): () => void;
  /** Buffered — applied on the next frame. Use for stream events. */
  dispatch(event: CopilotEvent): void;
  /** Applied synchronously. Use for replay, tests, and snapshot resync. */
  dispatchSync(event: CopilotEvent): void;
  setStreamStatus(status: StreamStatus): void;
  setIncomplete(incomplete: boolean): void;
  setDraining(draining: boolean): void;
  putApproval(approval: Approval): void;
  setActiveRun(runId: string): void;
  reset(): void;
  flush(): void;
}

export function createCopilotStore(initial?: CopilotState): CopilotStore {
  let state = initial || emptyState();
  const listeners = new Set<Listener>();
  let queue: CopilotEvent[] = [];
  let frame: number | null = null;

  function notify(): void {
    listeners.forEach((l) => l());
  }

  function apply(events: CopilotEvent[]): void {
    if (events.length === 0) return;
    let next = state;
    let maxSeq = state.stream.lastSeq;
    for (const event of events) {
      next = reduce(next, event);
      maxSeq = Math.max(maxSeq, event.seq);
    }
    state = { ...next, stream: { ...next.stream, lastSeq: maxSeq } };
    notify();
  }

  function schedule(): void {
    if (frame !== null) return;
    const raf =
      typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function'
        ? window.requestAnimationFrame
        : (cb: FrameRequestCallback) => setTimeout(() => cb(Date.now()), 16) as unknown as number;

    frame = raf(() => {
      frame = null;
      const batch = queue;
      queue = [];
      apply(batch);
    }) as unknown as number;
  }

  return {
    getSnapshot: () => state,

    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    dispatch(event) {
      queue.push(event);
      schedule();
    },

    dispatchSync(event) {
      apply([event]);
    },

    setStreamStatus(status) {
      if (state.stream.status === status) return;
      state = { ...state, stream: { ...state.stream, status } };
      notify();
    },

    setIncomplete(incomplete) {
      if (state.stream.incomplete === incomplete) return;
      state = { ...state, stream: { ...state.stream, incomplete } };
      notify();
    },

    setDraining(draining) {
      if (state.stream.isDraining === draining) return;
      state = { ...state, stream: { ...state.stream, isDraining: draining } };
      notify();
    },

    putApproval(approval) {
      state = putApproval(state, approval);
      notify();
    },

    setActiveRun(runId) {
      if (state.activeRunId === runId) return;
      state = { ...state, activeRunId: runId };
      notify();
    },

    reset() {
      state = emptyState();
      queue = [];
      notify();
    },

    flush() {
      const batch = queue;
      queue = [];
      apply(batch);
    },
  };
}
