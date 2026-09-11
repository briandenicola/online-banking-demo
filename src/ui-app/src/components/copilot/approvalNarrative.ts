/**
 * The approval card's narrative layer — Danny's IA spec (`.squad/decisions.md`, "Approval card:
 * information architecture spec"), §7 steps 1 and 3.
 *
 * GOVERNING RULE, from §1 of that spec: the one line Brian did not complain about was the
 * human-written reason — *"Lockout was caused by a stale saved password on the customer's
 * phone."* Concrete, situational, about a person. Every sentence here is judged against it:
 * **would a banker say this to a colleague?** If not, it is engine vocabulary and belongs in
 * the collapsed "how this was decided" region, not on the primary surface.
 *
 * WHY THESE ARE PURE FUNCTIONS
 * ----------------------------
 * They are the part of the card most likely to be wrong in a way that renders fine — a
 * plausible sentence about the wrong account is worse than no sentence. Keeping them pure
 * makes each case assertable without a DOM.
 *
 * WHAT THIS DELIBERATELY DOES NOT DO
 * ----------------------------------
 * It does not invent a customer. §6.1 subject enrichment is Turk's and is not available; §7
 * is explicit that step 1 without it is honest and achievable, but that printing the GUID and
 * calling it done is not. So where the card cannot say who the customer is, it says exactly
 * that — see `subjectAbsence`. Nothing here reads or contributes to the hashed payload.
 */
import { Approval, PayloadField } from './types';

/** `flattenPayload` keys rows on `path`, not `key` — a `.key` lookup silently returns
 *  undefined for every field and every sentence degrades to its fallback. */
function field(approval: Approval, key: string): PayloadField | undefined {
  return approval.payload.find((f) => f.path === key);
}

function raw(approval: Approval, key: string): unknown {
  return field(approval, key)?.value;
}

function money(value: unknown): string | null {
  const n = typeof value === 'string' ? Number(value) : typeof value === 'number' ? value : NaN;
  if (!Number.isFinite(n)) return null;
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD' });
}

/**
 * §3.1 — the ask, in one sentence, verb-first.
 *
 * Falls back to `actionLabel` for any action this map does not know. That fallback is the
 * whole safety property: an unknown action degrades to today's wording rather than to a
 * confident sentence about the wrong thing.
 */
export function approvalHeadline(approval: Approval): string {
  switch (approval.actionId) {
    case 'account.balance.adjust': {
      const amount = money(raw(approval, 'amount'));
      const direction = String(raw(approval, 'direction') ?? '').toLowerCase();
      if (!amount) return approval.actionLabel;
      if (direction === 'debit') return `Take ${amount} off a customer's account`;
      if (direction === 'credit') return `Put ${amount} back into a customer's account`;
      return `Adjust a customer's account by ${amount}`;
    }
    case 'user.unlock':
      return "Let a customer back into their account";
    case 'transaction.score.override': {
      const score = raw(approval, 'newScore');
      const value = typeof score === 'string' || typeof score === 'number' ? String(score) : null;
      return value
        ? `Overrule the fraud score on one transaction, setting it to ${value}`
        : 'Overrule the fraud score on one transaction';
    }
    default:
      return approval.actionLabel;
  }
}

/**
 * §3.2, honest-absence form.
 *
 * The card cannot name the customer until §6.1 lands, and Danny called the raw GUID the most
 * damaging item on the card because it makes it unusable rather than merely irritating: a
 * banker cannot judge an unlock without knowing whose account it is. Saying so plainly is a
 * true statement a banker can act on — they know to go and look. A GUID presented as if it
 * were an answer is not.
 *
 * Returns null when there is no customer-ish identifier in play, so the line never appears on
 * an approval it does not describe.
 */
export function subjectAbsence(approval: Approval): string | null {
  const hasSubject =
    raw(approval, 'accountId') !== undefined ||
    raw(approval, 'userId') !== undefined ||
    raw(approval, 'transactionId') !== undefined;
  if (!hasSubject) return null;

  return (
    'This card cannot yet tell you which customer this is — only an internal id, shown below ' +
    'in what you are signing. Check the customer in the account record before you sign.'
  );
}

/**
 * §3.7 / §6.4 — why this needs two people, in consequence terms.
 *
 * The base-rung case fires no escalator, so there is no `reasonTemplate` to render and the
 * card fell back to *"Base rung for 'Post a balance adjustment'. No escalators fired."* — a
 * faithful description of a code path that a banker has no use for. Danny assigned the map
 * explicitly to the client: no backend work.
 *
 * Deliberately keyed on action id and rung TOGETHER: the same action at a different rung is a
 * different sentence, and a map keyed on action alone would confidently say "always needs two"
 * about a single-signer approval.
 */
