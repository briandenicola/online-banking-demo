/**
 * The three free-text run outcomes, against the DEPLOYED system.
 *
 * Why this file exists: five e2e configs already drive the fake stack on
 * localhost, they are good, and they have caught real defects — and not one of
 * them could have caught the thing that actually bit us, which is that the first
 * prompt of Brian's demo script behaved differently in the cloud than it did
 * offline while 440 offline tests sat green. Nothing had been proven until Brian
 * opened a browser himself. This suite is the attempt to stop that.
 *
 * Run (the gate is mandatory and throws when unset):
 *   BANKER_COPILOT_CLOUD_E2E=1 npx playwright test --config cloud.config.ts
 *
 * RULES THIS FILE HOLDS TO
 *
 *  - Assert INVARIANTS, never model prose. A live model writes a different
 *    paragraph every run. Structure, roles, refusal codes, rungs, signer counts
 *    and the presence or absence of a proposal are stable; sentences are not.
 *  - Assert something POSITIVE about the rendered surface before asserting any
 *    absence. An absence assertion passes trivially when the container that
 *    would hold the thing never rendered — that is how an earlier terminal-state
 *    test of mine went green while checking nothing.
 *  - No `try/catch`, no defensive waits, no retries. If the cloud behaves
 *    differently from the design, that is the finding, and burying it under a
 *    wait is how we got here.
 *  - Single subject only. There is an unfixed defect where a stale subject's
 *    identifiers can travel into another customer's approval, so a two-customer
 *    prompt is not run from here at any cost.
 */
import { test, expect } from '@playwright/test';
import {
  approvalDock,
  approvalIds,
  artifactCanvas,
  assertGated,
  candidateNames,
  listApprovals,
  login,
  openCopilot,
  refusalNotice,
  selectApprovalByHash,
  submitObjective,
  tracePane,
  waitForAnswer,
  waitForNewApprovals,
  NOTHING_TO_SIGN,
} from './cloudSession';

assertGated();

/** A live planner run. 2.5s for a refusal, ~70s for a full propose path. */
const RUN_TIMEOUT = 240_000;

