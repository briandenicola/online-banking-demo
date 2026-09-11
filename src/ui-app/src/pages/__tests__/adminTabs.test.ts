/**
 * Admin tab visibility rules.
 *
 * These are the rules that decide whether a supervisor can see User Management.
 * Each is pinned by a test that fails for ITS OWN reason — a guard proven only
 * in aggregate is a guard that erodes silently (see the epic-wide finding on
 * `isBatchEligible`, where four conditions shared one passing suite).
 */
import {
  ADMIN_TABS,
  AdminTabDefinition,
  resolveAdminTab,
  visibleAdminTabs,
} from '../adminTabs';

const ADMIN = { isAdmin: true, mayViewAdminObservability: true };
const SUPERVISOR = { isAdmin: false, mayViewAdminObservability: true };
const BANKER = { isAdmin: false, mayViewAdminObservability: false };

const ids = (tabs: AdminTabDefinition[]) => tabs.map((t) => t.regionId);

describe('visibleAdminTabs', () => {
  it('gives an admin every tab, unfiltered', () => {
    expect(ids(visibleAdminTabs(ADMIN))).toEqual(ids(ADMIN_TABS));
    expect(visibleAdminTabs(ADMIN)).toHaveLength(8);
  });

  it('gives a supervisor the five read-only observability tabs', () => {
    expect(ids(visibleAdminTabs(SUPERVISOR)).sort()).toEqual(
      [
        'admin-audit',
        'admin-eval',
        'admin-flagged',
        'admin-health',
        'admin-transactions',
      ].sort()
    );
  });

  /**
   * THE test. A supervisor who could reach User Management could promote
   * themselves to admin (`user.role.promote` is an L3 platform action), and
   * from there rewrite the policy governing their own co-signature. The demo's
   * entire separation-of-duties story rests on this one assertion.
   */
  it('never gives a supervisor User Management', () => {
    expect(ids(visibleAdminTabs(SUPERVISOR))).not.toContain('admin-users');
  });

  it('never gives a supervisor the other write tabs either', () => {
    const visible = ids(visibleAdminTabs(SUPERVISOR));
    expect(visible).not.toContain('admin-prompt');
    expect(visible).not.toContain('admin-applications');
  });

  it('gives a plain banker no admin surface at all', () => {
    expect(visibleAdminTabs(BANKER)).toEqual([]);
  });

  /**
   * Fail-closed pin. Written with `delete` rather than `= undefined` so it
   * survives a fixture-builder refactor, and cast at the boundary because the
   * wire (and a stale AuthContext) is not bound by our TypeScript. An absent
   * capability field must never read as permission.
   */
  it('treats an absent capability as no access, not full access', () => {
    const noCapability: Record<string, unknown> = { ...SUPERVISOR };
    delete noCapability.mayViewAdminObservability;
    delete noCapability.isAdmin;

    expect(
      visibleAdminTabs(noCapability as unknown as typeof SUPERVISOR)
    ).toEqual([]);
  });

  it('marks User Management as a write tab, not observability', () => {
    // Pins the DATA, not just the filter: flipping this flag would open the tab
    // without touching a line of gate logic.
    const users = ADMIN_TABS.find((t) => t.regionId === 'admin-users');
    expect(users?.readOnlyObservability).toBe(false);
  });
});

describe('ADMIN_TABS region identity', () => {
  it('keeps the eight frozen regionIds used by the Phase 5 comparison', () => {
    // Renaming or dropping one of these silently rebases the context-switch
    // count that Classic Admin is measured by.
    expect(ids(ADMIN_TABS)).toEqual([
      'admin-applications',
      'admin-users',
      'admin-transactions',
      'admin-flagged',
      'admin-prompt',
      'admin-eval',
      'admin-audit',
      'admin-health',
    ]);
  });
});

describe('resolveAdminTab', () => {
  const supervisorTabs = visibleAdminTabs(SUPERVISOR);

  it('renders a tab the viewer may see', () => {
    const r = resolveAdminTab('admin-audit', supervisorTabs);
    expect(r.kind).toBe('render');
    expect(r.kind === 'render' && r.tab.regionId).toBe('admin-audit');
  });

  /**
   * The positional-indexing hazard, pinned.
   *
   * A supervisor's visible list is [transactions, flagged, eval, audit, health].
   * Under the old positional renderer, selecting index 1 rendered
   * `AdminUserManagementTab` — the filter would have handed the restricted panel
   * to exactly the caller it exists to exclude. Identity resolution cannot do
   * that: position 1 of the supervisor list IS Flagged Transactions and nothing
   * else.
   */
  it('resolves by identity, so a filtered list never shifts a panel into place', () => {
    const secondVisible = supervisorTabs[1];
    expect(secondVisible.regionId).toBe('admin-flagged');

    // The tab that sits at index 1 of the UNFILTERED list is the dangerous one.
    expect(ADMIN_TABS[1].regionId).toBe('admin-users');

    const r = resolveAdminTab(secondVisible.regionId, supervisorTabs);
    expect(r.kind === 'render' && r.tab.regionId).toBe('admin-flagged');
  });

  it('explains rather than renders when a withheld tab is selected', () => {
    // State can arrive from somewhere the tab strip did not draw.
    const r = resolveAdminTab('admin-users', supervisorTabs);
    expect(r.kind).toBe('restricted');
    expect(r.kind === 'restricted' && r.tab.label).toBe('User Management');
  });

  it('falls back to the first PERMITTED tab for an unknown selection', () => {
    const r = resolveAdminTab(undefined, supervisorTabs);
    expect(r.kind === 'render' && r.tab.regionId).toBe('admin-transactions');
  });

  it('reports no surface when the viewer may see nothing', () => {
    expect(resolveAdminTab('admin-users', []).kind).toBe('restricted');
    expect(resolveAdminTab(undefined, []).kind).toBe('none');
  });
});
