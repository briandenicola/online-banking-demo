/**
 * The reported defect, end to end: does the Task queue populate?
 *
 * This is the test that speaks to the symptom Brian actually saw — NEEDS YOU 0 /
 * WAITING 0 / RUNNING 0 / DONE TODAY 0 against an API returning ten items. It
 * mounts the real surface with the real provider (NOT `offline`, so
 * `refreshApprovals` genuinely runs), stubs only the HTTP layer, and feeds back
 * the actual `banker` payload.
 *
 * It settles the open question from the brief. The footer's "0 of 10" is a
 * hardcoded session cap, so the queue could have been receiving nothing — and it
 * was. The fault was in the FETCH, not the bucketing: `apiClient` carries
 * `baseURL: '/api'` and the path builder emitted the absolute `/api/authority/...`,
 * so the request went to `/api/api/authority/approvals`, which the SPA history
 * fallback answers with index.html and status 200.
 *
 * The stub below is URL-aware on purpose. It answers ONLY the correctly-prefixed
 * path with data and mimics the SPA fallback for anything else, so if the double
 * prefix ever returns, this test reproduces the exact empty queue rather than
 * passing on a convenient mock.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import CopilotHarness from '../CopilotHarness';
import { CopilotProvider } from '../CopilotContext';
import { FeatureFlagProvider } from '../../../contexts/FeatureFlagContext';
import TaskMeasurementBar from '../../comparison/TaskMeasurementBar';
import apiClient from '../../../api/client';
import fixture from '../../../api/__tests__/bankerApprovalsWire.fixture.json';

const SPA_FALLBACK = '<!doctype html><html><body><div id="root"></div></body></html>';

function stubHttp() {
  return jest.spyOn(apiClient, 'get').mockImplementation((url: string, config?: unknown) => {
    // What the browser really asks for, baseURL included.
    const resolved = apiClient.getUri({ url });

    if (resolved === '/api/authority/approvals') {
      const scope = (config as { params?: { scope?: string } } | undefined)?.params?.scope;
      // The server excludes the caller's own requests from `awaiting-me`, and
      // every seeded item was requested by `banker`.
      const items = scope === 'awaiting-me' ? [] : fixture.items;
      return Promise.resolve({ data: { count: items.length, items } });
    }

    // Anything else — including a doubled `/api/api/...` — gets what a static
    // host gives an unmatched path: index.html, with status 200.
    return Promise.resolve({ data: SPA_FALLBACK });
  });
}

function renderPage() {
  return render(
    <FeatureFlagProvider>
      <TaskMeasurementBar surface="copilot">
        <CopilotProvider>
          <CopilotHarness />
        </CopilotProvider>
      </TaskMeasurementBar>
    </FeatureFlagProvider>
  );
}

describe('Task queue against the live banker payload', () => {
  let get: jest.SpyInstance;

  beforeEach(() => {
    get = stubHttp();
  });
  afterEach(() => jest.restoreAllMocks());

  it('requests the single-prefixed authority path', async () => {
    renderPage();
    await waitFor(() => expect(get).toHaveBeenCalled());
    const urls = get.mock.calls.map((c) => apiClient.getUri({ url: c[0] as string }));
    expect(urls).toContain('/api/authority/approvals');
    expect(urls.some((u: string) => u.includes('/api/api/'))).toBe(false);
  });

  it('shows 7 in "Needs you" — not the reported 0', async () => {
    renderPage();

    const queue = screen.getByRole('region', { name: /task queue/i });
    const needsYou = await within(queue).findByRole('button', { name: /needs you/i });

    await waitFor(() => expect(within(needsYou).getByText('7')).toBeInTheDocument());
  });

  it('fills the other three buckets rather than leaving them all at zero', async () => {
    renderPage();
    const queue = screen.getByRole('region', { name: /task queue/i });

    // Synchronous getters inside `waitFor`. The earlier version awaited a
    // `findByRole` INSIDE the waitFor callback, so every poll spent up to a
    // second of its own retry budget before the outer poll could retry — the
    // suite passed alone and timed out under parallel load. A waitFor callback
    // must be cheap and synchronous; only the outer wait should retry.
    const badge = (name: RegExp) =>
      within(within(queue).getByRole('button', { name }));

    await waitFor(() => expect(badge(/needs you/i).getByText('7')).toBeInTheDocument());
    expect(badge(/waiting on a co-signer/i).getByText('1')).toBeInTheDocument();
    expect(badge(/running/i).getByText('1')).toBeInTheDocument();
    expect(badge(/done today/i).getByText('1')).toBeInTheDocument();
  });

  it('shapes the queue to 5 visible with the rest behind "Show 2 more"', async () => {
    renderPage();
    const queue = screen.getByRole('region', { name: /task queue/i });
    // Queue shaping caps the visible cards; the other two are not lost.
    expect(await within(queue).findByText(/show 2 more/i)).toBeInTheDocument();
  });

  it('renders an empty queue when the SPA fallback answers — the original bug', async () => {
    // Reproduces the defect exactly: every path returns index.html with 200.
    get.mockImplementation(() => Promise.resolve({ data: SPA_FALLBACK }));

    renderPage();
    const queue = screen.getByRole('region', { name: /task queue/i });
    const needsYou = await within(queue).findByRole('button', { name: /needs you/i });

    await waitFor(() => expect(within(needsYou).getByText('0')).toBeInTheDocument());
    expect(within(queue).getAllByText(/nothing here/i).length).toBeGreaterThan(0);
  });
});

/**
 * The centre-pane routing rule, guarded where CI can actually see it.
 *
 * The Playwright layout spec is deliberately excluded from the shared e2e config
 * (it needs a local static build on :8099, not the deployed BASE_URL), so nothing
 * in CI would otherwise notice if this rule regressed. The rule is LOGIC, not
 * pixels, so it belongs here too.
 *
 * The rule: a run owns the centre pane whenever one exists; otherwise the centre
 * shows the selected approval, and the artifact pane — which exists to show what
 * a run produced — is not mounted at all.
 */
describe('the centre pane routes on whether a run exists', () => {
  beforeEach(() => {
    stubHttp();
  });
  afterEach(() => jest.restoreAllMocks());

  it('gives the centre to the selected approval when no run is active', async () => {
    renderPage();

    // The harness auto-selects the most urgent signable item, so a detail pane
    // must appear without the test clicking anything.
    expect(await screen.findByTestId('approval-detail-pane')).toBeInTheDocument();
  });

  it('does not mount the artifact pane when there is nothing for it to show', async () => {
    renderPage();
    await screen.findByTestId('approval-detail-pane');

    expect(screen.queryByRole('region', { name: /artifacts and approvals/i })).toBeNull();
  });

  it('keeps the approval whole in the centre — rung and signature slots included', async () => {
    renderPage();
    const detail = await screen.findByTestId('approval-detail-pane');

    // §7.1 leans on the rung being visible; dual control is illegible without
    // the signature slots. The move must not have dropped either.
    expect(within(detail).getByText(/SIGNATURE REQUIRED/i)).toBeInTheDocument();
    expect(within(detail).getAllByText(/signer/i).length).toBeGreaterThan(0);
    // More than one legitimately matches — the rung chip and the "WHY THIS IS
    // L2" explainer — so assert presence, not uniqueness.
    expect(within(detail).getAllByText(/L2|L1/).length).toBeGreaterThan(0);
  });
});
