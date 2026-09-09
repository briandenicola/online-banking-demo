/**
 * The ONE place a supervisor/primary verdict becomes a label, a colour and a rank.
 *
 * Why this file exists: the verdict crossed four hops (model -> SecondOpinion ->
 * wire adapter -> chip) and MEANT SOMETHING DIFFERENT at each end. The shipped
 * mapping rendered `decline` — the strongest objection a supervisor can make —
 * as "CONDITIONAL", the mildest label available, and rendered `hold` — "resolve
 * something first" — as "DECLINE". A supervisor that flatly refused an action
 * read on screen as having merely attached a condition. That is not a cosmetic
 * bug: check 4.2 asks whether the supervisor ever genuinely disagrees, and it is
 * answered by looking at this chip.
 *
 * Two invented labels are deleted rather than reassigned:
 *   - "APPROVE"     — no server verdict maps to it, and ApprovalCard's own rule
 *                     is that the word "Approve" is reserved for a thing agents
 *                     may never do. An agent PROPOSES; it does not approve.
 *   - "CONDITIONAL" — no server verdict maps to it either. It was the *default*
 *                     arm of the adapter, which is how `decline` and "the model
 *                     returned gibberish" arrived on screen as the same amber
 *                     chip. A fallback that is indistinguishable from a real
 *                     verdict is how this bug class survives.
 *
 * The vocabulary below is the server's, verbatim and complete:
 *   `banker-copilot-service/app/planner/verdicts.py::RECOMMENDATIONS`
 *   = ("proceed", "hold", "decline")
 * If the server can emit a token this file has no case for, that token renders
 * loudly as unrecognised — never as the mildest verdict, and never silently.
 *
 * It lived in `supervisor_model.py` until the primary agent gained a real
 * assessment and a SECOND agent started stating verdicts; it then moved to a
 * neutral home. This comment cited the old path for exactly as long as it took
 * somebody to notice, which is the argument for
 * `__tests__/verdictVocabulary.contract.test.ts`: a comment cannot go stale in a
 * way a suite notices, so the list is now pinned against the real Python.
 *
 * Both agents key on this file. The names `SERVER_VERDICTS` and
 * `verdictPresentation` are deliberately not supervisor-specific — there is ONE
 * vocabulary, and a per-agent presentation table would be the translation table
 * that caused the original defect, wearing a plural.
 */

/** The server's verdict vocabulary, in ASCENDING order of objection. */
export const SERVER_VERDICTS = ['proceed', 'hold', 'decline'] as const;

export type ServerVerdict = (typeof SERVER_VERDICTS)[number];

/** MUI chip palette keys. Narrowed so a typo cannot ship a silent default colour. */
export type VerdictColor = 'success' | 'warning' | 'error';

export interface VerdictPresentation {
  /** False when the string is missing, empty, or not in the server vocabulary. */
  known: boolean;
  /** The normalised server token, or null when unrecognised/absent. */
  verdict: ServerVerdict | null;
  /** The visible chip text. */
  label: string;
  color: VerdictColor;
  /**
   * Objection strength, ascending. Anything unrecognised sorts ABOVE `decline`
   * so a "worst first" ordering surfaces a broken pipe rather than burying it
   * under real verdicts. It is never the mildest rank.
   */
  severity: number;
  /** Outlined marks the two non-verdicts apart from `decline`, which shares its colour. */
  variant: 'filled' | 'outlined';
  /** Tooltip / screen-reader text. Severity is never carried by colour alone. */
  description: string;
}

const PRESENTATION: Record<ServerVerdict, Omit<VerdictPresentation, 'known' | 'verdict'>> = {
  proceed: {
    label: 'PROCEED',
    color: 'success',
    severity: 0,
    variant: 'filled',
    description: 'Proceed — taking this action is defensible on the evidence gathered.',
  },
  hold: {
    label: 'HOLD',
    color: 'warning',
    severity: 1,
    variant: 'filled',
    description:
      'Hold — the evidence is insufficient, or something must be resolved before this action.',
  },
  decline: {
    label: 'DECLINE',
    color: 'error',
    severity: 2,
    variant: 'filled',
    description: 'Decline — the evidence argues against taking this action.',
  },
};

/** Rank given to anything that is not a verdict. Must stay above every real verdict. */
export const UNRECOGNISED_SEVERITY = 3;

const MISSING: VerdictPresentation = {
  known: false,
  verdict: null,
  label: 'NO VERDICT',
  color: 'error',
  severity: UNRECOGNISED_SEVERITY,
  variant: 'outlined',
  description:
    'No verdict reached this screen. An absent opinion is not an approval — treat it as a broken pipeline, not as consent.',
};

/**
 * Case- and whitespace-insensitive because the token crosses a language boundary
 * and has already been re-cased once on the way. Nothing else is tolerated: a
 * near-miss is a drift signal, and quietly repairing it is how a verdict comes to
 * mean something different at each end of the wire.
 */
export function normaliseVerdict(raw: string | null | undefined): ServerVerdict | null {
  if (typeof raw !== 'string') return null;
  const token = raw.trim().toLowerCase();
  return (SERVER_VERDICTS as readonly string[]).includes(token) ? (token as ServerVerdict) : null;
}

export function verdictPresentation(raw: string | null | undefined): VerdictPresentation {
  if (typeof raw !== 'string' || raw.trim() === '') return MISSING;

  const verdict = normaliseVerdict(raw);
  if (verdict === null) {
    return {
      known: false,
      verdict: null,
      label: 'UNRECOGNISED VERDICT',
      color: 'error',
      severity: UNRECOGNISED_SEVERITY,
      variant: 'outlined',
      description: `"${raw.trim()}" is not one of ${SERVER_VERDICTS.join(', ')}. A token that is not a verdict must never be read as permission.`,
    };
  }

  return { known: true, verdict, ...PRESENTATION[verdict] };
}
