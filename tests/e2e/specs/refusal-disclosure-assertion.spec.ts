/**
 * The disclosure assertion, tested in both directions against RENDERED output.
 *
 * WHY THIS FILE EXISTS. `banker-copilot-cloud.spec.ts` carries a SECURITY
 * assertion: a refusal must not disclose which customer records exist. It used
 * to be `expect(text).not.toMatch(/\d/)` — "a digit in a refusal is a count, and
 * a count is a disclosure" — and a cloud run failed it on the `30` in "The
 * planner model did not answer within 30s". A model timeout was reported as a
 * customer-data disclosure.
 *
 * A proxy assertion fails this way in both directions. Its red is uninformative,
 * so it gets ignored; and its green was luck, holding only because the other
 * refusals happened to be worded without digits. Danny named that anti-pattern
 * exactly: non-disclosure that holds because someone wrote careful strings is
 * not a control.
 *
 * The replacement is only trustworthy if it has been SEEN to fail for the right
 * reason. The cloud suite cannot demonstrate that — it needs a leak to exist on
 * a deployed host. So the check was extracted into `assertSubjectNonDisclosure`
 * and is exercised here against three real renders from the fake stack.
 *
 * Real `innerText`, never synthetic strings. The residue subtraction is about
 * the component's actual chrome — its headings, separators and punctuation — and
 * a version validated against hand-written text would be the next false positive.
 *
 * Run (one server process serves one mode):
 *   STREAM_MODE=leaky-refusal|suppressed-refusal|model-unavailable \
 *     python3 tests/e2e/support/fake_copilot_stack.py src/ui-app/build 8096 \
 *     src/ui-app/src/api/__tests__/bankerApprovalsWire.fixture.json
 *   npx playwright test --config disclosure.config.ts
 */
import { test, expect, Page } from '@playwright/test';
import {
  assertSubjectNonDisclosure,
  candidateNames,
} from '../cloud/cloudSession';
import {
  isNonDisclosing,
  refusalCopy,
} from '../../../src/ui-app/src/components/copilot/runOutcome';

const BASE = 'http://127.0.0.1:8096';
const MODE = process.env.STREAM_MODE || 'leaky-refusal';

async function boot(page: Page) {
  await page.route('**/runtime-config.js', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `window.__RUNTIME_CONFIG__ = { featureFlags: { copilotHarness: true, classicAdminTabs: true } };`,
    })
  );
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token');
    localStorage.setItem('auth_email', 'banker@banking-demo.com');
    localStorage.setItem('auth_role', 'banker');
  });
  await page.goto(`${BASE}/copilot`);
  await page.waitForSelector('[data-comparison-region="command"]', { timeout: 20000 });
}

/** The rendered refusal, read exactly as the cloud spec reads it. */
async function refusalText(page: Page): Promise<string> {
  const notice = page.getByRole('note', { name: /this run was refused/i });
  await expect(notice).toBeVisible({ timeout: 15000 });
  return notice.innerText();
}

function codeOf(text: string): string | undefined {
  return text.match(/·\s*([a-z_]+)\s*$/m)?.[1];
}

/** Runs the check the way the cloud spec runs it; returns the failure, if any. */
function check(text: string, code: string | undefined): Error | undefined {
  try {
    assertSubjectNonDisclosure(
      text,
      code,
      isNonDisclosing(code) ? refusalCopy(code) : undefined
    );
    return undefined;
  } catch (err) {
    return err as Error;
  }
}

