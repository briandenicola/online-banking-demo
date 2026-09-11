/**
 * The card's narrative layer, driven by the REAL banker payload.
 *
 * Every case here comes from `bankerApprovalsWire.fixture.json` — a verbatim reduction of a
 * live `GET /api/authority/approvals?limit=200` for user `banker`. Nothing is hand-authored,
 * because the failure mode this file exists to catch is a sentence that is grammatical,
 * confident and about the wrong thing. A fixture that agrees with my assumptions cannot catch
 * that; the service's own output can.
 *
 * The direction wording is pinned against `config/authority-policy.yaml:515-518`, which is the
 * authority on what `credit` means here: *"Crediting an account creates money, which is always
 * dual-control."* Credit = money into the customer's account. If that ever inverts, this file
 * fails rather than the card quietly telling a banker the opposite of what will happen.
 */

import { toApproval, WireApproval } from '../../../api/authorityWire';
import {
  approvalHeadline,
  subjectAbsence,
  whyThisRung,
  expiryConsequence,
  signingClosed,
  DENY_IS_FINAL,
} from '../approvalNarrative';
import { signingAttestation } from '../ApprovalCard';
import { Approval } from '../types';
import fixture from '../../../api/__tests__/bankerApprovalsWire.fixture.json';

const approvals: Approval[] = (fixture.items as unknown as WireApproval[]).map(toApproval);

const byAction = (actionId: string): Approval => {
  const found = approvals.find((a) => a.actionId === actionId);
  if (!found) throw new Error(`fixture has no ${actionId} — the payload moved, fix the test`);
  return found;
};

describe('approvalHeadline', () => {
  it('states the ask verb-first, with the money, for a debit adjustment', () => {
    // Fixture item 2: amount 920, direction debit.
    const headline = approvalHeadline(byAction('account.balance.adjust'));
    expect(headline).toBe("Take $920.00 off a customer's account");
  });

  it('reads the amount when the service sends it as a decimal STRING', () => {
    // The live payload is not consistent: most items send `amount` as a number, one sends
    // "2500.00" as a string. A headline that silently drops the figure on the largest
    // adjustment in the queue is precisely the wrong one to lose.
    const stringAmount = approvals.find(
      (a) => a.actionId === 'account.balance.adjust' && a.requiredRung === 'L2'
        && approvalHeadline(a).includes('2,500')
    );
    expect(stringAmount).toBeDefined();
  });

  it('does not print a raw identifier in the headline for any item in the live queue', () => {
    // §2: identifiers are never the primary reference. A GUID fragment leaking into the
    // headline is the exact defect Brian reported.
    const guidish = /[0-9a-f]{8}-[0-9a-f]{4}/i;
    approvals.forEach((a) => {
      expect(approvalHeadline(a)).not.toMatch(guidish);
    });
  });

  it('speaks about the customer, not the mechanism, for an unlock', () => {
    expect(approvalHeadline(byAction('user.unlock'))).toBe(
      "Let a customer back into their account"
    );
  });

  it('names the score it is being asked to set on an override', () => {
    expect(approvalHeadline(byAction('transaction.score.override'))).toBe(
      'Overrule the fraud score on one transaction, setting it to 0.25'
    );
  });

  it('falls back to the server label rather than guessing at an unknown action', () => {
    const unknown: Approval = {
      ...byAction('user.unlock'),
      actionId: 'account.close.permanently',
      actionLabel: 'Close an account permanently',
      payload: [],
    };
    expect(approvalHeadline(unknown)).toBe('Close an account permanently');
  });

  it('falls back rather than emitting a headline with a missing amount', () => {
    const noAmount: Approval = {
      ...byAction('account.balance.adjust'),
      payload: byAction('account.balance.adjust').payload.filter((f) => f.path !== 'amount'),
    };
    expect(approvalHeadline(noAmount)).toBe(noAmount.actionLabel);
  });

  it('says money is going IN when the direction is credit', () => {
    // Pinned against authority-policy.yaml:515 — credit creates money for the customer.
    const base = byAction('account.balance.adjust');
    const credit: Approval = {
      ...base,
      payload: base.payload.map((f) => (f.path === 'direction' ? { ...f, value: 'credit' } : f)),
    };
    expect(approvalHeadline(credit)).toBe("Put $920.00 back into a customer's account");
  });
});

