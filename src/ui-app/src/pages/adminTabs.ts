/**
 * Classic Admin tab identity, visibility, and selection resolution.
 *
 * Extracted from AdminPage so the visibility rules are pure functions that can
 * be tamper-tested one condition at a time, the same way approvalPolicy.ts
 * holds the batch rules.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 *  Tabs are addressed by IDENTITY (`regionId`), never by array position.
 *
 *  The page used to render its panels with `activeTab === 0 && <Applications/>`
 *  and friends, which is correct only while every caller sees the same eight
 *  tabs in the same order. The moment the list is FILTERED — as it now is for a
 *  supervisor — position 1 stops meaning "User Management" and starts meaning
 *  whatever survived the filter, so a positional renderer would show a
 *  restricted panel to the very caller the filter exists to keep out. That is
 *  not a cosmetic bug: it is the filter doing the opposite of its job, silently.
 *
 *  So `regionId` is the key for selection, for rendering, and for the
 *  comparison instrumentation. The IDs themselves are frozen — Phase 5 counts
 *  context switches by `data-comparison-region`, and renaming or renumbering
 *  one would silently rebase the measurement.
 * ─────────────────────────────────────────────────────────────────────────────
 */

export type AdminTabId =
  | 'admin-applications'
  | 'admin-users'
  | 'admin-transactions'
  | 'admin-flagged'
  | 'admin-prompt'
  | 'admin-eval'
  | 'admin-audit'
  | 'admin-health';

export interface AdminTabDefinition {
  label: string;
  /**
   * Stable tab identity, and the `data-comparison-region` value. FROZEN — see
   * the header note. Do not rename, do not renumber, do not reorder for effect.
   */
  regionId: AdminTabId;
  /**
   * True when the tab only OBSERVES: it reads state and offers no control that
   * changes anyone's authority, money, or account.
   *
   * This is the axis a supervisor is admitted on. It is a property of the TAB
   * (what it can do), not of the viewer (who they are), so adding a write
   * control to a tab marked `true` is a change a reviewer can see in one line.
   *
   * `false` for User Management above all: it carries promote and delete, which
   * are the L3 platform actions admin exists to hold alone.
   */
  readOnlyObservability: boolean;
}

export const ADMIN_TABS: AdminTabDefinition[] = [
  { label: 'Account Applications', regionId: 'admin-applications', readOnlyObservability: false },
  { label: 'User Management', regionId: 'admin-users', readOnlyObservability: false },
  { label: 'All Transactions', regionId: 'admin-transactions', readOnlyObservability: true },
  { label: 'Flagged Transactions', regionId: 'admin-flagged', readOnlyObservability: true },
  { label: 'Chatbot Prompt', regionId: 'admin-prompt', readOnlyObservability: false },
  { label: 'AI Evaluation', regionId: 'admin-eval', readOnlyObservability: true },
  { label: 'Login Audit', regionId: 'admin-audit', readOnlyObservability: true },
  { label: 'System Health', regionId: 'admin-health', readOnlyObservability: true },
];

export interface AdminTabViewer {
  /** Declared-role admin. The only thing that unlocks the write tabs. */
  isAdmin: boolean;
  /** Server-mirrored capability: may view the read-only observability tabs. */
  mayViewAdminObservability: boolean;
}

/**
 * The tabs this viewer may see.
 *
 * Every branch is a POSITIVE assertion, so an unrecognised viewer — a partial
 * context, a renamed field, a future role — yields an EMPTY list rather than
 * the full one. A missing capability is never consent.
 */
export function visibleAdminTabs(viewer: AdminTabViewer): AdminTabDefinition[] {
  if (viewer.isAdmin === true) {
    return ADMIN_TABS;
  }
  if (viewer.mayViewAdminObservability === true) {
    return ADMIN_TABS.filter((tab) => tab.readOnlyObservability === true);
  }
  return [];
}

export type AdminTabResolution =
  /** Render this tab's panel. */
  | { kind: 'render'; tab: AdminTabDefinition }
  /** A real tab, but not one this viewer may see. Explain; do not blank out. */
  | { kind: 'restricted'; tab: AdminTabDefinition }
  /** This viewer has no admin surface at all. */
  | { kind: 'none' };

/**
 * Resolves the selected tab against what the viewer may actually see.
 *
 * Re-filters defensively rather than trusting the selection, for the same
 * reason BatchApprovalCard re-filters its group: the selection is state, and
 * state can arrive from somewhere the tab strip did not draw.
 */
export function resolveAdminTab(
  requestedId: AdminTabId | undefined,
  visible: AdminTabDefinition[]
): AdminTabResolution {
  const permitted = visible.find((tab) => tab.regionId === requestedId);
  if (permitted) {
    return { kind: 'render', tab: permitted };
  }

  // Known tab, deliberately withheld from this viewer. Distinguish it from
  // "nothing here" so the page can say which, and say why.
  const withheld = ADMIN_TABS.find((tab) => tab.regionId === requestedId);
  if (withheld) {
    return { kind: 'restricted', tab: withheld };
  }

  return visible.length > 0 ? { kind: 'render', tab: visible[0] } : { kind: 'none' };
}
