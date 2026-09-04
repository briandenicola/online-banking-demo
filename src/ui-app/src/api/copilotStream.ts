/**
 * Copilot SSE client — `fetch` + `ReadableStream`, NOT native `EventSource`.
 *
 * ============================================================================
 * WHY NOT `EventSource`
 * ============================================================================
 * `EventSource` cannot set an `Authorization` header. Our token lives in
 * `localStorage` and is attached by an axios interceptor. Using `EventSource`
 * would force the token into the query string, where it lands in nginx access
 * logs, browser history, and every APM span — unacceptable for a banking demo
 * we hold up as a security exemplar.
 *
 * `fetch` + `ReadableStream` gives us headers, `AbortSignal` cancellation, and
 * real HTTP status codes on connect. The SSE frame parser below is small
 * because SSE is a small format; that is the whole trade.
 *
 * INFRA DEPENDENCY, already satisfied: the gateway sets `proxy_buffering off`
 * on `/api/copilot/`. Without it nginx accumulates the whole stream and delivers
 * it in one lump at the end — a live trace becomes a post-mortem.
 *
 * ORDERING GUARANTEES THIS CLIENT PROVIDES
 * ----------------------------------------
 *  - duplicates (`seq <= lastSeq`) are dropped; the reducer is idempotent anyway
 *  - a gap (`seq > lastSeq + 1`) buffers out-of-order frames, and if it cannot be
 *    closed within `gapResyncTimeoutMs` the caller is told to resync
 *  - a known-incomplete trace is NEVER presented as complete
 */

import { getCopilotConfig, copilotUrl } from '../config/copilotConfig';
import { logger } from '../utils/logger';
import {
  COPILOT_EVENT_KINDS,
  CopilotEvent,
  CopilotEventKind,
  StreamStatus,
} from '../components/copilot/types';

export interface CopilotStreamOptions {
  sessionId: string;
  /**
   * Watch one specific run. Omitted, the server attaches to the session's
   * latest — which is what the UI wants when it starts a run and then subscribes.
   */
  runId?: string;
  /** Resume cursor. The server replays from `lastSeq + 1`. */
  lastSeq?: number;
  onEvent: (event: CopilotEvent) => void;
  onStatusChange: (status: StreamStatus) => void;
  /**
   * A gap could not be closed. Carries the run whose trace is holed, because
   * `seq` is run-scoped — recovering "the session" would mean rebuilding one
   * run's trace from another run's frames.
   */
  onResyncRequired?: (fromSeq: number, runId?: string) => void;
  /** Injectable for tests; defaults to the global. */
  fetchImpl?: typeof fetch;
  /** Injectable for tests; defaults to reading `auth_token` from localStorage. */
  getToken?: () => string | null;
}

export interface CopilotStreamHandle {
  close(): void;
  status(): StreamStatus;
  lastSeq(): number;
}

interface RawFrame {
  event?: string;
  data: string;
  id?: string;
}

/**
 * Parses one SSE wire chunk into frames.
 *
 * Exported for tests: the frame parser is the part most likely to be subtly
 * wrong (CRLF handling, multi-line `data:`, comment keep-alives) and it is
 * cheap to test directly.
 */
export function parseSseChunk(buffer: string): { frames: RawFrame[]; rest: string } {
  const frames: RawFrame[] = [];
  const normalised = buffer.replace(/\r\n/g, '\n');
  const blocks = normalised.split('\n\n');
  const rest = blocks.pop() ?? '';

  for (const block of blocks) {
    if (!block.trim()) continue;
    const frame: RawFrame = { data: '' };
    const dataLines: string[] = [];

    for (const line of block.split('\n')) {
      // A line starting with ':' is a comment / keep-alive. nginx and FastAPI
      // both emit these; treating one as data would break JSON parsing.
      if (line.startsWith(':')) continue;
      const sep = line.indexOf(':');
      const field = sep === -1 ? line : line.slice(0, sep);
      const value = sep === -1 ? '' : line.slice(sep + 1).replace(/^ /, '');

      if (field === 'event') frame.event = value;
      else if (field === 'id') frame.id = value;
      else if (field === 'data') dataLines.push(value);
    }

    if (dataLines.length === 0) continue;
    frame.data = dataLines.join('\n');
    frames.push(frame);
  }

  return { frames, rest };
}

