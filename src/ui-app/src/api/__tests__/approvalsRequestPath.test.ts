/**
 * The empty-task-queue regression.
 *
 * `apiClient` carries `baseURL: '/api'`. `authorityUrl()` returns the ABSOLUTE
 * app path `/api/authority/approvals`. Handing the second to the first made
 * axios request `/api/api/authority/approvals`, which the SPA history fallback
 * answers with `index.html` and status **200** — so nothing threw, nothing
 * logged, `data.items` was simply absent, and the banker's queue rendered
 * "Nothing here." over ten live approvals.
 *
 * These tests pin the RESOLVED path, because the bug was never in the bucketing
 * logic — it was in the URL, and only a test that resolves the URL the way axios
 * resolves it can see the difference.
 */

import apiClient, { apiPath, API_BASE_PATH } from '../client';
import { listApprovals, getApproval, signApproval, denyApproval } from '../approvals';
import { createSession, startRun, sendMessage, fetchRunTrace } from '../copilot';
import { resetCopilotConfig } from '../../config/copilotConfig';

/** The path axios will actually put on the wire, baseURL included. */
function resolved(url: string): string {
  return apiClient.getUri({ url });
}

describe('apiPath', () => {
  it('subtracts the client baseURL from an absolute app path', () => {
    expect(apiPath('/api/authority/approvals')).toBe('/authority/approvals');
    expect(apiPath('/api/copilot/sessions')).toBe('/copilot/sessions');
  });

  it('leaves absolute URLs alone', () => {
    expect(apiPath('https://example.test/api/authority/approvals')).toBe(
      'https://example.test/api/authority/approvals'
    );
  });

  it('round-trips back to the original absolute path through axios', () => {
    expect(resolved(apiPath('/api/authority/approvals'))).toBe('/api/authority/approvals');
  });

  it('is loud rather than silent when the prefix is missing', () => {
    const spy = jest.spyOn(require('../../utils/logger').logger, 'error').mockImplementation(() => {});
    expect(apiPath('/authority/approvals')).toBe('/authority/approvals');
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it('agrees with the client baseURL constant', () => {
    expect(API_BASE_PATH).toBe('/api');
  });
});

describe('authority + copilot requests resolve to single-prefixed paths', () => {
  let get: jest.SpyInstance;
  let post: jest.SpyInstance;

  beforeEach(() => {
    resetCopilotConfig();
    get = jest.spyOn(apiClient, 'get').mockResolvedValue({ data: { count: 0, items: [] } });
    post = jest.spyOn(apiClient, 'post').mockResolvedValue({ data: {} });
  });

  afterEach(() => {
    jest.restoreAllMocks();
    resetCopilotConfig();
  });

  it('listApprovals hits /api/authority/approvals exactly once-prefixed', async () => {
    await listApprovals({ scope: 'mine' });
    const url = get.mock.calls[0][0] as string;
    expect(resolved(url)).toBe('/api/authority/approvals');
    expect(resolved(url)).not.toContain('/api/api/');
  });

  it('getApproval, sign and deny are single-prefixed', async () => {
    await getApproval('apr_1');
    expect(resolved(get.mock.calls[0][0] as string)).toBe('/api/authority/approvals/apr_1');

    await signApproval('apr_1', { expectedPayloadHash: 'sha256:abc' });
    expect(resolved(post.mock.calls[0][0] as string)).toBe('/api/authority/approvals/apr_1/sign');

    await denyApproval('apr_1', 'no');
    expect(resolved(post.mock.calls[1][0] as string)).toBe('/api/authority/approvals/apr_1/deny');
  });

  it('the copilot session and run calls are single-prefixed too', async () => {
    await createSession({ objective: 'x' });
    expect(resolved(post.mock.calls[0][0] as string)).toBe('/api/copilot/sessions');

    await startRun('sess_1', {});
    expect(resolved(post.mock.calls[1][0] as string)).toBe('/api/copilot/sessions/sess_1/runs');

    await sendMessage('sess_1', 'hi');
    expect(resolved(post.mock.calls[2][0] as string)).toBe('/api/copilot/sessions/sess_1/messages');

    await fetchRunTrace('run_1');
    expect(resolved(get.mock.calls[0][0] as string)).toBe('/api/copilot/runs/run_1/trace');
  });
});

describe('listApprovals on a non-list 200', () => {
  afterEach(() => jest.restoreAllMocks());

  it('reports rather than returning a quiet empty queue', async () => {
    // This is the SPA fallback: status 200, body is index.html.
    jest.spyOn(apiClient, 'get').mockResolvedValue({ data: '<!doctype html><html></html>' });
    const spy = jest
      .spyOn(require('../../utils/logger').logger, 'error')
      .mockImplementation(() => {});

    const result = await listApprovals({ scope: 'mine' });

    expect(result).toEqual([]);
    expect(spy).toHaveBeenCalledWith(expect.stringContaining('not an empty'));
  });
});
