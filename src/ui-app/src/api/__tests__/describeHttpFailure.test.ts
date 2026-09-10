/**
 * The misleading-error defect.
 *
 * A banker submitted an intent and was told "The harness did not accept that
 * request. It is not running on the server." The harness WAS running — the same
 * call returned 201 from the CLI a minute later. The request had gone to a
 * misbuilt URL and nginx answered 405. One hardcoded sentence turned a routing
 * bug into a false statement about infrastructure and sent the team to inspect
 * pods and tokens for twenty minutes.
 *
 * These tests pin the rule that replaced it: report the status, quote the server
 * if it spoke, and never assert a cause the client cannot observe.
 */

import { describeHttpFailure, resolveApiError } from '../errors';

const httpError = (status: number, data?: unknown) => ({
  response: { status, data },
  config: { url: '/copilot/sessions' },
  message: `Request failed with status code ${status}`,
});

describe('describeHttpFailure', () => {
  it('never claims the server is down for a 405 — the exact bug', () => {
    const message = describeHttpFailure(httpError(405), 'The harness request');

    expect(message).not.toMatch(/not running on the server/i);
    expect(message).not.toMatch(/is down/i);
    expect(message).toContain('405');
    // Points at the URL, which is where the fault actually was.
    expect(message).toMatch(/endpoint URL/i);
  });

  it('treats 404 the same way — a routing fault, not an outage', () => {
    const message = describeHttpFailure(httpError(404), 'The harness request');
    expect(message).toContain('404');
    expect(message).toMatch(/did not reach the service/i);
    expect(message).not.toMatch(/not running/i);
  });

  it('names an auth failure as an auth failure and points at re-login', () => {
    expect(describeHttpFailure(httpError(401))).toMatch(/unauthorised \(401\)/i);
    expect(describeHttpFailure(httpError(401))).toMatch(/sign in again/i);
    expect(describeHttpFailure(httpError(403))).toContain('403');
  });

  it('quotes what the server actually said', () => {
    const message = describeHttpFailure(
      httpError(500, { detail: 'planner deployment unavailable' }),
      'The harness request'
    );
    expect(message).toContain('500');
    expect(message).toContain('planner deployment unavailable');
  });

  it('distinguishes "no response" from "the server refused"', () => {
    const message = describeHttpFailure({ message: 'Network Error' }, 'The harness request');
    expect(message).toMatch(/no response was received/i);
    expect(message).toContain('Network Error');
    // It must not invent a status it never saw.
    expect(message).not.toMatch(/HTTP \d/);
  });

  it('still reports a plain 4xx with its status', () => {
    expect(describeHttpFailure(httpError(400, { message: 'bad objective' }))).toContain('400');
    expect(describeHttpFailure(httpError(400, { message: 'bad objective' }))).toContain(
      'bad objective'
    );
  });

  it('leaves the existing resolveApiError behaviour intact', () => {
    // FastAPI 422 array shape — must still coerce to a string, not an object.
    const message = resolveApiError({
      response: { data: { detail: [{ loc: ['body', 'objective'], msg: 'field required' }] } },
    });
    expect(message).toBe('objective: field required');
  });
});