function isKnownKind(kind: string): kind is CopilotEventKind {
  return (COPILOT_EVENT_KINDS as string[]).includes(kind);
}

/**
 * Turns a raw frame into an envelope, or null.
 *
 * Unknown kinds are logged and dropped rather than thrown (§7.4): a server that
 * ships a new event kind before the client does must degrade, not blank the
 * approval dock.
 */
export function toEnvelope(frame: RawFrame): CopilotEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(frame.data);
  } catch {
    logger.warn('copilotStream: unparseable frame data dropped');
    return null;
  }

  if (!parsed || typeof parsed !== 'object') return null;
  const candidate = parsed as Record<string, unknown>;

  // The `event:` field and the envelope `kind` must agree. When only one is
  // present, use it; when they disagree, trust the envelope — it is the
  // persisted artifact that #333 replays.
  const kind = (typeof candidate.kind === 'string' ? candidate.kind : frame.event) ?? '';
  if (!isKnownKind(kind)) {
    logger.warn(`copilotStream: unknown event kind "${kind}" ignored`);
    return null;
  }

  if (typeof candidate.seq !== 'number') {
    logger.warn(`copilotStream: frame of kind ${kind} has no numeric seq; dropped`);
    return null;
  }

  return { ...(candidate as object), kind } as CopilotEvent;
}

function defaultToken(): string | null {
  try {
    return window.localStorage.getItem('auth_token');
  } catch {
    return null;
  }
}