test.describe('RED — a refusal that genuinely leaks a candidate', () => {
  test.skip(MODE !== 'leaky-refusal', 'requires the stack in leaky-refusal mode');

  /**
   * Not a contrived leak. `reasonCode` has no enum, so a model can return a code
   * OUTSIDE `NON_DISCLOSING` while putting candidate names and a match count in
   * its message — Danny's open gap, which `TracePane`'s suppression guard cannot
   * close because that guard is keyed on the code. `objective_unmappable` is
   * disclosing, so the message renders verbatim and the names reach the screen.
   */
  test('is caught, and the failure names the candidate that leaked', async ({ page }) => {
    await boot(page);
    const text = await refusalText(page);

    // Positive first: prove the leak really is on screen, so that a pass below
    // cannot come from a notice that never rendered the message.
    expect(text, 'the leak must actually be rendered for this test to mean anything').toContain(
      'Casey Mbeki'
    );
    expect(text).toContain('3 customers matched');

    const failure = check(text, codeOf(text));
    expect(failure, 'a rendered candidate name must fail the disclosure check').toBeDefined();
    expect(failure?.message).toContain('must not name');
  });

  test('catches the COUNT as a count, not as a digit', async ({ page }) => {
    await boot(page);
    const text = await refusalText(page);

    // Isolate the count rule from the name rule by removing every name first.
    // Otherwise this test would pass on the name loop and tell us nothing about
    // whether "3 customers matched" is still caught.
    let deNamed = text;
    for (const name of candidateNames()) {
      deNamed = deNamed.replace(new RegExp(name, 'gi'), 'REDACTED');
    }
    expect(deNamed).not.toContain('Casey');
    expect(deNamed).toContain('3 customers matched');

    const failure = check(deNamed, codeOf(text));
    expect(failure, 'a match count is a disclosure even with every name removed').toBeDefined();
    expect(failure?.message).toContain('count of matching records');
  });

  test('the residue subtraction catches server text on its own', async ({ page }) => {
    await boot(page);
    const text = await refusalText(page);

    // Exercise the STRONG form directly, by passing the client copy for this
    // code as though it were non-disclosing. This is how the check behaves the
    // day Danny's ruling extends `NON_DISCLOSING` to cover a code whose message
    // is currently rendered: everything the client authored subtracts away, and
    // the server's sentence is left standing as residue.
    const copy = refusalCopy(codeOf(text));

    // Strip the names and the count first, so this test can only pass on the
    // residue rule. Otherwise it would pass on the name loop — as it did on the
    // first run here, failing with "the refusal must not name Rita" because my
    // hand-written redaction list missed a first name that `candidateNames()`
    // knows about. Derive the list; do not retype it.
    let stripped = text;
    for (const name of candidateNames()) {
      stripped = stripped.replace(new RegExp(name, 'gi'), 'X');
    }
    stripped = stripped.replace(/\b3 customers\b/gi, 'some customers');

    let failure: Error | undefined;
    try {
      assertSubjectNonDisclosure(stripped, codeOf(text), copy);
    } catch (err) {
      failure = err as Error;
    }
    expect(
      failure,
      'server-authored text surviving the subtraction must fail, independently of names and counts'
    ).toBeDefined();
    expect(failure?.message).toContain('server-authored text reaching the screen');
  });
});

test.describe('GREEN — the same leaking message under a non-disclosing code', () => {
  test.skip(MODE !== 'suppressed-refusal', 'requires the stack in suppressed-refusal mode');

  /**
   * The server tried to leak; `TracePane:68` dropped the message. The check must
   * pass — and pass because nothing reached the screen, not because nobody tried.
   */
  test('passes, and passes because the guard suppressed it', async ({ page }) => {
    await boot(page);
    const text = await refusalText(page);

    expect(codeOf(text)).toBe('subject_not_found');
    expect(isNonDisclosing(codeOf(text))).toBe(true);
    expect(text, 'the guard must have dropped the leaking server message').not.toContain(
      'Casey Mbeki'
    );

    expect(check(text, codeOf(text))).toBeUndefined();
  });
});

test.describe('NOT A SECURITY FAILURE — the planner model was unreachable', () => {
  test.skip(MODE !== 'model-unavailable', 'requires the stack in model-unavailable mode');

  test('the "30s" that broke the old assertion no longer trips the disclosure check', async ({
    page,
  }) => {
    await boot(page);
    const text = await refusalText(page);

    expect(codeOf(text)).toBe('planner_model_unavailable');
    expect(text).toContain('within 30s');

    // The old proxy, run against this exact rendered text. It fails — which is
    // the false positive that started this. Asserting it here keeps the reason
    // for the change checkable rather than a claim in a comment.
    expect(/\d/.test(text), 'the old /\\d/ assertion would have failed on this text').toBe(true);

    // The new check does not, because there is no count and no candidate.
    expect(
      check(text, codeOf(text)),
      'an unreachable model endpoint must not render as a disclosure failure'
    ).toBeUndefined();
  });

  test('the cloud spec bails out on this code rather than asserting through it', async ({
    page,
  }) => {
    await boot(page);
    const text = await refusalText(page);

    // The cloud spec's bail-out is keyed on the code, and this is the code it is
    // keyed on. Asserting the exact string keeps the two from drifting: if Turk
    // renames it, this fails here rather than silently re-enabling a subject
    // assertion on a run that never resolved a subject.
    expect(codeOf(text)).toBe('planner_model_unavailable');
    expect(isNonDisclosing(codeOf(text))).toBe(false);
  });
});
