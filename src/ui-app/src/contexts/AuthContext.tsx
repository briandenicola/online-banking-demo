import React, { createContext, useContext, useState, ReactNode, useEffect } from 'react';
import apiClient from '../api/client';
import { ACCOUNT_OPENING_STORAGE_KEY } from '../api/accountOpening';

interface User {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isAdmin: boolean;
  isBanker: boolean;
  mayViewAdminObservability: boolean;
}

/**
 * The banking role that grants access to the Banker Copilot harness.
 *
 * This MUST stay equal to `HARNESS_ROLE` in
 * `src/banker-copilot-service/app/auth.py`. The service is the authority; this
 * constant only decides whether we bother rendering the route. They were once
 * allowed to disagree — the UI gated `/copilot` on `isAdmin` while the service
 * required `banker` and explicitly rejected `admin` — which made the harness
 * unreachable by every identity: admins saw a screen the API refused, and
 * bankers were redirected away from a screen the API would have served.
 *
 * `ui-app/src/__tests__/harnessRole.contract.test.ts` reads the Python source
 * and fails if these two drift apart again.
 */
export const HARNESS_ROLE = 'banker';

/**
 * The roles the SERVER will serve the read-only admin observability endpoints
 * to (Foundry status, login audit, flagged/all transactions, evaluation).
 *
 * This is a capability, not a rank. It is named for what it grants — "may view
 * the read-only admin observability surface" — because the moment such a thing
 * is named after who holds it ("isSupervisorAdmin"), the next person to need it
 * gets given the role instead of the capability.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 *  This list does NOT make `supervisor` an admin, and must never be used to.
 *
 *  `admin` and `supervisor` are orthogonal axes (§5.8.2): admin has banking
 *  seniority 0 and implies nothing, supervisor has seniority 2 and implies
 *  banker. Widening the role hierarchy so supervisor implied admin would hand a
 *  supervisor the L3 actions — `authority.policy.edit` and `user.role.promote` —
 *  letting them rewrite the policy that governs their own co-signature. That is
 *  the separation of duties this whole demo is about. There is a tripwire test
 *  on the hierarchy for exactly that change.
 *
 *  So this grants VIEW of specific read-only tabs and nothing else. `isAdmin`
 *  stays a plain declared-role check and remains the only gate on User
 *  Management, the chatbot prompt, and applications.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * Kept as an allow-list of positive assertions so an unknown or absent role
 * fails CLOSED — the same rule as `isBatchEligible` in approvalPolicy.ts.
 */
export const ADMIN_OBSERVABILITY_ROLES: readonly string[] = ['admin', 'supervisor'];

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuthContext = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuthContext must be used within AuthProvider');
  return context;
};

function decodeJwtPayload(token: string): Record<string, unknown> {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(base64));
  } catch {
    return {};
  }
}

/**
 * Normalises the token's `effectiveRoles` claim into a lower-cased list.
 *
 * `effectiveRoles` is the same claim the services read, so role implication (a
 * supervisor implies a banker) is resolved server-side ONCE, in
 * `user-service`'s RoleHierarchy, rather than being re-derived here. A client
 * that expands the ladder itself has become a second, weaker policy engine.
 *
 * The claim arrives in three shapes: a string, an array, or (after a page
 * reload, having been through localStorage) a comma-joined string. All three
 * are normalised here, in ONE place, so a new capability cannot pick up a
 * fourth reading of the same claim. `role` is the fallback for tokens minted
 * before `effectiveRoles` existed.
 */
export function effectiveRolesFromToken(
  token: string | null,
  fallbackRole?: string
): string[] {
  if (!token) return [];
  const claims = decodeJwtPayload(token);
  const raw = claims['effectiveRoles'] ?? claims['role'] ?? fallbackRole;
  const roles = Array.isArray(raw) ? raw.map(String) : String(raw ?? '').split(',');
  return roles.map((r) => r.trim().toLowerCase()).filter((r) => r.length > 0);
}

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('auth_token'));
  
  // Initialize user synchronously from localStorage to avoid redirect flash
  const [user, setUser] = useState<User | null>(() => {
    const storedToken = localStorage.getItem('auth_token');
    const email = localStorage.getItem('auth_email');
    const role = localStorage.getItem('auth_role') || 'user';
    
    if (storedToken && email) {
      const emailParts = email.split('@')[0].split('.');
      return {
        id: '1',
        email,
        firstName: emailParts[0] || 'User',
        lastName: emailParts[1] || 'Name',
        role,
      };
    }
    return null;
  });

  // Sync user state when token changes (e.g., after login)
  useEffect(() => {
    if (token && !user) {
      const email = localStorage.getItem('auth_email');
      const role = localStorage.getItem('auth_role') || 'user';
      if (email) {
        const emailParts = email.split('@')[0].split('.');
        setUser({
          id: '1',
          email,
          firstName: emailParts[0] || 'User',
          lastName: emailParts[1] || 'Name',
          role,
        });
      }
    }
  }, [token, user]);

  const login = async (email: string, password: string) => {
    const response = await apiClient.post('/auth/login', { username: email, password });
    const data = response.data;
    const newToken = data.token;

    // Extract role from JWT claims
    const claims = decodeJwtPayload(newToken);
    const role = (claims['http://schemas.microsoft.com/ws/2008/06/identity/claims/role'] as string) || (data.role as string) || 'user';

    localStorage.setItem('auth_token', newToken);
    localStorage.setItem('auth_email', email);
    localStorage.setItem('auth_role', role);
    setToken(newToken);

    const emailParts = email.split('@')[0].split('.');
    setUser({
      id: data.userId || '1',
      email,
      firstName: emailParts[0] || 'User',
      lastName: emailParts[1] || 'Name',
      role,
    });
  };

  const logout = () => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_email');
    localStorage.removeItem('auth_role');
    localStorage.removeItem(ACCOUNT_OPENING_STORAGE_KEY);
  };

  const isAdmin = user?.role === 'admin';

  /**
   * The token's effective roles, expanded server-side. Every role-derived
   * capability below reads from this one list.
   */
  const effectiveRoles = effectiveRolesFromToken(token, user?.role);

  /**
   * Harness eligibility, mirroring what `banker-copilot-service` will actually
   * accept.
   */
  const isBanker = effectiveRoles.includes(HARNESS_ROLE);

  /**
   * May view the READ-ONLY admin observability tabs (Foundry status, login
   * audit, flagged transactions, all transactions, evaluation).
   *
   * This is a MIRROR of a server decision, never the decision itself — the same
   * discipline as `callerMaySign` in the approval surface, which is
   * "server-computed, never inferred client-side". The services enforce the
   * role on those read-only endpoints; this flag only decides whether we bother
   * rendering the route and the tabs. Hiding a surface the server would refuse
   * is a courtesy; it is not the refusal.
   *
   * Deliberately NOT `isAdmin || user?.role === 'supervisor'`: reading the
   * declared role would re-derive the ladder in the client and would drift the
   * moment the hierarchy changes — the exact defect recorded above, where the
   * UI gated `/copilot` on `isAdmin` while the service required `banker`.
   */
  const mayViewAdminObservability = effectiveRoles.some((r) =>
    ADMIN_OBSERVABILITY_ROLES.includes(r)
  );

  return (
    <AuthContext.Provider
      value={{ user, token, login, logout, isAdmin, isBanker, mayViewAdminObservability }}
    >
      {children}
    </AuthContext.Provider>
  );
};
