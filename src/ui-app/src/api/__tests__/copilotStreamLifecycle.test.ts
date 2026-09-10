/**
 * Stream lifecycle details that a browser test cannot see.
 *
 * `tests/e2e/specs/stream-lifecycle.spec.ts` proves the two user-visible defects in a real
 * browser against a real held-open stream — that is the primary evidence and it caught what
 * unit tests could not. These tests cover the parts that are invisible from the outside:
 * the resume cursor across a run boundary, and whether a finished run is re-dispatched to
 * the reducer when the server replays it.
 */
import { openCopilotStream } from '../copilotStream';
import { CopilotEvent } from '../../components/copilot/types';

function sseBody(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
}

function frame(kind: string, seq: number, runId: string): string {
  return `id: ${seq}\nevent: ${kind}\ndata: ${JSON.stringify({ kind, seq, runId, payload: {} })}\n\n`;
}

/** Byte-for-byte what `sessions.py::_heartbeat_frame` emits: no `seq`, no `id:`. */
const HEARTBEAT = `event: heartbeat\ndata: ${JSON.stringify({ serverTs: '2026-09-10T00:00:00Z' })}\n\n`;

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
      50
    )
  );
}

describe('copilotStream lifecycle', () => {
  it('treats a heartbeat with no seq as liveness, not as an unparseable frame', async () => {
    // The real heartbeat carries no `seq`, so `toEnvelope` rejects it. Before the fix that
    // rejection happened BEFORE anything petted the watchdog, so a healthy idle stream — a
    // banker working the queue without dispatching a run — was declared degraded and every
    // card went Deny-only.
    const h = await drive([[HEARTBEAT]]);
    expect(h.statuses).toContain('live');
    h.close();
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
      [frame('run.started', 1, 'runA'), frame('run.done', 2, 'runA')],
      [HEARTBEAT],
    ]);
    expect(h.urls[0]).not.toContain('lastSeq');
    expect(h.urls[1]).toBeDefined();
    expect(h.urls[1]).not.toContain('lastSeq=2');
    expect(h.urls[1]).not.toContain('runId=runA');
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