describe('subjectAbsence', () => {
  it('says plainly that the customer is unknown, on every item in the live queue', () => {
    // §6.1 is Turk's and has not landed. Until it does, the honest statement is that the card
    // cannot identify the customer — NOT a GUID presented as though it were an answer.
    approvals.forEach((a) => {
      expect(subjectAbsence(a)).toContain('cannot yet tell you which customer');
    });
  });

  it('does not print the identifier it is apologising for', () => {
    approvals.forEach((a) => {
      expect(subjectAbsence(a)).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/i);
    });
  });

  it('stays silent on an approval with no customer subject at all', () => {
    const noSubject: Approval = { ...byAction('user.unlock'), payload: [] };
    expect(subjectAbsence(noSubject)).toBeNull();
  });
});

describe('whyThisRung', () => {
  it('replaces "No escalators fired" with a consequence for a base-rung L1', () => {
    // §6.4, assigned to the client. The old string described a code path.
    const text = whyThisRung('account.balance.adjust', 'L1');
    expect(text).not.toBeNull();
    expect(text).not.toMatch(/escalator|base rung/i);
    expect(text).toContain('yours alone');
  });

  it('explains an L2 in terms of what the second person is FOR', () => {
    const text = whyThisRung('user.unlock', 'L2');
    expect(text).toContain('two people');
    expect(text).toMatch(/restoring access/i);
  });

  it('is keyed on rung as well as action, so the same action reads differently at L1 and L2', () => {
    // A map keyed on action alone would confidently claim a single-signer approval
    // "always needs two people".
    expect(whyThisRung('account.balance.adjust', 'L1')).not.toEqual(
      whyThisRung('account.balance.adjust', 'L2')
    );
  });

  it('still says something true for an action it has never seen', () => {
    expect(whyThisRung('account.close.permanently', 'L2')).toContain('two people');
    expect(whyThisRung('account.close.permanently', 'L1')).toContain('yours alone');
  });

  it('returns null for an unknown rung rather than inventing a rule', () => {
    expect(whyThisRung('user.unlock', 'L3')).toBeNull();
  });

  it('covers every action id present in the live queue', () => {
    approvals.forEach((a) => {
      expect(whyThisRung(a.actionId, a.requiredRung)).not.toBeNull();
    });
  });
});

describe('expiryConsequence', () => {
  // The fixture was seeded on 2026-09-10 and its windows have since closed, so every case
  // that expects a forecast must pin `now` inside the window. That is not a convenience:
  // the fixture expiring is exactly how the past-tense defect below reached the browser.
  const INSIDE_WINDOW = Date.parse('2026-09-10T13:10:00Z');

  it('states the outcome and that nothing executes, with a wall-clock time', () => {
    const text = expiryConsequence(byAction('account.balance.adjust'), INSIDE_WINDOW);
    expect(text).toContain('automatically denied');
    expect(text).toContain('Nothing will execute');
    // A relative countdown alone cannot be acted on; a banker needs a time of day.
    expect(text).toMatch(/by \d{1,2}:\d{2}/);
  });

  it('names the consequence for the CUSTOMER on an unlock', () => {
    expect(expiryConsequence(byAction('user.unlock'), INSIDE_WINDOW)).toContain('stays locked out');
  });

  it('renders for every item in the live queue', () => {
    approvals.forEach((a) => expect(expiryConsequence(a, INSIDE_WINDOW)).not.toBeNull());
  });

  it('says nothing at all once the window has closed', () => {
    // Found in a real browser: a future-tense forecast about a deadline that has already
    // passed. The countdown chip already reports the closed window; the card must not also
    // promise that "nobody signing by 4:06 PM" will cause something that already happened.
    approvals.forEach((a) => {
      expect(expiryConsequence(a, Date.parse('2027-01-01T00:00:00Z'))).toBeNull();
    });
  });

  it('returns null rather than "Invalid Date" when expiry is unparseable', () => {
    const broken: Approval = { ...byAction('user.unlock'), expiresAt: 'not-a-date' };
    expect(expiryConsequence(broken, INSIDE_WINDOW)).toBeNull();
  });
});

