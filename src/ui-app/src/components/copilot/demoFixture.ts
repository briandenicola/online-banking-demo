/**
 * A recorded run, used for two things: demo mode when the service is not
 * running, and as the reducer's test input.
 *
 * It is the same `CopilotEvent[]` shape the wire produces — NOT a special
 * fixture format. That is on purpose: if the fixture had its own shape, the
 * reducer tests would be testing a code path the product never executes, and a
 * schema drift between the frontend and banker-copilot-service would still pass
 * the whole suite. Same reason #333 replays this envelope rather than a bespoke
 * eval record.
 *
 * The scenario deliberately contains the hard cases: a plan revision mid-run, a
 * supervisor agent that DISAGREES with the primary, and an L2 approval whose
 * rung was raised by two escalators.
 */

import {
  Approval,
  CopilotEvent,
  PayloadField,
  SignatureSlot,
} from './types';

const RUN_ID = 'run_demo_0001';
const T0 = Date.UTC(2026, 4, 12, 14, 30, 0);
const at = (offsetMs: number): string => new Date(T0 + offsetMs).toISOString();

let seq = 0;
const next = (): number => {
  seq += 1;
  return seq;
};

const payloadFields: PayloadField[] = [
  { path: 'accountId', label: 'Account', value: '····8891', format: 'accountRef', material: true },
  { path: 'amount', label: 'Amount', value: 24500, format: 'currency', material: true },
  { path: 'counterparty', label: 'Counterparty', value: 'Meridian Freight LLC', format: 'text', material: true },
  { path: 'action', label: 'Action', value: 'Place 72-hour hold', format: 'text', material: true },
  { path: 'caseRef', label: 'Case reference', value: 'CASE-2026-0417', format: 'text' },
];

const slots: SignatureSlot[] = [
  {
    ordinal: 1,
    minSeniority: 1,
    mustDifferFrom: [],
    signedBy: undefined,
    filled: false,
  },
  {
    // No `cosignerId`, and none is inferable from this slot. The second slot
    // states a RULE — must differ from the requester, minimum seniority 2 — and
    // never a person. Naming the co-signer at proposal time is the self-dealing
    // pattern L2 exists to prevent.
    ordinal: 2,
    minSeniority: 2,
    mustDifferFrom: ['user_banker_demo'],
    filled: false,
  },
];

