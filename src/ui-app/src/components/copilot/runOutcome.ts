/**
 * Two run outcomes that could not occur before the free-text planner landed:
 * a read-only ANSWER with no approval, and a named REFUSAL.
 *
 * Both exist because of the defect Brian cared most about: typing an objective
 * produced one step, 320ms and an empty evidence bundle, and the run reported
 * itself completed. Turk's design states the structural invariant — no case may
 * complete as a successful empty evidence bundle. This module is the visual half
 * of that invariant. A refused run must not render as a completed run that
 * merely happens to be empty, because that is exactly what Brian saw and
 * correctly disbelieved.
 *
 * The register to match is the card's existing `NO VERDICT` block: concrete,
 * specific, honest about limits. A refusal that says "something went wrong" is
 * the same failure as an empty bundle wearing better clothes.
 */

import { Artifact } from './types';

/**
 * DISCLOSURE CONSTRAINT — read before adding a code.
 *
 * `ambiguous_subject` and `subject_not_found` must never reveal which records
 * exist or were matched: not names, not ids, not COUNTS, and not in a tooltip or
 * the raw view. Danny's ruling is that a refusal naming its candidates turns the
 * error channel into the customer-search API we deliberately declined to build,
 * and a count alone still answers "does a customer like this exist?".
 *
 * The planner is already careful here — on both paths it returns the evidence
 * accumulated SO FAR, and candidate matches are only ever written to evidence
 * after a unique match. The lookup runs through a direct executor call rather
 * than a traced tool step, so no `tool.result` frame carries the candidate list
 * either. That makes non-disclosure a property of the whole pipeline rather than
 * of this copy alone — but this file must not be the place that reintroduces it.
 */
const NON_DISCLOSING = new Set(['ambiguous_subject', 'subject_not_found']);

export interface RefusalCopy {
  /** Banker-readable headline. Never the raw code. */
  title: string;
  /** What the run actually did and did not do. */
  what: string;
  /** What the banker can do next. Empty when there is honestly nothing. */
  next: string;
  /**
   * Whether the server's own message may be shown.
   *
   * True for the ten named codes: Turk writes them for a banker and they are
   * non-disclosing by construction. False for anything unrecognised, because
   * the planner's catch-all emits `str(exc)` as its message and a Python
   * exception string is not something to put in front of someone about to move
   * money — it is also the one message not vetted for disclosure.
   */
  showServerMessage: boolean;
  /**
   * Whether any read was performed before refusing. Stated because "nothing was
   * read" is a reassuring, checkable claim — L3RefusalCard already makes it —
   * and claiming it falsely on a path that DID read would be worse than silence.
   */
  readsPerformed: 'none' | 'some';
}

