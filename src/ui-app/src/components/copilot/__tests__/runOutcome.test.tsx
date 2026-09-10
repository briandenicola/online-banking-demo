/**
 * The two run outcomes the free-text planner introduced.
 *
 * Before Turk's intent planner a run either produced an approval or died at the
 * transport. Now it can end in a read-only ANSWER with no approval, or in a
 * named REFUSAL. Brian's original complaint was that a free-text objective
 * produced "1 step, 320ms, empty evidence bundle" and still reported itself
 * completed, and he was right to disbelieve it. Turk's structural invariant is
 * that no case may complete as a successful empty evidence bundle; these tests
 * hold the VISUAL half of that invariant, because a refusal drawn as a short
 * completed run is the same lie with better structure behind it.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import TracePane from '../TracePane';
import ArtifactCanvas from '../ArtifactCanvas';
import { answerContent, isNonDisclosing, refusalCopy } from '../runOutcome';
import { Artifact, RunState } from '../types';

jest.mock('../CopilotContext', () => ({
  useNow: () => Date.now(),
  useCopilot: () => ({
    density: 'comfortable',
    setDensity: jest.fn(),
    streamStatus: 'live',
    incomplete: false,
    sign: jest.fn(),
    deny: jest.fn(),
  }),
}));

/** Every code `loop.py` and `intent_model.py` actually emit, read from the source. */
const CODES = [
  'planner_model_unavailable',
  'intent_contract_invalid',
  'objective_unmappable',
  'forbidden_action',
  'ambiguous_subject',
  'subject_not_found',
  'payload_unfillable',
  'payload_invalid',
  'evidence_unavailable',
  'proposal_refused_by_authority',
];

function refusedRun(code: string, message: string): RunState {
  return {
    runId: 'run_1',
    title: 'Refund a $35 overdraft fee on retail’s checking as goodwill',
    status: 'failed',
    startedAt: new Date().toISOString(),
    durationMs: 4200,
    planVersion: 1,
    stepIds: [],
    steps: {},
    subagents: {},
    toolCalls: {},
    rootSubagentIds: [],
    revisions: [],
    artifactIds: [],
    approvalIds: [],
    error: { code, message, recoverable: false },
  } as unknown as RunState;
}

function answerRun(content: unknown): RunState {
  const artifact: Artifact = {
    id: 'art_1',
    kind: 'answer',
    title: 'Copilot answer',
    revision: 1,
    content,
  } as unknown as Artifact;
  return {
    runId: 'run_1',
    title: 'Summarise casey’s accounts and recent activity',
    status: 'completed',
    startedAt: new Date().toISOString(),
    durationMs: 7400,
    planVersion: 1,
    stepIds: [],
    steps: {},
    subagents: {},
    toolCalls: {},
    rootSubagentIds: [],
    revisions: [],
    artifactIds: ['art_1'],
    artifacts: { art_1: artifact },
    approvalIds: [],
  } as unknown as RunState;
}

describe('refusal copy', () => {
  it('covers every code the planner emits, with no code left to the fallback', () => {
    for (const code of CODES) {
      const copy = refusalCopy(code);
      expect(copy.title).not.toContain(code);
      expect(copy.what.length).toBeGreaterThan(20);
      expect(copy.showServerMessage).toBe(true);
    }
  });

  it('does not coerce an unrecognised code into the nearest known one', () => {
    const copy = refusalCopy('planner_error');
    expect(copy.title).toMatch(/stopped without producing a result/i);
    expect(copy.what).toContain('planner_error');

    // The catch-all path emits `str(exc)` as its message. A Python exception
    // string is not banker-readable and is the one message nobody vetted for
    // disclosure, so it must not be rendered.
    expect(copy.showServerMessage).toBe(false);
  });

  it('never claims no tools were called on a path that performed reads', () => {
    // "No plan was formed and no tools were called" is a reassuring, CHECKABLE
    // claim. It is true where the run refused at interpretation and false once
    // the resolver has done lookups, so it must not be boilerplate.
    expect(refusalCopy('forbidden_action').readsPerformed).toBe('none');
    expect(refusalCopy('objective_unmappable').readsPerformed).toBe('none');
    expect(refusalCopy('ambiguous_subject').readsPerformed).toBe('some');
    expect(refusalCopy('evidence_unavailable').readsPerformed).toBe('some');
  });

  it('discloses nothing about which records matched a subject reference', () => {
    // Danny's ruling: a refusal that names its candidates turns the error
    // channel into the customer-search API we deliberately declined to build.
    // A COUNT is disclosure too — "3 customers matched" answers "does a
    // customer like this exist?" just as well as a list of names.
    for (const code of ['ambiguous_subject', 'subject_not_found']) {
      expect(isNonDisclosing(code)).toBe(true);
      const copy = refusalCopy(code);
      const text = `${copy.title} ${copy.what} ${copy.next}`;
      expect(text).not.toMatch(/\d/);
      expect(text).not.toMatch(/casey|dana|retail|verify-target/i);
    }
  });
});

