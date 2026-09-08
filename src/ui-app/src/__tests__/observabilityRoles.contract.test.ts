/**
 * Contract: the UI's admin-observability allow-list must equal the server's.
 *
 * Two documents, two languages, and nothing but this test comparing them:
 *
 *   client  ADMIN_OBSERVABILITY_ROLES  (contexts/AuthContext.tsx)
 *   server  BankingRoles.ObservabilityRead  (src/shared/Auth/BankingRoles.cs)
 *
 * This was deferred while the server constant was still moving. It is written
 * now to the rule Danny set on the neighbouring seam: a cross-language check
 * must READ THE REAL OTHER SIDE, never a restatement of it. Hard-coding
 * "admin,Admin,supervisor,Supervisor" here would hold two documents together
 * with a third that can drift from both — and would pass forever after the
 * server dropped a role, which is the only failure it exists to catch.
 *
 * So the C# source is parsed from disk, exactly as `harnessRole.contract.test.ts`
 * parses `auth.py`.
 *
 * What drift looks like if this is absent, in both directions:
 *   - server GAINS a role the client lacks → the tab is served but never shown;
 *     the grant looks broken and gets "fixed" by widening the client to admin.
 *   - client GAINS a role the server lacks → the tab is offered, the fetch 403s,
 *     and the user sees an empty panel rather than a refusal.
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { ADMIN_OBSERVABILITY_ROLES } from '../contexts/AuthContext';

const BANKING_ROLES_CS = join(__dirname, '..', '..', '..', 'shared', 'Auth', 'BankingRoles.cs');

/** Pull one `public const string <name> = "...";` out of the real C# source. */
function csharpRoleConstant(source: string, name: string): string[] {
  const match = source.match(
    new RegExp(`public\\s+const\\s+string\\s+${name}\\s*=\\s*"([^"]*)"\\s*;`)
  );
  // A missing constant means the server was refactored. Fail loudly — a contract
  // test that quietly finds nothing to compare is worse than no test at all.
  expect(match).not.toBeNull();
  return match![1].split(',').map((role) => role.trim()).filter(Boolean);
}

function distinctLowerCase(roles: string[]): string[] {
  return Array.from(new Set(roles.map((role) => role.toLowerCase()))).sort();
}

describe('admin observability role contract', () => {
  const source = readFileSync(BANKING_ROLES_CS, 'utf8');

  it('reads a non-empty ObservabilityRead from the real C# source (anti-vacuous guard)', () => {
    // Proves the haystack exists BEFORE asserting anything about the needle. If the
    // file moved or the regex rotted, every assertion below would otherwise pass on
    // an empty list compared against an empty list.
    const roles = csharpRoleConstant(source, 'ObservabilityRead');
    expect(roles.length).toBeGreaterThan(0);
    expect(ADMIN_OBSERVABILITY_ROLES.length).toBeGreaterThan(0);
  });

  it('grants exactly the roles the server serves those endpoints to', () => {
    const server = distinctLowerCase(csharpRoleConstant(source, 'ObservabilityRead'));
    const client = distinctLowerCase([...ADMIN_OBSERVABILITY_ROLES]);
    expect(client).toEqual(server);
  });

  it('keeps the server list case-duplicated, because [Authorize(Roles=)] matches ordinally', () => {
    // Not decoration: dropping "Supervisor" would 403 every token whose claim is
    // capitalised, while this contract — which compares case-insensitively — stayed
    // green. So the duplication is asserted on its own terms.
    const raw = csharpRoleConstant(source, 'ObservabilityRead');
    for (const role of distinctLowerCase(raw)) {
      const capitalised = role.charAt(0).toUpperCase() + role.slice(1);
      expect(raw).toContain(role);
      expect(raw).toContain(capitalised);
    }
  });

  it('is expressed lower-cased on the client, because the token claim is normalised that way', () => {
    // `effectiveRolesFromToken` lower-cases the claim before comparing. An entry
    // like 'Supervisor' here would never match and would fail closed silently.
    for (const role of ADMIN_OBSERVABILITY_ROLES) {
      expect(role).toBe(role.toLowerCase());
    }
  });

  it('is strictly wider than the admin-only list, and never narrower', () => {
    // The whole point of the constant: observability is admin PLUS supervisor.
    // If ObservabilityRead ever collapsed back to Admin, the supervisor grant is
    // gone and this catches it without restating either list.
    const observability = distinctLowerCase(csharpRoleConstant(source, 'ObservabilityRead'));
    const adminOnly = distinctLowerCase(csharpRoleConstant(source, 'Admin'));
    for (const role of adminOnly) {
      expect(observability).toContain(role);
    }
    expect(observability.length).toBeGreaterThan(adminOnly.length);
  });

  it('does not make the client treat a supervisor as an admin', () => {
    // Viewing read-only tabs is not platform authority (§5.8.2). This list is a
    // capability allow-list; `isAdmin` remains a separate declared-role check.
    expect(ADMIN_OBSERVABILITY_ROLES).toContain('supervisor');
    expect(ADMIN_OBSERVABILITY_ROLES).toContain('admin');
  });
});
