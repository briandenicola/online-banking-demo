/**
 * The reported defect: every card in the queue rendered Deny-only.
 *
 * `canSignUnderStream` accepts only `live`/`resumed`, `stream.status` starts at
 * `idle`, and `openStream` had exactly ONE call site — inside `submitIntent`.
 * So a banker who loaded `/copilot` to work the queue and never dispatched an
 * agent run sat at `idle` forever and could not sign anything, by construction.
 * Confirmed in a real browser before the fix: zero requests to `/stream` on a
 * cold load, against a stream endpoint that was verified healthy.
 *
 * These tests pin the two directions that matter, and they are deliberately
 * asymmetric:
 *
 *   1. A cold load with NO run dispatched must still ask for a stream. That is
 *      the regression.
 *   2. When the stream cannot be established, the gate must STAY SHUT. The fix
 *      is to restore the client's ability to verify payload freshness, never to
 *      make the button light up. A test that only asserted (1) would pass just
 *      as happily against a bypassed gate.
 */

import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { CopilotProvider } from '../CopilotContext';
import { canSignUnderStream, streamGateReason } from '../types';
import { createSession } from '../../../api/copilot';
import { openCopilotStream } from '../../../api/copilotStream';

jest.mock('../../../api/copilot', () => ({
  createSession: jest.fn(),
  sendMessage: jest.fn(),
  startRun: jest.fn(),
  fetchRunTrace: jest.fn(),
}));

jest.mock('../../../api/copilotStream', () => ({
  openCopilotStream: jest.fn(() => ({ close: jest.fn() })),
}));

const mockCreateSession = createSession as jest.MockedFunction<typeof createSession>;
const mockOpenStream = openCopilotStream as jest.MockedFunction<typeof openCopilotStream>;

// The provider alone is enough: the bootstrap lives in CopilotContext, and
// mounting the whole harness would drag in the approvals fetch for no gain.
function mountProvider() {
  return render(
    <CopilotProvider>
      <div>queue surface</div>
    </CopilotProvider>
  );
}

describe('the signing gate on a cold load', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('opens a stream on mount, without any run being dispatched', async () => {
    mockCreateSession.mockResolvedValue({ sessionId: 'sess_cold_1' } as never);

    mountProvider();

    await waitFor(() => expect(mockOpenStream).toHaveBeenCalledTimes(1));

    // The stream must be opened against the session we just created, not a
    // placeholder — `/sessions/undefined/stream` retries forever on a backoff
    // and is indistinguishable from a server fault.
    expect(mockOpenStream.mock.calls[0][0].sessionId).toBe('sess_cold_1');
    expect(mockCreateSession).toHaveBeenCalledTimes(1);
  });

  it('leaves the gate shut when the session cannot be created', async () => {
    mockCreateSession.mockRejectedValue({ response: { status: 503 } });

    mountProvider();

    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());
    // No session means no stream, which means no signature. Failing closed is
    // the point.
    expect(mockOpenStream).not.toHaveBeenCalled();
  });

  it('opens the stream only once across re-renders', async () => {
    mockCreateSession.mockResolvedValue({ sessionId: 'sess_cold_2' } as never);

    const { rerender } = mountProvider();
    await waitFor(() => expect(mockOpenStream).toHaveBeenCalledTimes(1));

    rerender(
      <CopilotProvider>
        <div>queue surface again</div>
      </CopilotProvider>
    );

    // A session per render would be a quiet resource leak on a page the banker
    // leaves open all day.
    expect(mockCreateSession).toHaveBeenCalledTimes(1);
  });
});

describe('under StrictMode, as the app actually mounts', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('still opens a stream despite the dev double-invoke', async () => {
    // index.tsx wraps the app in React.StrictMode, which mounts, unmounts and
    // remounts every effect in development. A naive "run once" ref survives that
    // unmount, so the remount skips the bootstrap and no stream is ever opened —
    // the exact defect, reintroduced by its own guard, in dev only.
    mockCreateSession.mockResolvedValue({ sessionId: 'sess_strict' } as never);

    render(
      <React.StrictMode>
        <CopilotProvider>
          <div>queue surface</div>
        </CopilotProvider>
      </React.StrictMode>
    );

    await waitFor(() => expect(mockOpenStream).toHaveBeenCalled());
    expect(mockOpenStream.mock.calls[0][0].sessionId).toBe('sess_strict');
  });
});

describe('the gate itself is unchanged', () => {
  it('still refuses every status except live and resumed', () => {
    expect(canSignUnderStream('live')).toBe(true);
    expect(canSignUnderStream('resumed')).toBe(true);
    (['idle', 'connecting', 'reconnecting', 'degraded', 'failed'] as const).forEach((s) => {
      expect(canSignUnderStream(s)).toBe(false);
    });
  });

  it('explains a never-established stream differently from a dropped one', () => {
    // The old copy said "Reconnecting" while idle, which is a lie: nothing had
    // ever connected. Brian read it as a server outage and we lost 20 minutes.
    const idle = streamGateReason('idle');
    expect(idle).not.toMatch(/reconnect/i);
    expect(streamGateReason('reconnecting')).toMatch(/reconnect/i);
  });
});
