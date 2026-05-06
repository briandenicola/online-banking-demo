import React, { createContext, useContext, useState, ReactNode, useEffect } from 'react';
import apiClient from '../api/client';

interface User {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuthContext = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuthContext must be used within AuthProvider');
  return context;
};

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('auth_token'));

  // Restore user from token on mount
  useEffect(() => {
    if (token && !user) {
      const email = localStorage.getItem('auth_email');
      if (email) {
        const emailParts = email.split('@')[0].split('.');
        setUser({
          id: '1',
          email,
          firstName: emailParts[0] || 'User',
          lastName: emailParts[1] || 'Name',
        });
      }
    }
  }, [token, user]);

  const login = async (email: string, password: string) => {
    const response = await apiClient.post('/auth/login', { username: email, password });
    const data = response.data;
    const newToken = data.token;

    localStorage.setItem('auth_token', newToken);
    localStorage.setItem('auth_email', email);
    setToken(newToken);

    const emailParts = email.split('@')[0].split('.');
    setUser({
      id: '1',
      email,
      firstName: emailParts[0] || 'User',
      lastName: emailParts[1] || 'Name',
    });
  };

  const logout = () => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_email');
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};
