/**
 * The banker's live queue, end to end: wire JSON → `toApproval` → `groupApprovals`.
 *
 * The fixture is a faithful reduction of a real
 * `GET /api/authority/approvals?limit=200` response for user `banker`
 * (10 items, seeded 2026-09-10). Only `evidence` and `agentAssessment` are
 * emptied; every field the queue routes on is verbatim.
 *
 * This is a GUARD, not the proof of the empty-queue fix. `groupApprovals` was
 * never broken — the list never reached it. See
 * `api/__tests__/approvalsRequestPath.test.ts` for the regression itself. What
 * this pins is that the bucket predicates match the field names and enum
 * spellings the service actually emits, so a future contract move fails here.
 */

import { toApproval, WireApproval } from '../../../api/authorityWire';
import { groupApprovals } from '../TaskQueuePane';
import fixture from '../../../api/__tests__/bankerApprovalsWire.fixture.json';

const wire = fixture.items as unknown as WireApproval[];
const NOW = Date.parse('2026-09-10T13:10:00Z');

describe('groupApprovals against the live banker payload', () => {
  const approvals = wire.map(toApproval);

  it('maps all ten items without falling back to an unknown status', () => {
    expect(approvals).toHaveLength(10);
    expect(approvals.map((a) => a.status).sort()).toEqual(
      ['denied', 'signed', ...Array(8).fill('pending')].sort()
    );
  });

  it('reads callerMaySign, requiredRung and signaturesCollected as sent', () => {
    expect(approvals.filter((a) => a.callerMaySign)).toHaveLength(7);
    expect(approvals.filter((a) => a.requiredRung === 'L2')).toHaveLength(6);
    expect(approvals.filter((a) => a.requiredRung === 'L1')).toHaveLength(4);
    // The wire sends a NUMBER here, not an array. Reading `.length` off it
    // would yield undefined and silently break every signature-count display.
    approvals.forEach((a) => expect(typeof a.signaturesCollected).toBe('number'));
    expect(approvals.filter((a) => a.signaturesCollected > 0)).toHaveLength(2);
  });

  it('buckets 7 needing the banker, 1 awaiting a co-signer, 1 signed, 1 denied', () => {
    const groups = groupApprovals(approvals, NOW);

    expect(groups.needsYou).toHaveLength(7);
    expect(groups.awaitingCosigner).toHaveLength(1);
    // `running` is "signed, not yet executed" — the one signed item lands here,
    // and `doneToday` holds the terminal denial. demo.sh counts the signed item
    // as done instead; the two classifications differ and the UI's is the one
    // the pane documents.
    expect(groups.running).toHaveLength(1);
    expect(groups.doneToday).toHaveLength(1);

    expect(groups.needsYou.every((a) => a.callerMaySign)).toBe(true);
    expect(groups.awaitingCosigner[0].callerMaySignReason).toContain('you cannot also approve it');
    expect(groups.running[0].status).toBe('signed');
    expect(groups.doneToday[0].status).toBe('denied');
  });

  it('sorts the needsYou bucket by time remaining, never by amount', () => {
    const groups = groupApprovals(approvals, NOW);
    const expiries = groups.needsYou.map((a) => Date.parse(a.expiresAt));
    expect([...expiries].sort((x, y) => x - y)).toEqual(expiries);
  });

  it('accounts for every item exactly once', () => {
    const groups = groupApprovals(approvals, NOW);
    const total =
      groups.needsYou.length +
      groups.awaitingCosigner.length +
      groups.running.length +
      groups.doneToday.length;
    expect(total).toBe(10);
  });
});