const REFUSALS: Record<string, RefusalCopy> = {
  planner_model_unavailable: {
    title: 'The reasoning model could not be reached',
    what: 'No plan was formed, no records were read and nothing was proposed. This is a fault in the environment, not a judgement about your objective.',
    next: 'Retry. If it keeps happening the model configuration needs an operator — the Copilot will not fall back to a canned answer.',
    showServerMessage: true,
    readsPerformed: 'none',
  },
  intent_contract_invalid: {
    title: 'The model\u2019s reply did not fit the required contract',
    what: 'The reply was discarded rather than repaired, so nothing was read and nothing was proposed.',
    next: 'Retry, or restate the objective more plainly.',
    showServerMessage: true,
    readsPerformed: 'none',
  },
  objective_unmappable: {
    title: 'This objective did not map to anything the Copilot can do',
    what: 'It was understood as banking language but matched no safe read and no action the agent may propose. Nothing was read and nothing was proposed.',
    next: 'Restate it naming the customer, the account and the change you want.',
    showServerMessage: true,
    readsPerformed: 'none',
  },
  forbidden_action: {
    title: 'That action is outside the Copilot harness',
    what: 'The objective maps to a real action, but one the agent may never propose. No plan was formed and no tools were called.',
    next: 'Handle it through Classic Admin or the break-glass process, where it is recorded against your own identity.',
    showServerMessage: true,
    readsPerformed: 'none',
  },
  ambiguous_subject: {
    title: 'The subject of this objective was not unique',
    what: 'More than one record matched the reference, so nothing was selected. The Copilot will not pick one on your behalf.',
    next: 'Identify the subject exactly — a full username or an account number.',
    showServerMessage: true,
    readsPerformed: 'some',
  },
  subject_not_found: {
    title: 'The subject of this objective could not be resolved',
    what: 'Nothing matched the reference for this banker, so no plan was formed against it.',
    next: 'Check the identifier and try again.',
    showServerMessage: true,
    readsPerformed: 'some',
  },
  payload_unfillable: {
    title: 'The action is permitted, but the details are incomplete',
    what: 'A required field could not be constructed from the objective and the evidence, and the Copilot will not guess it. Nothing was proposed.',
    next: 'State the missing detail explicitly — typically the direction (credit or debit) or the amount.',
    showServerMessage: true,
    readsPerformed: 'some',
  },
  payload_invalid: {
    title: 'A value failed validation before anything was proposed',
    what: 'The payload was checked against the policy\u2019s money scale and field rules and did not pass. No proposal was created.',
    next: 'Restate the value in a plain form, such as 35.00 rather than a rounded or formatted figure.',
    showServerMessage: true,
    readsPerformed: 'some',
  },
  evidence_unavailable: {
    title: 'The required evidence could not be gathered',
    what: 'A read the policy requires for this action failed or came back incomplete. No assessment was made and nothing was proposed on partial evidence.',
    next: 'Retry. If the read keeps failing the underlying service needs attention.',
    showServerMessage: true,
    readsPerformed: 'some',
  },
  proposal_refused_by_authority: {
    title: 'The authority service refused the proposal',
    what: 'Evidence was gathered and a proposal was constructed, but authority rejected it. Its reason is preserved exactly as given, not reinterpreted.',
    next: 'Read the reason below. If it names a policy constraint, that constraint is the answer.',
    showServerMessage: true,
    readsPerformed: 'some',
  },
};

/**
 * Copy for a refusal code.
 *
 * An unrecognised code is NOT coerced into the nearest known one. It reports the
 * code verbatim so the trace stays diagnosable, and suppresses the server
 * message, which on the catch-all path is a raw exception string.
 */
export function refusalCopy(code: string | undefined): RefusalCopy {
  if (code && REFUSALS[code]) return REFUSALS[code];
  return {
    title: 'The run stopped without producing a result',
    what: `It ended on an unrecognised condition${code ? ` (${code})` : ''}. Nothing was signed and nothing was executed.`,
    next: 'Retry. If it recurs, quote the code above — the details are in the raw trace.',
    showServerMessage: false,
    readsPerformed: 'some',
  };
}

/** True when a code must not have candidate detail rendered beside it. */
export function isNonDisclosing(code: string | undefined): boolean {
  return code !== undefined && NON_DISCLOSING.has(code);
}

export interface AnswerContent {
  answer: string;
  keyPoints: string[];
  citedEvidenceIds: string[];
  unverified: string[];
}

/**
 * Reads the read-only answer artifact.
 *
 * Detected by SHAPE, not by `kind`, matching the deliberate choice already made
 * in `ArtifactBody`: keying a renderer off the kind means a new kind renders as
 * raw JSON in front of someone about to sign against it. An artifact qualifies
 * when it carries a non-empty `answer` string; the three list fields are
 * normalised to arrays of strings and are each optional, so a thin answer
 * degrades to a paragraph rather than to a JSON dump.
 */
export function answerContent(artifact: Artifact | undefined): AnswerContent | undefined {
  const content = artifact?.content;
  if (!content || typeof content !== 'object' || Array.isArray(content)) return undefined;
  const record = content as Record<string, unknown>;
  const answer = record.answer;
  if (typeof answer !== 'string' || answer.trim() === '') return undefined;
  return {
    answer,
    keyPoints: stringList(record.keyPoints),
    citedEvidenceIds: stringList(record.citedEvidenceIds),
    unverified: stringList(record.unverified),
  };
}

function stringList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((v): v is string => typeof v === 'string' && v.trim() !== '');
}
