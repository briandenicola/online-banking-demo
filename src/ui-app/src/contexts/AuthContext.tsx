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
   * Harness eligibility, mirroring what `banker-copilot-service` will actually
   * accept. Read from the token's `effectiveRoles` claim — the same claim the
   * service reads — so role implication (a supervisor implies a banker) is
   * resolved server-side, once, rather than being re-derived here.
   *
   * The claim arrives as a string, an array, or (after a page reload, having
   * been through localStorage) a comma-joined string. All three are normalised.
   * `role` is the fallback for tokens minted before `effectiveRoles` existed.
   */
  const isBanker = (() => {
    if (!token) return false;
    const claims = decodeJwtPayload(token);
    const raw = claims['effectiveRoles'] ?? claims['role'] ?? user?.role;
    const roles = Array.isArray(raw)
      ? raw.map(String)
      : String(raw ?? '').split(',');
    return roles.map((r) => r.trim().toLowerCase()).includes(HARNESS_ROLE);
  })();

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAdmin, isBanker }}>
      {children}
    </AuthContext.Provider>
  );
};
