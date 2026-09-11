/**
 * Session plumbing for the deployed-surface suite.
 *
 * Everything in here was established by probing the live host on 2026-09-10,
 * not by reading the design docs. Where the two disagreed, the host won and the
 * disagreement is written down beside the code.
 */
import { APIRequestContext, Page, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const GATE = 'BANKER_COPILOT_CLOUD_E2E';

/**
 * The gate again, at spec-module scope.
 *
 * `cloud.config.ts` already throws, but a spec can be pointed at by a different
 * config (an IDE runner, a `--testDir` override, a future widening of
 * `playwright.config.ts`'s glob). The rule Brian set is that an ungated
 * collection must be LOUD, and a second throw costs nothing.
 */
export function assertGated(): void {
  if (process.env[GATE] !== '1') {
    throw new Error(
      `${GATE} is not set to "1". The deployed-surface suite refuses to run ` +
        'unattended; it is not allowed to degrade into a silent skip.'
    );
  }
}

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const DATASET_PATH = path.join(REPO_ROOT, 'config', 'demo-dataset.json');

interface DemoDataset {
  credentials: { passwordEnv: string; passwordDefault: string };
  identities: { username: string; firstName: string; lastName: string; retail?: boolean }[];
}

export const dataset: DemoDataset = JSON.parse(fs.readFileSync(DATASET_PATH, 'utf8'));

export function demoPassword(): string {
  return process.env[dataset.credentials.passwordEnv] || dataset.credentials.passwordDefault;
}

/**
 * Every CUSTOMER name a refusal must never utter.
 *
 * Usernames AND the human names behind them: "Casey Mbeki" discloses exactly
 * what "casey" discloses. Built from the dataset rather than hardcoded, so
 * adding a customer extends the assertion automatically.
 *
 * FINDING, learned by running it: the first version of this used every identity
 * in the dataset and failed on the live refusal for `subject_not_found`, whose
 * copy reads "Nothing matched the reference for this banker". That is not a
 * disclosure — `banker` there is the READER's own role, addressed to them, and
 * `banker`/`supervisor`/`admin` are staff logins, not customers. The constraint
 * Danny ruled on is about which CUSTOMER RECORDS exist, so the list is scoped to
 * the retail identities. A staff username that also happened to be a customer
 * would slip through this, and that is the known, deliberate edge.
 */
export function candidateNames(): string[] {
  const names: string[] = [];
  for (const identity of dataset.identities) {
    if (identity.retail !== true) continue;
    names.push(identity.username, identity.firstName, identity.lastName);
  }
  return names.filter((n) => typeof n === 'string' && n.length > 2);
}

/** `POST /api/auth/login`. Returns the bearer token; never log it. */
export async function login(request: APIRequestContext, username: string): Promise<string> {
  const response = await request.post('/api/auth/login', {
    data: { username, password: demoPassword() },
  });
  expect(response.status(), `login as ${username}`).toBe(200);
  const body = (await response.json()) as { token?: string };
  const token = body.token;
  if (!token) throw new Error(`login as ${username} returned no token`);
  return token;
}

export interface CloudApproval {
  id: string;
  status: string;
  actionId: string;
  actionLabel: string;
  requiredRung: string;
  requiredSigners: number;
  baseRung: string;
  payload: Record<string, unknown>;
  payloadHashShort: string;
  createdAt: string;
}

/**
 * The approvals list.
 *
 * FINDING: the brief said `/api/approvals?scope=all`. That path answers 200 and
 * serves the SPA's `index.html` through the history fallback — a "successful"
 * response that is not JSON at all. Authority is behind
 * `/api/authority/approvals`, which is what `src/ui-app/src/api/approvals.ts`
 * actually builds. `?scope=all` is kept: without it the list is actor-scoped.
 */
export async function listApprovals(
  request: APIRequestContext,
  token: string
): Promise<CloudApproval[]> {
  const response = await request.get('/api/authority/approvals?scope=all', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.status(), 'GET /api/authority/approvals?scope=all').toBe(200);
  const body = (await response.json()) as { items?: CloudApproval[] };
  if (!Array.isArray(body.items)) {
    throw new Error(
      'approvals response carried no `items` array. This is not an empty queue; ' +
        'it is a shape this suite does not understand, and treating it as empty ' +
        'would make every delta assertion below pass vacuously.'
    );
  }
  return body.items;
}

export async function approvalIds(
  request: APIRequestContext,
  token: string
): Promise<Set<string>> {
  return new Set((await listApprovals(request, token)).map((a) => a.id));
}

/**
 * Opens the copilot harness as `username`.
 *
 * The token is seeded into `localStorage` rather than typed into the login form:
 * the form is not what is under test, and `/copilot` is guarded by `isBanker`,
 * which reads `effectiveRoles` out of the JWT — so it has to be a real token
 * either way. Confirmed live: the `banker` token carries
 * `effectiveRoles: "banker"`.
 *
 * `?ff=bankerCopilot` is required. `bankerCopilot` gates the whole surface and
 * the deployed `runtime-config.js` does not turn it on.
 */
export async function openCopilot(page: Page, token: string, username: string): Promise<void> {
  await page.addInitScript(
    ([t, u]) => {
      localStorage.setItem('auth_token', t);
      localStorage.setItem('auth_email', `${u}@banking-demo.com`);
      localStorage.setItem('auth_role', 'banker');
    },
    [token, username]
  );
  await page.goto('/copilot?ff=bankerCopilot', { waitUntil: 'domcontentloaded' });
  await expect(
    page.getByRole('textbox', { name: 'Describe the task' }),
    'the command bar — if this is missing, the flag or the role did not take'
  ).toBeVisible({ timeout: 45000 });
}

export async function submitObjective(page: Page, objective: string): Promise<void> {
  await page.getByRole('textbox', { name: 'Describe the task' }).fill(objective);
  await page.getByRole('button', { name: /^Start$/ }).click();
}

export const refusalNotice = (page: Page) =>
  page.getByRole('note', { name: /this run was refused/i });

export const artifactCanvas = (page: Page) =>
  page.getByRole('region', { name: 'Artifacts and approvals' });

export const tracePane = (page: Page) => page.getByRole('region', { name: 'Plan and trace' });

export const approvalDock = (page: Page) => page.locator('[data-testid="approval-dock"]');

export const NOTHING_TO_SIGN =
  'This was a read-only question. Nothing was proposed and there is nothing to sign.';

/**
 * Waits for the read-only answer, and names the alternative when it does not come.
 *
 * The bare `toBeVisible` this replaces reported only "element(s) not found"
 * after four minutes, which is exactly the failure mode that has cost us the
 * most time tonight: a red test that does not say what the system did instead.
 * A refusal is still a failure here — it now arrives carrying its own code.
 */
export async function waitForAnswer(page: Page, timeoutMs: number): Promise<void> {
  const caption = artifactCanvas(page).getByText(NOTHING_TO_SIGN);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await caption.count()) return;
    if (await refusalNotice(page).count()) {
      throw new Error(
        `the read-only run REFUSED instead of answering:\n${await refusalNotice(page).innerText()}`
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error(
    `no answer and no refusal after ${Math.round(timeoutMs / 1000)}s. Trace pane said:\n` +
      `${(await tracePane(page).innerText()).slice(0, 1200)}`
  );
}

/**
 * Waits until the run has produced an approval of its OWN.
 *
 * Polls authority rather than the DOM. The queue pane is a view of the whole
 * tenant — 25 open approvals on the live host at the time of writing — so "an
 * approval is on screen" says nothing whatever about what this run did. The
 * delta against a pre-run snapshot does.
 *
 * It also watches the page for a refusal, because a bare "expected 1, received
 * 0" after four minutes is a useless failure: the first time this test failed
 * that way it took another full run to find out the planner had refused. A
 * refusal here is still a failure — it just now says what it was.
 */
export async function waitForNewApprovals(
  request: APIRequestContext,
  token: string,
  before: Set<string>,
  timeoutMs: number,
  page?: Page
): Promise<CloudApproval[]> {
  const deadline = Date.now() + timeoutMs;
  let latest: CloudApproval[] = [];
  // 5s, not 3s. The approvals list is 111KB on the live tenant; a tighter poll
  // pulled ~9MB through the gateway across one four-minute wait and ended in a
  // `read ECONNRESET` mid-body. Polling is not the thing under test and it
  // should not be the thing that fails.
  while (Date.now() < deadline) {
    latest = (await listApprovals(request, token)).filter((a) => !before.has(a.id));
    if (latest.length > 0) return latest;
    if (page && (await refusalNotice(page).count())) {
      throw new Error(
        `the run refused instead of proposing:\n${await refusalNotice(page).innerText()}`
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 5000));
  }
  if (page) {
    throw new Error(
      `no approval after ${Math.round(timeoutMs / 1000)}s and no refusal either. Trace pane said:\n` +
        `${(await tracePane(page).innerText()).slice(0, 1200)}`
    );
  }
  return latest;
}

/**
 * Docks an approval identified by its payload hash.
 *
 * FINDING, and the reason this is not a one-line click: nothing links a run to
 * its approval in the UI. The harness auto-selects the first pending signable
 * approval on mount and then deliberately never re-points the dock
 * (`CopilotHarness`: re-pointing under someone mid-read is its own hazard), so
 * after a successful propose the dock is STILL showing whatever unrelated
 * approval was docked at page load. Queue rows carry no id attribute, and in a
 * tenant full of `Post a balance adjustment` rows their text does not identify
 * them either.
 *
 * So: expand the queue, click rows, and confirm the card that docks is the one
 * we mean, by its payload-hash chip — which is unique and is the same value the
 * signature binds to. If no row yields it, that is a loud failure, never a
 * fallback to "well, some approval was shown".
 */
export async function selectApprovalByHash(page: Page, hashShort: string): Promise<void> {
  const showMore = page.getByRole('button', { name: /^Show \d+ more$/ });
  if (await showMore.count()) await showMore.first().click();

  const chip = approvalDock(page).getByText(`payload ${hashShort}`);
  if (await chip.count()) return;

  const rows = page.locator('[data-comparison-region="queue"] button[aria-current]');
  const count = await rows.count();
  for (let i = 0; i < count; i += 1) {
    await rows.nth(i).click();
    if (await chip.count()) return;
  }
  throw new Error(
    `no queue row docked the approval with payload hash "${hashShort}" after trying ` +
      `${count} row(s). Authority holds the approval; the queue pane did not surface it.`
  );
}

/**
 * The subject non-disclosure check, as a pure function over the rendered text.
 *
 * Extracted from the spec so BOTH directions can be proven without a live
 * deployment: that it catches a refusal genuinely carrying a candidate name, and
 * that it does not fire on an infrastructure message that merely contains a
 * number. An assertion that has only ever been seen to pass is not a control.
 *
 * WHAT THIS REPLACED, and why. The check used to be
 * `expect(text).not.toMatch(/\d/)` with the note "a digit in a refusal is a
 * count, and a count is a disclosure". It failed a cloud run on the `30` in "The
 * planner model did not answer within 30s" — a model timeout reported as a
 * customer-data disclosure. Being a proxy, it could not tell a match count from
 * a timeout, an amount or a date, so its red was uninformative; and it passed
 * only because the other refusals happened to be worded without digits, so its
 * green was luck. That is the anti-pattern Danny named: non-disclosure holding
 * because someone wrote careful strings is not a control.
 *
 * Throws on violation, in the voice of the assertion that failed.
 */
export function assertSubjectNonDisclosure(
  text: string,
  code: string | undefined,
  clientCopy: { title: string; what: string; next: string } | undefined
): void {
  // 1. No candidate identifier, whatever the code. This is the property the
  //    ruling is actually about and it holds for every refusal.
  const names = candidateNames();
  expect(
    names.length,
    'an empty candidate list would make the loop below pass without checking anything'
  ).toBeGreaterThan(4);
  for (const name of names) {
    expect(text.toLowerCase(), `the refusal must not name ${name}`).not.toContain(
      name.toLowerCase()
    );
  }

  // 2. No count of matching records. A count discloses without naming anything:
  //    "3 customers matched" answers "does a customer like this exist?". Matched
  //    as the PROPERTY — a number quantifying records — not as "has a digit".
  expect(text, 'a count of matching records is a disclosure even without a name').not.toMatch(
    /\b\d+\s+(customer|user|account|record|match|result|candidate)s?\b/i
  );

  // 3. For the codes the ruling covers, the strong form. `TracePane` drops the
  //    server's message entirely for these, so the notice should contain nothing
  //    but copy this repo authored. Subtract ours; any residue is server text
  //    that reached the screen, which is the only channel candidate detail could
  //    travel on. Exact, and independent of anyone's wording.
  if (!clientCopy) return;
  const ours = [
    'Refused —',
    clientCopy.title,
    clientCopy.what,
    clientCopy.next,
    'Nothing was signed and nothing was executed',
    'No tools were called.',
    code || '',
  ].filter(Boolean);
  let residue = text;
  for (const part of ours) residue = residue.split(part).join(' ');
  residue = residue.replace(/[·.\s]+/g, ' ').trim();
  expect(
    residue,
    'a non-disclosing refusal must render only the client\u2019s own copy; anything else is ' +
      'server-authored text reaching the screen, which is the channel a candidate name would ' +
      'travel on'
  ).toBe('');
}
