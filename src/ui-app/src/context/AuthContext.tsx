import React, { createContext, useContext, useState, ReactNode } from 'react';

export interface Account {
  id: string;
  name: string;
  number: string;
  balance: number;
  type: string;
}

interface User {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
}

interface AuthContextType {
  user: User | null;
  accounts: Account[];
  transfer: (fromId: string, toId: string, amount: number) => boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
};

const initialAccounts: Account[] = [
  { id: '1', name: 'Checking Account', number: '****-1234', balance: 2543.78, type: 'Checking' },
  { id: '2', name: 'Savings Account', number: '****-5678', balance: 15234.56, type: 'Savings' },
  { id: '3', name: 'Credit Card', number: '****-9012', balance: -876.23, type: 'Credit' },
];

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [accounts, setAccounts] = useState<Account[]>(initialAccounts);

  const transfer = (fromId: string, toId: string, amount: number): boolean => {
    setAccounts(prev => prev.map(acc => {
      if (acc.id === fromId) {
        return { ...acc, balance: acc.balance - amount };
      }
      if (acc.id === toId) {
        return { ...acc, balance: acc.balance + amount };
      }
      return acc;
    }));
    return true;
  };

  const login = async (email: string, password: string) => {
    setUser({
      id: '1',
      email,
      firstName: 'John',
      lastName: 'Doe',
    });
  };

  const logout = () => {
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, accounts, transfer, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};