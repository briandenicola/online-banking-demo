import {
  COMPARISON_METRICS,
  endTask,
  exportComparisonData,
  recordContextSwitch,
  recordDecision,
  recordInteraction,
  resetComparisonData,
  setComparisonEnabled,
  SHARED_TASK_SET,
  startTask,
  summarise,
} from '../comparison';

describe('comparison instrumentation', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    resetComparisonData();
    setComparisonEnabled(true);
  });

  afterEach(() => {
    setComparisonEnabled(false);
  });

  it('records nothing at all when the flag is off', () => {
    setComparisonEnabled(false);
    const session = startTask('review-flagged-txn', 'classic');
    recordInteraction(session, 'click');
    endTask(session, 'completed');

    const data = exportComparisonData();
    expect(data.sessions).toHaveLength(0);
    expect(data.events).toHaveLength(0);
  });

  it('counts interactions and context switches per task session', () => {
    const session = startTask('review-flagged-txn', 'classic');
    recordInteraction(session, 'open-row');
    recordInteraction(session, 'expand-detail');
    recordContextSwitch(session, 'flagged-tab', 'all-transactions-tab');
    endTask(session, 'completed');

    const summary = summarise('classic');
    expect(summary.taskCount).toBe(1);
    expect(summary.completedCount).toBe(1);
    expect(summary.medianInteractionCount).toBe(2);
    expect(summary.medianContextSwitchCount).toBe(1);
  });

  it('keeps the two surfaces in separate summaries', () => {
    const classic = startTask('review-flagged-txn', 'classic');
    recordContextSwitch(classic, 'a', 'b');
    recordContextSwitch(classic, 'b', 'c');
    endTask(classic, 'completed');

    const copilot = startTask('review-flagged-txn', 'copilot');
    endTask(copilot, 'completed');

    expect(summarise('classic').medianContextSwitchCount).toBe(2);
    expect(summarise('copilot').medianContextSwitchCount).toBe(0);
  });

  it('records decisions using the ratified lifecycle vocabulary', () => {
    const session = startTask('approve-transfer', 'copilot');
    recordDecision(session, {
      approvalId: 'apr_123',
      requiredRung: 'L1',
      decision: 'denied',
      terminalReason: 'HUMAN_DENIED',
      dwellMs: 9000,
      evidenceOpened: true,
    });
    endTask(session, 'completed');

    const summary = summarise('copilot');
    expect(summary.deniedCount).toBe(1);
    expect(summary.signedCount).toBe(0);
    expect(summary.evidenceOpenRate).toBe(1);
  });

  it('computes median signature dwell from signed decisions only', () => {
    const session = startTask('approve-transfer', 'copilot');
    recordDecision(session, {
      approvalId: 'apr_1',
      requiredRung: 'L1',
      decision: 'signed',
      dwellMs: 4000,
      evidenceOpened: true,
    });
    recordDecision(session, {
      approvalId: 'apr_2',
      requiredRung: 'L1',
      decision: 'signed',
      dwellMs: 8000,
      evidenceOpened: false,
    });
    recordDecision(session, {
      approvalId: 'apr_3',
      requiredRung: 'L1',
      decision: 'denied',
      terminalReason: 'HUMAN_DENIED',
      dwellMs: 60000,
      evidenceOpened: true,
    });

    expect(summarise('copilot').medianSignatureDwellMs).toBe(6000);
    expect(summarise('copilot').evidenceOpenRate).toBeCloseTo(2 / 3);
  });

  it('marks signing speed as suspicious rather than better', () => {
    // Epic §9 risk 1: a falling time-to-sign is a defect, not adoption. This is
    // asserted in a test because it is the single easiest thing to get
    // backwards when someone later builds a chart from these metrics.
    const dwell = COMPARISON_METRICS.find((m) => m.key === 'signatureDwellMs');
    const rate = COMPARISON_METRICS.find((m) => m.key === 'signaturesPerHour');
    expect(dwell?.direction).toBe('lowerIsSuspicious');
    expect(rate?.direction).toBe('lowerIsSuspicious');
  });

  it('treats denial rate as explicitly neutral', () => {
    const denial = COMPARISON_METRICS.find((m) => m.key === 'denialRate');
    expect(denial?.direction).toBe('neutral');
  });

  it('ships the interpretation warnings inside the export', () => {
    // The caveats travel with the numbers so a reader cannot separate them.
    const data = exportComparisonData();
    expect(data.interpretationWarnings.length).toBeGreaterThan(0);
    expect(data.interpretationWarnings.join(' ')).toMatch(/DEFECT/);
    expect(data.metrics).toEqual(COMPARISON_METRICS);
  });

  it('returns null medians rather than zero when there is no data', () => {
    // Zero would read as a real measurement of "instant", which is worse than
    // admitting we have nothing.
    const summary = summarise('copilot');
    expect(summary.medianTaskDurationMs).toBeNull();
    expect(summary.evidenceOpenRate).toBeNull();
  });

  it('ignores events for unknown sessions without throwing', () => {
    expect(() => recordInteraction('cmp_nonexistent', 'click')).not.toThrow();
    expect(() => endTask('cmp_nonexistent', 'completed')).not.toThrow();
  });
});

describe('shared task set (pre-registration)', () => {
  it('includes a task that favours Classic Admin, so the comparison can be lost', () => {
    const flagged = SHARED_TASK_SET.find((t) => t.taskKey === 'review-flagged-txn');
    expect(flagged).toBeDefined();
    expect(flagged!.rationale.toLowerCase()).toContain('unfavourable to the harness');
  });

  it('has unique task keys, since taskKey is the cross-surface join key', () => {
    const keys = SHARED_TASK_SET.map((t) => t.taskKey);
    expect(new Set(keys).size).toBe(keys.length);
  });
});
