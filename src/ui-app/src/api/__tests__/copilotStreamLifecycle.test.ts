/**
 * Stream lifecycle details that a browser test cannot see.
 *
 * `tests/e2e/specs/stream-lifecycle.spec.ts` proves the two user-visible defects in a real
 * browser against a real held-open stream — that is the primary evidence and it caught what
 * unit tests could not. These tests cover the parts that are invisible from the outside:
 * the resume cursor across a run boundary, and whether a finished run is re-dispatched to
 * the reducer when the server replays it.
 */
import { TextDecoder as NodeTextDecoder, TextEncoder as NodeTextEncoder } from 'util';
import { openCopilotStream } from '../copilotStream';

// jsdom ships neither `TextEncoder` nor `TextDecoder`. Without them the client's decode step
// throws inside `connect()`, the error is caught as a lost connection, and every frame
// disappears — the suite then reports a reconnect loop that is an artefact of the test
// environment rather than of the code under test.
const globals = global as unknown as Record<string, unknown>;
if (typeof globals.TextEncoder === 'undefined') globals.TextEncoder = NodeTextEncoder;
if (typeof globals.TextDecoder === 'undefined') globals.TextDecoder = NodeTextDecoder;
import { CopilotEvent } from '../../components/copilot/types';

/**
 * A minimal reader rather than a real `ReadableStream`.
 *
 * jsdom has no `ReadableStream`, so constructing one here yields a body the client can never
 * read — every frame silently vanishes and the test "passes" for the wrong reason. The client
 * only ever calls `body.getReader()`, so supply exactly that.
 */
function sseBody(chunks: string[]): { getReader: () => { read: () => Promise<{ done: boolean; value?: Uint8Array }> } } {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    getReader: () => ({
      read: () =>
        Promise.resolve(
          i < chunks.length
            ? { done: false, value: encoder.encode(chunks[i++]) }
            : { done: true, value: undefined }
        ),
    }),
  };
}

function frame(kind: string, seq: number, runId: string): string {
  return `id: ${seq}\nevent: ${kind}\ndata: ${JSON.stringify({ kind, seq, runId, payload: {} })}\n\n`;
}

/** Byte-for-byte what `sessions.py::_heartbeat_frame` emits: no `seq`, no `id:`. */
const HEARTBEAT = `event: heartbeat\ndata: ${JSON.stringify({ serverTs: '2026-09-10T00:00:00Z' })}\n\n`;

/** Reconnect uses a 500ms base with jitter, so a second attach needs ~1.5s of real time. */
const SETTLE_MS = 1600;

/**
 * A stream that stays OPEN and heartbeats, the way a healthy idle session does.
 *
 * A body that ends after its chunks is a disconnect, and the reconnect that follows masks
 * whatever the watchdog was about to do. To test the watchdog the connection has to live.
 */
function heldHeartbeatBody(everyMs: number): {
  getReader: () => { read: () => Promise<{ done: boolean; value?: Uint8Array }> };
} {
  const encoder = new TextEncoder();
  return {
    getReader: () => ({
      read: () =>
        new Promise((resolve) =>
          setTimeout(() => resolve({ done: false, value: encoder.encode(HEARTBEAT) }), everyMs)
        ),
    }),
  };
}

interface Harness {
  urls: string[];
  events: CopilotEvent[];
  statuses: string[];
  close: () => void;
}

function drive(bodies: string[][]): Promise<Harness> {
  const urls: string[] = [];
  const events: CopilotEvent[] = [];
  const statuses: string[] = [];
  let call = 0;

  const fetchImpl = ((url: string) => {
    urls.push(url);
    const body = bodies[Math.min(call, bodies.length - 1)];
    call += 1;
    return Promise.resolve({
      ok: true,
      status: 200,
      body: sseBody(body),
    } as unknown as Response);
  }) as unknown as typeof fetch;

  const handle = openCopilotStream({
    sessionId: 'sess_1',
    onEvent: (event) => events.push(event),
    onStatusChange: (status) => statuses.push(status),
    fetchImpl,
    getToken: () => 'test-token',
  });

  return new Promise((resolve) =>
    setTimeout(
      () => resolve({ urls, events, statuses, close: () => handle.close() }),
      SETTLE_MS
    )
  );
}