export const demoApproval: Approval = {
  id: 'apr_demo_0001',
  status: 'pending',
  actionId: 'act_hold_funds',
  actionLabel: 'Place a 72-hour hold on ····8891',
  requesterId: 'user_banker_demo',
  requesterUsername: 'j.okafor',
  sessionId: 'sess_demo',
  payload: payloadFields,
  rawPayload: {
    accountId: '····8891',
    amount: 24500,
    counterparty: 'Meridian Freight LLC',
    action: 'Place 72-hour hold',
    caseRef: 'CASE-2026-0417',
  },
  evidence: [
    {
      id: 'ev_1',
      kind: 'tool_result',
      label: 'Three wires to the same counterparty in 48 hours',
      sourceToolCallId: 'tc_2',
      excerpt: '2026-05-10 $8,200 · 2026-05-11 $8,100 · 2026-05-11 $8,200',
      findings: [
        { path: 'transferCount', label: 'Transfer count', value: 3, format: 'text', material: true },
        { path: 'windowHours', label: 'Window hours', value: 48, format: 'text', material: false },
        { path: 'aggregate', label: 'Aggregate', value: 24500, format: 'currency', material: true },
      ],
    },
    {
      id: 'ev_2',
      kind: 'record',
      label: 'Counterparty first seen 6 days ago',
      sourceToolCallId: 'tc_3',
      findings: [
        { path: 'firstSeenDaysAgo', label: 'First seen days ago', value: 6, format: 'text', material: false },
      ],
    },
    {
      id: 'ev_3',
      kind: 'policy',
      label: 'AML-14 structuring threshold',
      sourceToolCallId: 'tc_4',
      excerpt: 'Three or more transfers within 72h aggregating above $20,000.',
      findings: [
        { path: 'threshold', label: 'Threshold', value: 20000, format: 'currency', material: true },
      ],
    },
  ],
  // Every field below is a field the REGENERATED GOLDEN WIRE FIXTURE
  // (`tests/fixtures/copilot-wire-envelopes.json`) actually carries, and
  // `demoFixtureShape.test.ts` fails if this fixture ever invents one that the
  // service does not send. Three separate defects on this card came from this
  // fixture teaching the UI a shape the service has never produced, so the rule
  // is now held by a test instead of by a comment.
  assessments: [
    {
      // No `agentId`: the golden wire's primary assessment carries none. The
      // supervisor's is `run_demo::supervisor`, derived from its subagent run id;
      // the primary is the run itself and has no separate one.
      agentName: 'Primary agent',
      role: 'primary',
      // The action is `transaction.hold.place`. The primary PROPOSED it, so its verdict is
      // `proceed` — proceed with placing the hold. Prose verdicts ("Recommend hold") were
      // invented vocabulary the server never emits, and on an adverse action they read
      // backwards: "hold" is the noun in the action, not the verdict.
      verdict: 'proceed',
      // The primary now makes a REAL model-backed assessment, so it states its own
      // confidence, its own factors and what it could not establish. Until this week it
      // emitted only `{summary, evidenceToolIds}` and this fixture deliberately carried
      // neither, because inventing them is what taught the UI a shape that did not exist.
      // They are here now because the wire carries them — not because the card looks
      // better with them.
      selfReportedConfidence: 0.88,
      rationale:
        'Amounts sit just under the $8,500 single-wire review threshold and aggregate above the AML-14 structuring trigger.',
      keyFactors: [
        // `{label, citedEvidenceIds}`. No `value` and no `concern`: a flat model factor is
        // a statement, not a dimension-and-measurement pair, and the builder has no
        // parameter for either.
        { label: 'amounts reconcile against the flagged transaction record' },
        { label: 'aggregate crosses the AML-14 structuring trigger' },
      ],
      unverified: ["the beneficiary's identity could not be established"],
      citedEvidenceIds: ['ev_1', 'ev_3'],
      mode: 'foundry',
      modelDeployment: 'gpt-4o-banker',
      promptSha256: 'sha256:5772aae6c2733eddaae29ee24193f56311e01ab7a5a30f513472ae86fa6ca0cc',
      responseSha256: 'sha256:36903754aa4b4e04e8516e7c8acfc524b34641adb6d82333317a71b235f25efa',
    },
    {
      agentId: 'agent_supervisor',
      agentName: 'Independent supervisor',
      role: 'supervisor',
      // "Recommend release" argued AGAINST placing the hold — that is `decline`, the
      // strongest objection available, not a mild condition. Under the old label adapter
      // this exact opinion reached the screen as "CONDITIONAL".
      verdict: 'decline',
      selfReportedConfidence: 0.62,
      rationale:
        'Counterparty is a freight vendor and the customer runs a haulage business; the pattern matches invoice settlement, not structuring.',
      keyFactors: [
        // Flat statements, which is what a decider actually holds: `SecondOpinion.
        // key_factors` is a `tuple[str, ...]` of the supervisor's own short factors.
        // The `value` field is absent because the service has nothing to put in it —
        // it used to send the constant "independently corroborated", which was not
        // read off anything.
        { label: 'counterparty is an established freight vendor' },
        { label: 'pattern matches invoice settlement' },
      ],
      citedEvidenceIds: ['ev_2'],
      // NO attribution block, and that asymmetry is real rather than an oversight.
      // `supervisor_wire_assessment` spreads attribution only when the decider
      // supplied one, and the golden capture's supervisor supplies none. Adding a
      // plausible-looking `modelDeployment` here would show a reader that the two
      // opinions came from the same base model — a fact this fixture cannot know
      // and the capture does not state. That invention is precisely the bug this
      // fixture has now produced three times.
    },
  ],
  // SERVER-STATED, never re-derived here. `fanout.py` puts `compare_verdicts`'
  // result on the wire beside the two verdicts; a fixture with two assessments
  // and no `agreement` is a shape the service never emits.
  assessmentAgreement: 'diverge',
  payloadHash: '9f2c4a7b1e8d3f60a5c2b9e4d7f1a8c3b6e9d2f5a8c1b4e7d0f3a6c9b2e5d8f1',
  payloadHashShort: '9f2c4a7b',
  policyVersion: 'policy-2026.05.1',
  policyId: 'pol_hold_funds',
  baseRung: 'L1',
  requiredRung: 'L2',
  requiredSigners: 2,
  signaturesCollected: 0,
  firedEscalators: [
    {
      key: 'amount_above_threshold',
      raisedTo: 'L2',
      thresholdName: 'hold_amount',
      thresholdValue: '$20,000',
      reason: 'Aggregate hold value exceeds the L1 ceiling.',
    },
    {
      key: 'agent_disagreement',
      raisedTo: 'L2',
      reason: 'The independent reviewer reached the opposite conclusion.',
    },
  ],
  signatureSlots: slots,
  createdAt: at(31_000),
  expiresAt: at(31_000 + 15 * 60 * 1000),
  executionState: 'not_started',
  callerMaySign: true,
};