export function whyThisRung(actionId: string, rung: string): string | null {
  if (rung === 'L2') {
    switch (actionId) {
      case 'account.balance.adjust':
        return 'Moving money on a customer’s account always needs two people — the second signature is the check that the figure and the reason match.';
      case 'user.unlock':
        return 'Account unlocks always need two people, because restoring access is the step that would let someone in.';
      case 'transaction.score.override':
        return 'Overruling the fraud score always needs two people — it turns off the check that would otherwise stop this payment.';
      default:
        return 'This action always needs two people. A second signer has to agree before anything happens.';
    }
  }

  if (rung === 'L1') {
    switch (actionId) {
      case 'account.balance.adjust':
        return 'One signature is enough for an adjustment this size, but it is yours alone — nobody else checks it.';
      case 'user.unlock':
        return 'One signature is enough to unlock an account, but it is yours alone — nobody else checks it.';
      default:
        return 'One signature is enough here, but it is yours alone — nobody else checks it.';
    }
  }

  return null;
}

/**
 * §3.8 — what happens if you do nothing.
 *
 * `expires in 46:05 → DENIED` reads as a countdown to failure with no guidance. Auto-denial is
 * a deliberate design property (`config/authority-policy.yaml`: *"Expiry is a denial, never an
 * auto-approval"*), so the card should say so with confidence, state the outcome for the
 * CUSTOMER, and give a wall-clock time as well as a relative one.
 */
export function expiryConsequence(approval: Approval, now: number = Date.now()): string | null {
  const expires = new Date(approval.expiresAt);
  if (Number.isNaN(expires.getTime())) return null;

  // Caught in a real browser, not in a unit test: against expired fixtures the card read
  // "If nobody signs by 4:06 PM, this is automatically denied" on an approval whose window had
  // ALREADY closed. A forecast stated in the future tense about something that has already
  // happened is worse than silence — the countdown chip already says the window is closed.
  if (expires.getTime() <= now) return null;
  const clock = expires.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  const outcome =
    approval.actionId === 'user.unlock'
      ? 'and the customer stays locked out'
      : 'and nothing happens to the account';
  return `If nobody signs by ${clock}, this is automatically denied ${outcome}. Nothing will execute.`;
}

/**
 * Priority 3 / companion ruling §0a — Deny is permanent.
 *
 * Brian burned three approvals discovering this behaviour by doing it. The warning has to land
 * BEFORE the click, not as a confirmation after it, and it has to say what is foreclosed: a
 * denied request cannot be revised or re-raised from this card.
 */
export const DENY_IS_FINAL =
  'Denying is final. It closes this request for good — it cannot be revised, re-opened or ' +
  'signed later, and anyone who still wants this done has to raise it again from scratch.';

/**
 * Whether this record can still receive a signature — and if not, why not.
 *
 * THE DEFECT THIS EXISTS TO KILL. Brian selected a record whose signing window had closed and
 * the card told him *"Yours is the only signature needed — this goes ahead once you sign."*
 * The card was confidently wrong about authority, which is the one thing this product exists
 * to be right about.
 *
 * Root cause: the card's `terminal` flag keyed on STATUS alone (`denied || executed`), and
 * expiry is not a status. The service had not yet swept the record, so it was still `pending`
 * with `callerMaySign: true` while its window had already closed — the countdown was rendering
 * "signature window closed — DENIED" three lines above an invitation to sign.
 *
 * `signed` was missing for the same reason: it is terminal for SIGNING (every slot is filled)
 * while remaining non-terminal for execution.
 *
 * This never grants anything. It is a pure narrowing of what the card offers, so it cannot
 * weaken the gate — `callerMaySign` and `canSignUnderStream` remain authoritative for the
 * positive case. Where this disagrees with the service, it closes signing, never opens it.
 */
export type SigningClosure = {
  kind: 'expired' | 'signed' | 'denied' | 'executed';
  /** Replaces "SIGNATURE REQUIRED". A signed record and a lapsed one are different stories. */
  header: string;
  /** The outcome, and whether anything happened. Answers "did something half-execute?" */
  note: string;
};

export function signingClosed(approval: Approval, now: number = Date.now()): SigningClosure | null {
  if (approval.status === 'denied') {
    return {
      kind: 'denied',
      header: 'DENIED — NO SIGNATURE POSSIBLE',
      note: 'This request was denied. Nothing was executed and no signature can be added to it.',
    };
  }

  if (approval.status === 'executed') {
    return {
      kind: 'executed',
      header: 'ALREADY CARRIED OUT',
      note: 'This was signed and has already been carried out. Nothing further is needed.',
    };
  }

  if (approval.status === 'signed' || approval.signatureSlots.every((slot) => slot.filled)) {
    const signers = approval.signatureSlots
      .filter((slot) => slot.filled && slot.signedByUsername)
      .map((slot) => slot.signedByUsername as string);
    const who = signers.length > 0 ? ` Signed by ${signers.join(' and ')}.` : '';
    return {
      kind: 'signed',
      header: 'FULLY SIGNED — NOTHING NEEDED FROM YOU',
      note: `Every signature this needed is in.${who} It is now waiting to be carried out.`,
    };
  }

  const expires = new Date(approval.expiresAt);
  if (!Number.isNaN(expires.getTime()) && expires.getTime() <= now) {
    const clock = expires.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    return {
      kind: 'expired',
      header: 'SIGNATURE WINDOW CLOSED',
      note:
        `Nobody signed before ${clock}, so this was denied automatically. Nothing was ` +
        'executed, and it can no longer be signed — it would have to be raised again.',
    };
  }

  return null;
}