describe('a refused run in the trace pane', () => {
  it('reads as a refusal rather than as a completed run that happens to be empty', () => {
    render(
      <TracePane
        run={refusedRun(
          'ambiguous_subject',
          'More than one customer matched the supplied reference; no customer was selected.'
        )}
      />
    );

    const notice = screen.getByRole('note', { name: /this run was refused/i });
    expect(notice).toHaveTextContent(/refused/i);
    expect(notice).toHaveTextContent(/was not unique/i);
    expect(notice).toHaveTextContent(/nothing was signed and nothing was executed/i);

    // The banker is told what to do next, not merely that it failed.
    expect(notice).toHaveTextContent(/full username or an account number/i);
  });

  it('shows the server message for a named code, and suppresses it otherwise', () => {
    const { unmount } = render(
      <TracePane run={refusedRun('forbidden_action', 'That action is outside the Copilot harness.')} />
    );
    expect(screen.getByRole('note', { name: /refused/i })).toHaveTextContent(
      /outside the Copilot harness/i
    );
    unmount();

    render(
      <TracePane
        run={refusedRun('planner_error', "KeyError: 'accountId' at loop.py line 812")}
      />
    );
    expect(screen.queryByText(/KeyError/)).toBeNull();
  });


  it('drops the server message entirely for the two non-disclosing codes', () => {
    // The UI must ENFORCE the ruling, not merely honour it. Turk's current
    // strings are safe, but the message is server-authored and can change
    // without this file being touched, so the guard is tested with a message
    // that deliberately leaks: a count and a name. Neither may reach the DOM.
    render(
      <TracePane
        run={refusedRun(
          'ambiguous_subject',
          '3 customers matched: casey.reed, casey.morgan, casey.two'
        )}
      />
    );

    const notice = screen.getByRole('note', { name: /refused/i });
    expect(notice).toHaveTextContent(/was not unique/i);
    expect(screen.queryByText(/casey\.reed/)).toBeNull();
    expect(notice.textContent).not.toMatch(/casey/i);
    expect(notice.textContent).not.toMatch(/3 customers/);
  });

  it('says nothing when a run merely completed', () => {
    const run = refusedRun('objective_unmappable', 'x');
    render(<TracePane run={{ ...run, status: 'completed', error: undefined } as RunState} />);
    expect(screen.queryByRole('note', { name: /refused/i })).toBeNull();
  });
});

describe('the read-only answer artifact', () => {
  const CONTENT = {
    answer:
      'Casey holds a checking and a savings account. Activity over the last 30 days is dominated by a single large payroll credit.',
    keyPoints: ['Checking balance is $16,143.46', 'One offshore wire is flagged for review'],
    citedEvidenceIds: ['list_customer_accounts', 'list_account_transactions'],
    unverified: ['Whether the offshore wire was pre-notified by the customer'],
  };

  it('renders as prose rather than the JSON dump it fell back to', () => {
    render(<ArtifactCanvas run={answerRun(CONTENT)} streamStatus="live" />);

    expect(screen.getByText(/dominated by a single large payroll credit/i)).toBeInTheDocument();
    expect(screen.getByText(/One offshore wire is flagged for review/i)).toBeInTheDocument();

    // The JSON fallback would have put the field names on screen.
    expect(screen.queryByText(/"citedEvidenceIds"/)).toBeNull();
  });

  it('gives the unverified list the register the approval card uses', () => {
    render(<ArtifactCanvas run={answerRun(CONTENT)} streamStatus="live" />);
    expect(screen.getByText(/could not be established from the evidence/i)).toBeInTheDocument();
    expect(
      screen.getByText(/whether the offshore wire was pre-notified/i)
    ).toBeInTheDocument();
  });

  it('says plainly that there is nothing to sign', () => {
    // A banker who has watched every previous run end in a signature needs to be
    // told this one is not waiting on him, rather than inferring it from an
    // absent approval dock.
    render(<ArtifactCanvas run={answerRun(CONTENT)} streamStatus="live" />);
    expect(screen.getByText(/nothing was proposed and there is nothing to sign/i)).toBeInTheDocument();
  });

  it('omits the unverified heading entirely when the list is empty', () => {
    // An empty heading implies the agent checked and found no gaps. That is a
    // stronger claim than staying silent and it is not one the evidence makes.
    render(<ArtifactCanvas run={answerRun({ ...CONTENT, unverified: [] })} streamStatus="live" />);
    expect(screen.queryByText(/could not be established/i)).toBeNull();
    expect(screen.getByText(/dominated by a single large payroll credit/i)).toBeInTheDocument();
  });

  it('is recognised by shape, so a thin answer degrades to prose not to JSON', () => {
    expect(answerContent({ content: { answer: 'Yes.' } } as unknown as Artifact)).toEqual({
      answer: 'Yes.',
      keyPoints: [],
      citedEvidenceIds: [],
      unverified: [],
    });

    // An evidence bundle is not an answer and must keep its own renderer.
    expect(answerContent({ content: { get_account: { balance: 1 } } } as unknown as Artifact)).toBeUndefined();
    expect(answerContent({ content: { answer: '   ' } } as unknown as Artifact)).toBeUndefined();
    expect(answerContent(undefined)).toBeUndefined();
  });
});