describe('copilotStream lifecycle', () => {
  it('is not declared degraded by a stream that is heartbeating perfectly', async () => {
    // THE QUEUE-ONLY KILLER. The real heartbeat carries no `seq`, so `toEnvelope` rejected it
    // before anything could pet the watchdog. A banker who loaded /copilot to work the queue
    // and never dispatched a run therefore watched a healthy connection be declared degraded,
    // and `canSignUnderStream` (correctly, on the information it was given) disabled signing
    // on every card. The gate was right; the input to it was a lie.
    //
    // The shipped watchdog is 15000ms x 2. Squeeze it via the same runtime config a deployment
    // uses so the window fits in a test.
    (window as unknown as { __RUNTIME_CONFIG__: unknown }).__RUNTIME_CONFIG__ = {
      copilot: { heartbeatIntervalMs: 200, missedHeartbeatsBeforeDegraded: 2 },
    };

    const statuses: string[] = [];
    const fetchImpl = (() =>
      Promise.resolve({ ok: true, status: 200, body: heldHeartbeatBody(120) } as unknown as Response)) as unknown as typeof fetch;

    const handle = openCopilotStream({
      sessionId: 'sess_1',
      onEvent: () => undefined,
      onStatusChange: (status) => statuses.push(status),
      fetchImpl,
      getToken: () => 'test-token',
    });

    await new Promise((resolve) => setTimeout(resolve, 1200));
    handle.close();
    delete (window as unknown as { __RUNTIME_CONFIG__?: unknown }).__RUNTIME_CONFIG__;

    // Six watchdog windows' worth of a connection that never missed a beat.
    expect(statuses).not.toContain('degraded');
    expect(statuses).toContain('live');
  });

  it('does not claim a signable status merely because the server answered 200', async () => {
    // A session-scoped attach to a finished run also answers 200 and then says nothing.
    const h = await drive([[]]);
    expect(h.statuses).not.toContain('live');
    expect(h.statuses).not.toContain('resumed');
    h.close();
  });

  it('resets the resume cursor at a run boundary so the next run is not swallowed', async () => {
    // `seq` is scoped to the RUN (`bus.py`: `RunStream._seq` starts at 0 per run). Carrying
    // run A's cursor of 4 into run B would make the server replay from seq 5 and silently
    // drop run B's first four frames — a trace with a hole in it that looks complete.
    const h = await drive([
      [
        frame('run.started', 1, 'runA'),
        frame('run.done', 2, 'runA'),
        frame('run.started', 1, 'runB'),
        frame('step.started', 2, 'runB'),
      ],
    ]);
    expect(h.urls[0]).not.toContain('lastSeq');
    // Originally this asserted the cursor on a RECONNECT. The client no longer reconnects
    // after a finished run — it opens zero further connections — so the guarantee is now
    // proven where it actually matters: runB's frames arriving on the SAME connection must
    // not be swallowed as duplicates of runA's seq 1 and 2. The requirement is unchanged;
    // only the path that exercises it is.
    const runB = h.events.filter((event) => event.runId === 'runB');
    expect(runB.map((event) => event.seq)).toEqual([1, 2]);
    h.close();
  });

  it('does not re-dispatch a finished run when the server replays it', async () => {
    const h = await drive([
      [frame('run.started', 1, 'runA'), frame('run.done', 2, 'runA')],
      [frame('run.started', 1, 'runA'), frame('run.done', 2, 'runA')],
    ]);
    const runA = h.events.filter((event) => event.runId === 'runA');
    expect(runA).toHaveLength(2);
    h.close();
  });
});

/**
 * The storm, measured rather than reasoned about.
 *
 * Brian's browser: 213 requests / 8.5 MB in one short session, dominated by repeated attaches
 * to a run that had finished in three seconds. My first fix only made the loop back off — it
 * turned a 500ms storm into a 15s one, which is still unbounded over a demo's length.
 *
 * The rule now under test is absolute: once a run has ended, the client opens ZERO further
 * connections. Anything else is a cap, not a fix.
 */
describe('a finished run stops the connection loop outright', () => {
  it('never reattaches after the terminal frame, however long we wait', async () => {
    const done = [frame('run.started', 1, 'runA'), frame('run.done', 2, 'runA')];
    // Every subsequent attach would replay the same finished run — exactly what the server
    // does via `latest_for_session` on a closed run.
    const h = await drive([done, done, done, done, done]);

    expect(h.urls).toHaveLength(1);
    h.close();
  });

  it('settles on a status that keeps the signing gate shut, rather than churning', async () => {
    // Not signable — and honestly so. `approval.updated` only ever arrives on a RUN stream
    // (`planner/fanout.py:649`), so with the run closed there is genuinely nothing to verify
    // freshness against. The gate must stay shut; it must not be reopened to hide the churn.
    const done = [frame('run.started', 1, 'runA'), frame('run.done', 2, 'runA')];
    const h = await drive([done, done, done]);

    expect(h.statuses[h.statuses.length - 1]).toBe('closed');
    expect(['live', 'resumed']).not.toContain(h.statuses[h.statuses.length - 1]);
    h.close();
  });

  it('still reconnects when the run is UNFINISHED — the stop must be causal, not blanket', async () => {
    // A dropped connection mid-run is the case reconnect exists for. If the fix suppressed
    // that too it would be a regression dressed as a fix.
    const midRun = [frame('run.started', 1, 'runB'), frame('step.started', 2, 'runB')];
    const h = await drive([midRun, midRun, midRun]);

    expect(h.urls.length).toBeGreaterThan(1);
    h.close();
  });
});
