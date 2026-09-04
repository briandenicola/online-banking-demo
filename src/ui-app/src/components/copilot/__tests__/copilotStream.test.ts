/**
 * SSE-over-fetch parsing tests.
 *
 * `EventSource` is not used here — it cannot carry an Authorization header, and
 * the workaround (a token in the query string) puts a bearer token into nginx
 * access logs, browser history, and APM spans. So we parse the wire format
 * ourselves, which means the parser is ours to get right and ours to test.
 */

import { parseSseChunk, toEnvelope } from '../../../api/copilotStream';

describe('parseSseChunk', () => {
  it('parses a single complete frame', () => {
    const { frames, rest } = parseSseChunk('id: 1\ndata: {"a":1}\n\n');
    expect(frames).toHaveLength(1);
    expect(frames[0].id).toBe('1');
    expect(frames[0].data).toBe('{"a":1}');
    expect(rest).toBe('');
  });

  it('holds a partial frame back until the terminator arrives', () => {
    // TCP does not respect message boundaries. A frame split across two reads
    // must not be parsed as two half-frames.
    const first = parseSseChunk('data: {"a":');
    expect(first.frames).toHaveLength(0);

    const second = parseSseChunk(first.rest + '1}\n\n');
    expect(second.frames).toHaveLength(1);
    expect(second.frames[0].data).toBe('{"a":1}');
  });

  it('joins multi-line data fields with newlines, per the SSE spec', () => {
    const { frames } = parseSseChunk('data: line one\ndata: line two\n\n');
    expect(frames[0].data).toBe('line one\nline two');
  });

  it('normalises CRLF', () => {
    const { frames } = parseSseChunk('id: 7\r\ndata: {"a":1}\r\n\r\n');
    expect(frames).toHaveLength(1);
    expect(frames[0].id).toBe('7');
  });

  it('ignores comment keep-alives', () => {
    // nginx and some proxies emit `:` lines to hold the connection open. They
    // are not events and must not reach the reducer.
    const { frames } = parseSseChunk(': keep-alive\n\ndata: {"a":1}\n\n');
    expect(frames).toHaveLength(1);
    expect(frames[0].data).toBe('{"a":1}');
  });

  it('parses several frames from one chunk', () => {
    const { frames } = parseSseChunk('data: {"a":1}\n\ndata: {"a":2}\n\n');
    expect(frames.map((f) => f.data)).toEqual(['{"a":1}', '{"a":2}']);
  });
});

describe('toEnvelope', () => {
  const valid = JSON.stringify({
    id: 'evt_1',
    seq: 4,
    runId: 'run_1',
    kind: 'heartbeat',
    ts: '2026-05-12T14:30:00.000Z',
    payload: { serverTs: '2026-05-12T14:30:00.000Z' },
  });

  it('accepts a well-formed envelope', () => {
    const envelope = toEnvelope({ data: valid });
    expect(envelope?.kind).toBe('heartbeat');
    expect(envelope?.seq).toBe(4);
  });

  it('drops an unknown kind instead of throwing', () => {
    // Forward compatibility: the service may ship a new frame kind before this
    // client knows it. Logging and dropping is right; crashing the trace pane
    // because the backend deployed first is not.
    const envelope = toEnvelope({
      data: JSON.stringify({ id: 'x', seq: 5, runId: 'r', kind: 'agent.thinking', ts: 'now', payload: {} }),
    });
    expect(envelope).toBeNull();
  });

  it('drops a frame with a non-numeric seq', () => {
    // `seq` carries gap detection and replay ordering. A frame without a usable
    // one cannot be placed, and guessing a position would silently corrupt the
    // record we are asking a human to sign against.
    const envelope = toEnvelope({
      data: JSON.stringify({ id: 'x', seq: 'four', runId: 'r', kind: 'heartbeat', ts: 'now', payload: {} }),
    });
    expect(envelope).toBeNull();
  });

  it('drops malformed JSON', () => {
    expect(toEnvelope({ data: '{not json' })).toBeNull();
  });
});
