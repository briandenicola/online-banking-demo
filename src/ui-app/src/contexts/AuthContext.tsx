import React, { createContext, useContext, useState, ReactNode, useEffect } from 'react';
import apiClient from '../api/client';

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
}

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
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('auth_token'));

  // Restore user from token on mount
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
  };

  const isAdmin = user?.role === 'admin';

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAdmin }}>
      {children}
    </AuthContext.Provider>
  );
};