export function openCopilotStream(opts: CopilotStreamOptions): CopilotStreamHandle {
  const config = getCopilotConfig();
  const doFetch = opts.fetchImpl || (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : null);
  const readToken = opts.getToken || defaultToken;

  let status: StreamStatus = 'idle';
  let lastSeq = opts.lastSeq ?? 0;
  // The run whose frames we are currently tracking. Recorded from the stream
  // itself rather than assumed from the caller, because `seq` is run-scoped and
  // a resync must rebuild the run that actually has the hole in it.
  let currentRunId = opts.runId;
  let closed = false;
  let attempt = 0;
  let controller: AbortController | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  let gapTimer: ReturnType<typeof setTimeout> | null = null;
  const pending = new Map<number, CopilotEvent>();

  function setStatus(next: StreamStatus): void {
    if (status === next) return;
    status = next;
    opts.onStatusChange(next);
  }

  function clearGapTimer(): void {
    if (gapTimer) {
      clearTimeout(gapTimer);
      gapTimer = null;
    }
  }

  function armHeartbeatWatchdog(): void {
    if (heartbeatTimer) clearTimeout(heartbeatTimer);
    // A half-open TCP connection is indistinguishable from "the agent is
    // thinking" without this, which is the worst possible ambiguity on a surface
    // whose whole promise is that you are watching something happen.
    heartbeatTimer = setTimeout(
      () => {
        if (closed) return;
        logger.warn('copilotStream: heartbeat watchdog fired; forcing reconnect');
        setStatus('degraded');
        abortCurrent();
      },
      config.heartbeatIntervalMs * config.missedHeartbeatsBeforeDegraded
    );
  }

  function emit(event: CopilotEvent): void {
    lastSeq = event.seq;
    opts.onEvent(event);
  }

  function drainPending(): void {
    let progressed = true;
    while (progressed) {
      progressed = false;
      const next = pending.get(lastSeq + 1);
      if (next) {
        pending.delete(lastSeq + 1);
        emit(next);
        progressed = true;
      }
    }
    if (pending.size === 0) clearGapTimer();
  }

  function handleEvent(event: CopilotEvent): void {
    armHeartbeatWatchdog();
    if (event.runId) currentRunId = event.runId;

    if (status !== 'live' && status !== 'resumed') {
      setStatus(lastSeq > 0 ? 'resumed' : 'live');
    }

    if (event.seq <= lastSeq) return; // duplicate replay after a reconnect

    if (event.seq === lastSeq + 1) {
      emit(event);
      drainPending();
      return;
    }

    // Gap. Buffer and wait; if it does not close, the caller must snapshot.
    if (pending.size < config.gapBufferLimit) pending.set(event.seq, event);

    if (!gapTimer) {
      const from = lastSeq;
      gapTimer = setTimeout(() => {
        gapTimer = null;
        pending.clear();
        logger.error(`copilotStream: unable to close seq gap after ${from}; resync required`);
        setStatus('degraded');
        if (opts.onResyncRequired) opts.onResyncRequired(from, currentRunId);
      }, config.gapResyncTimeoutMs);
    }
  }

  function abortCurrent(): void {
    if (controller) {
      controller.abort();
      controller = null;
    }
  }

  function backoffDelay(): number {
    // Exponential with jitter. Jitter matters more than it looks: without it a
    // gateway restart reconnects every open browser in lockstep.
    const exponential = Math.min(config.reconnectMaxMs, config.reconnectBaseMs * 2 ** attempt);
    return exponential / 2 + Math.random() * (exponential / 2);
  }

  function scheduleReconnect(): void {
    if (closed) return;
    attempt += 1;
    setStatus(attempt > 2 ? 'degraded' : 'reconnecting');
    const delay = backoffDelay();
    reconnectTimer = setTimeout(connect, delay);
  }

  async function connect(): Promise<void> {
    if (closed) return;
    if (!doFetch) {
      logger.error('copilotStream: fetch is unavailable in this environment');
      setStatus('failed');
      return;
    }

    setStatus(lastSeq > 0 ? 'reconnecting' : 'connecting');
    controller = new AbortController();

    const query = new URLSearchParams();
    if (currentRunId) query.set('runId', currentRunId);
    if (lastSeq > 0) query.set('lastSeq', String(lastSeq));
    const search = query.toString();
    const url = `${copilotUrl(config.endpoints.sessionStream, { sessionId: opts.sessionId })}${
      search ? `?${search}` : ''
    }`;

    const headers: Record<string, string> = { Accept: 'text/event-stream' };
    const token = readToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    // Standard SSE resume header, sent alongside the query param so the server
    // may honour either.
    if (lastSeq > 0) headers['Last-Event-ID'] = String(lastSeq);

    try {
      const response = await doFetch(url, {
        method: 'GET',
        headers,
        signal: controller.signal,
        cache: 'no-store',
      });

      if (response.status === 409) {
        // The replay window has passed us by. A snapshot is the only honest
        // recovery; silently continuing would render a trace with holes in it.
        logger.warn('copilotStream: server reports resync_required');
        pending.clear();
        if (opts.onResyncRequired) opts.onResyncRequired(lastSeq, currentRunId);
        setStatus('degraded');
        scheduleReconnect();
        return;
      }

      if (response.status === 401 || response.status === 403) {
        // Not retryable by backoff. Retrying an auth failure forever just hides
        // it behind a spinner.
        logger.error(`copilotStream: authentication failed (${response.status})`);
        setStatus('failed');
        return;
      }

      if (!response.ok || !response.body) {
        throw new Error(`stream open failed: ${response.status}`);
      }

      attempt = 0;
      setStatus(lastSeq > 0 ? 'resumed' : 'live');
      armHeartbeatWatchdog();

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { frames, rest } = parseSseChunk(buffer);
        buffer = rest;
        for (const frame of frames) {
          const envelope = toEnvelope(frame);
          if (envelope) handleEvent(envelope);
        }
      }

      if (!closed) {
        setStatus('reconnecting');
        scheduleReconnect();
      }
    } catch (error) {
      if (closed || (error as Error)?.name === 'AbortError') return;
      logger.warn('copilotStream: connection lost', error);
      scheduleReconnect();
    }
  }

  connect();

  return {
    close(): void {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (heartbeatTimer) clearTimeout(heartbeatTimer);
      clearGapTimer();
      abortCurrent();
      setStatus('closed');
    },
    status: () => status,
    lastSeq: () => lastSeq,
  };
}
