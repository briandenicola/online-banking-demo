/**
 * Harness session API — `banker-copilot-service`.
 *
 * Open a session, start a run inside it, send a turn, read back a persisted
 * trace. Everything else arrives on the SSE stream. Note what is NOT here:
 * nothing that writes to the banking domain. The harness's only write
 * affordance is `propose_action`, which it exercises server-side against
 * `authority-service`; the browser never has a path from this file to a state
 * change.
 *
 * A RUN IS NOT A SESSION. `seq` is run-scoped, which is what makes each trace
 * independently replayable — a session with three runs has three traces, not
 * one. Gap detection and snapshot recovery are therefore both keyed by runId,
 * and getting that wrong would mean resyncing one run from another's frames.
 */

import apiClient from './client';
import { copilotUrl, getCopilotConfig } from '../config/copilotConfig';
import { CopilotEvent } from '../components/copilot/types';

export interface CopilotSession {
  sessionId: string;
  agentId?: string;
  policyId?: string;
  capabilities?: string[];
  traceUrl?: string;
  expiresAt?: string;
}

export interface CreateSessionArgs {
  objective: string;
  context?: Record<string, unknown>;
}

export async function createSession(args: CreateSessionArgs): Promise<CopilotSession> {
  const { endpoints } = getCopilotConfig();
  const response = await apiClient.post<CopilotSession>(copilotUrl(endpoints.sessions), {
    objective: args.objective,
    context: args.context || {},
  });
  return response.data;
}

export interface StartRunResult {
  runId: string;
  sessionId: string;
  status: string;
  traceUrl?: string;
}

export interface StartRunArgs {
  objective?: string;
  actionId?: string;
  payload?: Record<string, unknown>;
  facts?: Record<string, unknown>;
}

/** Start one planner execution inside an existing session. */
export async function startRun(
  sessionId: string,
  args: StartRunArgs = {}
): Promise<StartRunResult> {
  const { endpoints } = getCopilotConfig();
  const response = await apiClient.post<StartRunResult>(
    copilotUrl(endpoints.sessionRuns, { sessionId }),
    args
  );
  return response.data;
}

export interface SendMessageResult {
  accepted: boolean;
  seq?: number;
}

export async function sendMessage(sessionId: string, content: string): Promise<SendMessageResult> {
  const { endpoints } = getCopilotConfig();
  const response = await apiClient.post<SendMessageResult>(
    copilotUrl(endpoints.sessionMessages, { sessionId }),
    { content }
  );
  return response.data;
}

export interface RunTrace {
  events: CopilotEvent[];
  /**
   * The server could not persist every frame. Propagated rather than swallowed:
   * a trace with holes must never be presented as a complete record, least of
   * all to someone deciding whether to sign against it.
   */
  degraded: boolean;
}

/**
 * The persisted trace for one run.
 *
 * The recovery path when a seq gap cannot be closed. It returns the same
 * envelopes the stream emitted — not a bespoke "current state" shape — so the
 * client rebuilds by replaying them through the same reducer the live stream
 * uses. One code path, so a resynced trace cannot diverge from a live one.
 *
 * This reads the persistence sink rather than the service's in-process buffer,
 * so a trace that failed to persist reads as MISSING here instead of being
 * reconstructed from memory and looking complete. It is the same endpoint eval
 * replay uses (#333) — one trace, one reader, no second definition to drift.
 */
export async function fetchRunTrace(runId: string): Promise<RunTrace> {
  const { endpoints } = getCopilotConfig();
  const response = await apiClient.get<{ frames?: CopilotEvent[]; traceDegraded?: boolean }>(
    copilotUrl(endpoints.runTrace, { runId })
  );
  return {
    events: Array.isArray(response.data?.frames) ? response.data.frames : [],
    degraded: Boolean(response.data?.traceDegraded),
  };
}
