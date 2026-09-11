/**
 * The read-only admin observability capability, derived from `effectiveRoles`.
 *
 * The failure this guards against is documented in AuthContext.tsx: the UI once
 * gated `/copilot` on `isAdmin` while the service required `banker`, and each
 * side was internally coherent while the surface was unreachable by everyone.
 * The rule that came out of it is that the client reads the SAME claim the
 * service reads, and never re-derives the ladder.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import {
  ADMIN_OBSERVABILITY_ROLES,
  AuthProvider,
  effectiveRolesFromToken,
  useAuthContext,
} from '../AuthContext';

/** An unsigned JWT carrying the given claims. Only the payload is ever read. */
function tokenWith(claims: Record<string, unknown>): string {
  const b64 = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `${b64({ alg: 'none' })}.${b64(claims)}.sig`;
}

const Probe: React.FC = () => {
  const { isAdmin, isBanker, mayViewAdminObservability } = useAuthContext();
  return (
    <div>
      <span data-testid="isAdmin">{String(isAdmin)}</span>
      <span data-testid="isBanker">{String(isBanker)}</span>
      <span data-testid="mayView">{String(mayViewAdminObservability)}</span>
    </div>
  );
};

function signIn(role: string, effectiveRoles: unknown) {
  localStorage.setItem('auth_token', tokenWith({ role, effectiveRoles }));
  localStorage.setItem('auth_email', `a.person@example.com`);
  localStorage.setItem('auth_role', role);
}

function renderProbe() {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );
  return {
    isAdmin: screen.getByTestId('isAdmin').textContent,
    isBanker: screen.getByTestId('isBanker').textContent,
    mayView: screen.getByTestId('mayView').textContent,
  };
}

beforeEach(() => localStorage.clear());

describe('mayViewAdminObservability', () => {
  it('is true for a supervisor', () => {
    signIn('supervisor', ['supervisor', 'banker']);
    expect(renderProbe().mayView).toBe('true');
  });

  it('is true for an admin', () => {
    signIn('admin', ['admin']);
    expect(renderProbe().mayView).toBe('true');
  });

  it('is false for a plain banker', () => {
    signIn('banker', ['banker']);
    const r = renderProbe();
    expect(r.mayView).toBe('false');
    expect(r.isBanker).toBe('true'); // the harness gate is unaffected
  });

  it('is false for an ordinary customer', () => {
    signIn('user', ['user']);
    expect(renderProbe().mayView).toBe('false');
  });

  it('is false with no token at all', () => {
    expect(renderProbe().mayView).toBe('false');
  });
});

describe('the two axes stay orthogonal', () => {
  /**
   * The tripwire in UI form. `isAdmin` must remain a DECLARED-role check, so a
   * supervisor — however senior in banking terms — is never an admin. Making
   * supervisor imply admin would hand them `authority.policy.edit` and
   * `user.role.promote`: the power to rewrite the policy governing their own
   * co-signature.
   */
  it('does not make a supervisor an admin', () => {
    signIn('supervisor', ['supervisor', 'banker']);
    const r = renderProbe();
    expect(r.isAdmin).toBe('false');
    expect(r.mayView).toBe('true'); // view, without becoming
  });

  it('does not make an admin a banker', () => {
    // admin implies nothing (§5.8.2); the copilot harness stays out of reach.
    signIn('admin', ['admin']);
    expect(renderProbe().isBanker).toBe('false');
  });

  it('grants the capability to exactly two roles', () => {
    expect([...ADMIN_OBSERVABILITY_ROLES].sort()).toEqual(['admin', 'supervisor']);
    expect(ADMIN_OBSERVABILITY_ROLES).not.toContain('banker');
    expect(ADMIN_OBSERVABILITY_ROLES).not.toContain('user');
  });
});

describe('the capability reads effectiveRoles, not the declared role', () => {
  /**
   * DELIBERATELY SELF-INCONSISTENT FIXTURES. Do not "fix" them into agreement —
   * that restores the hole.
   *
   * Every other fixture here keeps `role` and `effectiveRoles` consistent, so a
   * client that read `user.role` directly would pass all of them by
   * coincidence. That is the absent-by-coincidence shape this repo keeps
   * producing. These two make the declared role useless, so only the
   * effectiveRoles read can produce the right answer.
   *
   * It also encodes the real contract: `effectiveRoles` is expanded ONCE,
   * server-side, from config/role-hierarchy.yaml. If the ladder changes there,
   * the client must follow without a code change.
   */
  it('honours a grant that only effectiveRoles carries', () => {
    signIn('banker', ['banker', 'supervisor']);
    const r = renderProbe();
    expect(r.mayView).toBe('true');
    expect(r.isAdmin).toBe('false');
  });

  it('withholds the capability when effectiveRoles does not carry it', () => {
    signIn('supervisor', ['banker']);
    expect(renderProbe().mayView).toBe('false');
  });
});

describe('effectiveRolesFromToken normalises every arrival shape', () => {
  // One normaliser, so a new capability cannot pick up a fourth reading of the
  // same claim.
  it('reads an array', () => {
    expect(effectiveRolesFromToken(tokenWith({ effectiveRoles: ['Supervisor', 'banker'] })))
      .toEqual(['supervisor', 'banker']);
  });

  it('reads a bare string', () => {
    expect(effectiveRolesFromToken(tokenWith({ effectiveRoles: 'supervisor' })))
      .toEqual(['supervisor']);
  });

  it('reads the comma-joined form left by a localStorage round trip', () => {
    expect(effectiveRolesFromToken(tokenWith({ effectiveRoles: 'supervisor, banker' })))
      .toEqual(['supervisor', 'banker']);
  });

  it('falls back to `role` for tokens minted before effectiveRoles existed', () => {
    expect(effectiveRolesFromToken(tokenWith({ role: 'supervisor' }))).toEqual(['supervisor']);
  });

  it('yields nothing for an absent or unreadable token', () => {
    expect(effectiveRolesFromToken(null)).toEqual([]);
    expect(effectiveRolesFromToken('not-a-jwt')).toEqual([]);
    expect(effectiveRolesFromToken(tokenWith({}))).toEqual([]);
  });
});