test.describe('banker copilot, deployed', () => {
  test('a read-only objective answers in prose and proposes nothing', async ({ page, request }) => {
    const token = await login(request, 'banker');
    const before = await approvalIds(request, token);
    await openCopilot(page, token, 'banker');

    // Brian's demo script opens on this exact sentence.
    await submitObjective(page, "Summarise casey's accounts and recent activity");

    const canvas = artifactCanvas(page);

    // POSITIVE FIRST, and diagnosed. `waitForAnswer` fails with the refusal's
    // own code if the run refuses, rather than reporting the vacuous success of
    // an absent approval dock four minutes later.
    await waitForAnswer(page, RUN_TIMEOUT);
    await expect(
      canvas.getByText(NOTHING_TO_SIGN),
      'the read-only run must say out loud that there is nothing to sign'
    ).toBeVisible();

    // An answer TAB, not a paragraph that scrolls away. Server-authored title,
    // rendered verbatim by design.
    const answerTab = page.getByRole('tab', { name: /Copilot answer/i });
    await expect(answerTab).toBeVisible();
    await answerTab.click();

    await expect(
      canvas.getByText('Cited evidence', { exact: true }),
      'an answer that cites nothing is the empty evidence bundle in better clothes'
    ).toBeVisible();

    // FINDING: the approval dock is a child of the "Artifacts and approvals"
    // region, so `canvas.innerText()` carries the docked (unrelated) approval's
    // copy as well as the answer. The first version of this test asserted on the
    // whole region and hit a strict-mode violation on `Cited evidence`, which
    // also matched a sentence inside the docked card — meaning the length and
    // JSON assertions below would have been satisfied by the CARD, not by the
    // answer. Subtract the dock so they are about the artifact body alone.
    const dock = approvalDock(page);
    const canvasText = await canvas.innerText();
    const dockText = (await dock.count()) ? await dock.innerText() : '';
    const prose = dockText ? canvasText.replace(dockText, '') : canvasText;

    // Prose, not a stub. Length, not wording: the model writes a different
    // paragraph every run and this suite never asserts its sentences.
    expect(prose.length, 'the answer body is substantive prose').toBeGreaterThan(200);

    // The JSON fallback branch in `ArtifactBody` stringifies unknown object
    // content. If the answer ever falls back to it, these field names appear on
    // the surface the banker is meant to read.
    expect(prose).not.toContain('"citedEvidenceIds"');
    expect(prose).not.toContain('"keyPoints"');

    await expect(
      refusalNotice(page),
      'a read-only question about a known customer must not refuse'
    ).toHaveCount(0);

    // THE REAL "no approval dock" ASSERTION.
    //
    // FINDING: the dock cannot be asserted absent on the deployed surface. It is
    // fed by the queue, not by the run — the harness auto-selects the first
    // pending signable approval on mount, and the live tenant always has some.
    // A literal `toHaveCount(0)` here would be a test that can only fail, and
    // faking an empty queue would be testing the fake. What the requirement
    // actually means is that THIS RUN proposed nothing, and authority is the
    // only place that can answer that.
    const created = (await listApprovals(request, token)).filter((a) => !before.has(a.id));
    expect(created.map((a) => a.id), 'a read-only run must create no approval').toEqual([]);

    await expect(
      tracePane(page).getByText(/Propose /i),
      'no proposal step belongs in a read-only plan'
    ).toHaveCount(0);
  });

  test('a credit objective proposes an L2 approval that needs a signature', async ({
    page,
    request,
  }) => {
    const token = await login(request, 'banker');
    const before = await approvalIds(request, token);
    await openCopilot(page, token, 'banker');

    // From Brian's L2 list. A credit — crediting an account creates money, which
    // `credit-adjustment` always raises to dual control. Single subject.
    await submitObjective(page, "Refund a $35 overdraft fee on retail's checking as goodwill");

    const created = await waitForNewApprovals(request, token, before, RUN_TIMEOUT, page);
    expect(created.length, 'exactly one approval from one objective').toBe(1);

    const approval = created[0];
    // `proposed` then `pending`, and the transition is quick enough that polling
    // authority can catch either. The invariant is that the record is OPEN and
    // awaiting people, not which of the two labels it wears in that instant —
    // `TaskQueuePane` groups both as open for exactly this reason. Asserting
    // `pending` alone made this test lose a race it had no business running.
    expect(['proposed', 'pending'], 'the approval is open and awaiting signatures').toContain(
      approval.status
    );
    expect(approval.requiredRung, 'a credit is dual control').toBe('L2');
    expect(approval.requiredSigners).toBe(2);
    expect(approval.payload.direction, 'a refund is money going back to the customer').toBe(
      'credit'
    );

    // Now prove the CARD says it, not just the record. The dock is still showing
    // an unrelated queue item at this point; `selectApprovalByHash` docks ours
    // and fails loudly if the queue never surfaces it.
    await selectApprovalByHash(page, approval.payloadHashShort);
    const dock = approvalDock(page);

    await expect(dock.getByText(`payload ${approval.payloadHashShort}`)).toBeVisible();
    await expect(dock.getByText('SIGNATURE REQUIRED')).toBeVisible();
    await expect(
      dock.getByText(`${approval.requiredRung} · ${approval.requiredSigners} signers`),
      'the rung on the card must be the rung authority assigned'
    ).toBeVisible();

    // Present and offered — deliberately NOT clicked. Signing is permitted here
    // but is not what this test is for, and bulk signing is not permitted at all.
    await expect(dock.getByRole('button', { name: /^Sign — / })).toHaveCount(1);
  });

  test('an unknown subject refuses by name of code, and discloses nothing', async ({
    page,
    request,
  }) => {
    const token = await login(request, 'banker');
    const before = await approvalIds(request, token);
    await openCopilot(page, token, 'banker');

    // A customer reference that resolves to nothing. Deliberately digit-free, so
    // that the no-digits assertion below is about what the SURFACE chose to say
    // and not about the objective being echoed back.
    await submitObjective(page, "Summarise nonexistent-customer-zqx's accounts and recent activity");

    const notice = refusalNotice(page);
    await expect(notice).toBeVisible({ timeout: RUN_TIMEOUT });

    const text = await notice.innerText();

    // A NAMED code. `refusalCopy` falls back to this headline for anything it
    // does not recognise, and a fallback refusal is a refusal we cannot reason
    // about.
    expect(text, 'the refusal must be one of the named codes').not.toContain(
      'The run stopped without producing a result'
    );
    const code = text.match(/·\s*([a-z_]+)\s*$/m)?.[1];
    expect(code, 'the refusal renders its code for the trace').toBeTruthy();
    expect(['subject_not_found', 'ambiguous_subject']).toContain(code);

    await expect(notice).toContainText('Nothing was signed and nothing was executed');

    // NON-DISCLOSURE — Danny's ruling. A refusal that names its candidates turns
    // the error channel into the customer-search API we deliberately declined to
    // build, and a COUNT alone still answers "does a customer like this exist?".
    // Hence: no customer names, and no digits at all.
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
    expect(text, 'a digit in a refusal is a count, and a count is a disclosure').not.toMatch(/\d/);

    const created = (await listApprovals(request, token)).filter((a) => !before.has(a.id));
    expect(created.map((a) => a.id), 'a refused run must create no approval').toEqual([]);
  });
});