describe('DENY_IS_FINAL', () => {
  it('says what denial forecloses, not merely that it is permanent', () => {
    expect(DENY_IS_FINAL).toContain('final');
    expect(DENY_IS_FINAL).toMatch(/cannot be revised/);
    expect(DENY_IS_FINAL).toMatch(/raise it again/);
  });
});

describe('signingClosed — the defect Brian hit in the deployed build', () => {
  const LIVE = Date.parse('2026-09-10T13:10:00Z');
  const AFTER = Date.parse('2027-01-01T00:00:00Z');

  it('closes signing on a record whose window has lapsed while still `pending`', () => {
    // THE EXACT LIVE CASE. The service had not swept the record, so it arrived `pending` with
    // `callerMaySign: true` and unfilled slots — every signal the card keyed on said "signable"
    // while the countdown three lines above said "signature window closed — DENIED".
    const lapsed = byAction('account.balance.adjust');
    expect(lapsed.status).toBe('pending');
    const closure = signingClosed(lapsed, AFTER);
    expect(closure).not.toBeNull();
    expect(closure!.kind).toBe('expired');
    expect(closure!.header).not.toMatch(/signature required/i);
    expect(closure!.note).toContain('Nothing was executed');
  });

  it('leaves a live pending record open — it must narrow, never block signing outright', () => {
    approvals
      .filter((a) => a.status === 'pending' && a.signatureSlots.some((s) => !s.filled))
      .forEach((a) => expect(signingClosed(a, LIVE)).toBeNull());
  });

  it('tells a different story for signed than for denied', () => {
    const signed = approvals.find((a) => a.status === 'signed');
    const denied = approvals.find((a) => a.status === 'denied');
    expect(signed && denied).toBeTruthy();
    expect(signingClosed(signed!, LIVE)!.kind).toBe('signed');
    expect(signingClosed(denied!, LIVE)!.kind).toBe('denied');
    expect(signingClosed(signed!, LIVE)!.header).not.toEqual(
      signingClosed(denied!, LIVE)!.header
    );
  });

  it('never says a closed record needs something from the reader', () => {
    approvals.forEach((a) => {
      const closure = signingClosed(a, AFTER);
      expect(closure).not.toBeNull();
      expect(closure!.note).not.toMatch(/once you sign|only signature needed|you sign/i);
    });
  });
});

describe('signingAttestation on a closed record', () => {
  const AFTER = Date.parse('2027-01-01T00:00:00Z');

  it('says nothing at all — this is the sentence Brian was shown on a dead approval', () => {
    // Pre-fix this returned "Yours is the only signature needed — this goes ahead once you
    // sign." for a lapsed single-slot L1, because it counted SLOTS and never looked at time.
    const lapsedL1 = approvals.find(
      (a) => a.signatureSlots.length === 1 && a.signatureSlots.every((s) => !s.filled)
    );
    expect(lapsedL1).toBeDefined();
    expect(signingAttestation(lapsedL1!, 'banker', AFTER)).toBe('');
  });

  it('still speaks for a record that is genuinely open', () => {
    const live = approvals.find(
      (a) => a.status === 'pending' && a.callerMaySign && a.signatureSlots.some((s) => !s.filled)
    );
    expect(signingAttestation(live!, 'banker', Date.parse('2026-09-10T13:10:00Z'))).not.toBe('');
  });
});
