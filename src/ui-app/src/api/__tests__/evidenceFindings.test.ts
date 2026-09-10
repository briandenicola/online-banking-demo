/**
 * Evidence must carry what the agent FOUND, not merely which tool it called.
 *
 * The reported defect: Brian's card listed "Get user · List login audits" — the
 * tool names — while the record carried real values underneath them. Two
 * client-side drops, both of which had to be fixed for either to matter:
 *
 *   1. `toEvidence` took the object KEY for a label and discarded the value.
 *      `excerpt` was only populated from a nested `summary` string or a value
 *      that was itself a string, so a structured result like
 *      `{ accountId, balance }` produced nothing at all.
 *   2. `EvidenceList` rendered `item.label` and never any value.
 *
 * Nothing was stripped by the service and nothing was lost in transit — the wire
 * carried it the whole way.
 */

import { toApproval, WireApproval } from '../authorityWire';
import fixture from './bankerApprovalsWire.fixture.json';

function withEvidence(evidence: Record<string, unknown>): WireApproval {
  return { ...(fixture.items[0] as unknown as WireApproval), evidence };
}

describe('evidence findings survive the wire mapping', () => {
  it('keeps the values from a real evidence record', () => {
    // Exactly the shape from a live approval.
    const approval = toApproval(
      withEvidence({
        get_account: { accountId: 'e3bdc96d-1111-2222-3333-444455556666', balance: 59480 },
        list_account_transactions: {
          accountId: 'e3bdc96d-1111-2222-3333-444455556666',
          count: 3,
        },
      })
    );

    expect(approval.evidence).toHaveLength(2);

    const account = approval.evidence.find((e) => e.id === 'get_account')!;
    // The tool name still labels the group — that part was never wrong.
    expect(account.label).toBe('Get account');
    // ...but the finding is now present, which is the whole point.
    const balance = account.findings.find((f) => f.path === 'balance')!;
    expect(balance).toBeDefined();
    expect(balance.value).toBe(59480);

    const txns = approval.evidence.find((e) => e.id === 'list_account_transactions')!;
    expect(txns.findings.find((f) => f.path === 'count')!.value).toBe(3);
  });

  it('does not repeat the lifted metadata as if it were a finding', () => {
    const approval = toApproval(
      withEvidence({
        policy_check: {
          kind: 'policy',
          label: 'Policy check',
          toolCallId: 'call_7',
          summary: 'Within the L1 ceiling.',
          href: 'https://example.test/policy',
          ceiling: 25000,
        },
      })
    );

    const [item] = approval.evidence;
    expect(item.kind).toBe('policy');
    expect(item.label).toBe('Policy check');
    expect(item.sourceToolCallId).toBe('call_7');
    expect(item.excerpt).toBe('Within the L1 ceiling.');

    // Those five are rendered in their own right; repeating them below the label
    // would be noise.
    expect(item.findings.map((f) => f.path)).toEqual(['ceiling']);
  });

  it('gives every ref a findings array, never undefined', () => {
    // Callers should not each have to invent a guard.
    const approval = toApproval(
      withEvidence({ note: 'A plain string result.', empty: {}, missing: null })
    );
    approval.evidence.forEach((item) => {
      expect(Array.isArray(item.findings)).toBe(true);
    });
    // A bare string was already handled as an excerpt; it is not also a finding.
    expect(approval.evidence.find((e) => e.id === 'note')!.excerpt).toBe('A plain string result.');
    expect(approval.evidence.find((e) => e.id === 'note')!.findings).toEqual([]);
  });

  it('flattens nested results rather than dropping them', () => {
    const approval = toApproval(
      withEvidence({ get_user: { profile: { username: 'j.okafor', active: true } } })
    );
    const paths = approval.evidence[0].findings.map((f) => f.path);
    expect(paths).toContain('profile.username');
    expect(paths).toContain('profile.active');
  });

  it('survives an evidence object that is absent or malformed', () => {
    expect(toApproval({ ...(fixture.items[0] as unknown as WireApproval), evidence: undefined })
      .evidence).toEqual([]);
  });
});