export const demoEvents: CopilotEvent[] = [
  {
    id: 'evt_1',
    seq: next(),
    runId: RUN_ID,
    kind: 'run.started',
    ts: at(0),
    payload: {
      taskId: 'task_demo',
      title: 'Review overnight flagged wires',
      intent: 'Review the flagged wires from overnight and tell me which need action',
      actor: { id: 'user_banker_demo', role: 'banker', displayName: 'J. Okafor' },
      startedAt: at(0),
    },
  },
  {
    id: 'evt_2',
    seq: next(),
    runId: RUN_ID,
    kind: 'plan.proposed',
    ts: at(400),
    payload: {
      version: 1,
      steps: [
        { id: 'st_1', index: 0, title: 'Pull overnight flagged transactions', status: 'pending' },
        { id: 'st_2', index: 1, title: 'Group flags by counterparty and account', status: 'pending' },
        { id: 'st_3', index: 2, title: 'Draft a recommendation per group', status: 'pending' },
      ],
    },
  },
  {
    id: 'evt_3',
    seq: next(),
    runId: RUN_ID,
    kind: 'step.started',
    ts: at(500),
    payload: { stepId: 'st_1', index: 0, title: 'Pull overnight flagged transactions' },
  },
  {
    id: 'evt_4',
    seq: next(),
    runId: RUN_ID,
    kind: 'tool.started',
    ts: at(600),
    payload: {
      toolCallId: 'tc_1',
      stepId: 'st_1',
      name: 'transactions.listFlagged',
      args: { since: at(-43_200_000) },
      attempt: 1,
    },
  },
  {
    id: 'evt_5',
    seq: next(),
    runId: RUN_ID,
    kind: 'tool.completed',
    ts: at(1_900),
    payload: { toolCallId: 'tc_1', durationMs: 1_300, resultSummary: '7 flagged transactions' },
  },
  {
    id: 'evt_6',
    seq: next(),
    runId: RUN_ID,
    kind: 'step.completed',
    ts: at(2_000),
    payload: { stepId: 'st_1', durationMs: 1_500, summary: '7 flagged' },
  },
  {
    id: 'evt_7',
    seq: next(),
    runId: RUN_ID,
    kind: 'step.started',
    ts: at(2_100),
    payload: { stepId: 'st_2', index: 1, title: 'Group flags by counterparty and account' },
  },
  {
    id: 'evt_8',
    seq: next(),
    runId: RUN_ID,
    kind: 'tool.started',
    ts: at(2_200),
    payload: { toolCallId: 'tc_2', stepId: 'st_2', name: 'transactions.correlate', attempt: 1 },
  },
  {
    id: 'evt_9',
    seq: next(),
    runId: RUN_ID,
    kind: 'tool.completed',
    ts: at(3_600),
    payload: {
      toolCallId: 'tc_2',
      durationMs: 1_400,
      resultSummary: '3 of 7 share one counterparty',
    },
  },
  // The plan changes its mind. This is the moment the surface exists to show.
  {
    id: 'evt_10',
    seq: next(),
    runId: RUN_ID,
    kind: 'plan.revised',
    ts: at(3_800),
    payload: {
      version: 2,
      reason: 'Three flags share a counterparty — treating them as one pattern, not three incidents',
      addedStepIds: ['st_4'],
      removedStepIds: [],
      at: at(3_800),
      steps: [
        {
          id: 'st_4',
          index: 2,
          title: 'Assess the Meridian Freight cluster as a single pattern',
          status: 'pending',
        },
      ],
    },
  },
  {
    id: 'evt_11',
    seq: next(),
    runId: RUN_ID,
    kind: 'step.completed',
    ts: at(3_900),
    payload: { stepId: 'st_2', durationMs: 1_800 },
  },
  {
    id: 'evt_12',
    seq: next(),
    runId: RUN_ID,
    kind: 'step.started',
    ts: at(4_000),
    payload: { stepId: 'st_4', index: 2, title: 'Assess the Meridian Freight cluster as a single pattern' },
  },
  {
    id: 'evt_13',
    seq: next(),
    runId: RUN_ID,
    kind: 'subagent.spawned',
    ts: at(4_100),
    payload: {
      subagentId: 'sa_1',
      parentStepId: 'st_4',
      name: 'Counterparty history',
      role: 'specialist',
      depth: 1,
    },
  },
  {
    id: 'evt_14',
    seq: next(),
    runId: RUN_ID,
    kind: 'tool.started',
    ts: at(4_200),
    payload: {
      toolCallId: 'tc_3',
      stepId: 'st_4',
      subagentId: 'sa_1',
      name: 'counterparty.lookup',
      attempt: 1,
    },
  },
  {
    id: 'evt_15',
    seq: next(),
    runId: RUN_ID,
    kind: 'tool.completed',
    ts: at(5_100),
    payload: { toolCallId: 'tc_3', durationMs: 900, resultSummary: 'First seen 6 days ago' },
  },
  {
    id: 'evt_16',
    seq: next(),
    runId: RUN_ID,
    kind: 'tool.started',
    ts: at(5_200),
    payload: { toolCallId: 'tc_4', stepId: 'st_4', subagentId: 'sa_1', name: 'policy.match', attempt: 1 },
  },
  {
    id: 'evt_17',
    seq: next(),
    runId: RUN_ID,
    kind: 'tool.completed',
    ts: at(6_000),
    payload: { toolCallId: 'tc_4', durationMs: 800, resultSummary: 'AML-14 structuring' },
  },
  {
    id: 'evt_18',
    seq: next(),
    runId: RUN_ID,
    kind: 'subagent.completed',
    ts: at(6_100),
    payload: {
      subagentId: 'sa_1',
      status: 'complete',
      confidence: 0.81,
      // No `verdictSummary`. The ONLY producer of this field in the service is
      // `fanout.py`, which fills it with a verdict token for the SUPERVISOR. A
      // specialist has no verdict, so prose here ('Pattern matches AML-14 structuring')
      // taught the UI that the field is free-form narration when live it is a
      // one-word structural caption. (That the planner emits no specialist
      // `subagent.completed` at all is a wider demo-vs-service gap — noted, not fixed.)
      durationMs: 2_000,
    },
  },
  // The supervisor is spawned with no parent step: it is a sibling of the plan,
  // not a child of the reasoning it is reviewing.
  {
    id: 'evt_19',
    seq: next(),
    runId: RUN_ID,
    kind: 'subagent.spawned',
    ts: at(6_200),
    payload: {
      subagentId: 'sa_sup',
      parentStepId: '',
      name: 'Independent review',
      role: 'supervisor',
      depth: 1,
    },
  },
  {
    id: 'evt_20',
    seq: next(),
    runId: RUN_ID,
    kind: 'subagent.completed',
    ts: at(8_400),
    payload: {
      subagentId: 'sa_sup',
      status: 'complete',
      confidence: 0.62,
      // `fanout.py` sends `verdict_for(opinion.recommendation)` here and documents it as
      // "a short, server-derived summary of the STRUCTURAL opinion, never free prose the
      // supervisor authored". The fixture carried authored prose ('Recommend release —
      // vendor settlement pattern') and TracePane renders this field in quotation marks,
      // so the demo showed a sentence attributed to the supervisor that the service is
      // explicitly built never to emit. Third fixture-vs-service divergence found today.
      verdictSummary: 'DECLINE',
      durationMs: 2_200,
    },
  },
  {
    id: 'evt_21',
    seq: next(),
    runId: RUN_ID,
    kind: 'artifact.created',
    ts: at(8_600),
    payload: {
      artifactId: 'art_1',
      kind: 'decision_memo',
      title: 'Meridian Freight cluster',
      revision: 1,
      content:
        'Three wires totalling $24,500 to Meridian Freight LLC over 48 hours.\n\n' +
        'The transaction reviewer reads this as structuring under AML-14: the amounts sit just below the single-wire review threshold and aggregate above the reporting trigger.\n\n' +
        'The independent reviewer disagrees, reading it as invoice settlement for a haulage customer with four comparable vendor payments in the last year.\n\n' +
        'The two reviewers reached opposite conclusions, which is itself why this requires two signatures.',
    },
  },
  {
    id: 'evt_22',
    seq: next(),
    runId: RUN_ID,
    kind: 'step.completed',
    ts: at(8_700),
    payload: { stepId: 'st_4', durationMs: 4_700 },
  },
  {
    id: 'evt_23',
    seq: next(),
    runId: RUN_ID,
    kind: 'approval.required',
    ts: at(31_000),
    payload: {
      approval: demoApproval,
      policyVersion: demoApproval.policyVersion,
      requiredRung: 'L2',
    },
  },
  {
    id: 'evt_24',
    seq: next(),
    runId: RUN_ID,
    kind: 'run.done',
    ts: at(31_100),
    payload: {
      status: 'completed',
      durationMs: 31_100,
      finalArtifactIds: ['art_1'],
      finalSeq: seq,
    },
  },
];

export default demoEvents;
