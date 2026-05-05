import React, { createContext, useContext, useState, ReactNode, useEffect } from 'react';

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
  addAccount: (account: Omit<Account, 'id'>) => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
};

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [nextAccountId, setNextAccountId] = useState(1);

  // Fetch accounts from API on mount
  useEffect(() => {
    const fetchAccounts = async () => {
      try {
        const response = await fetch('/api/accounts');
        if (response.ok) {
          const data = await response.json();
          setAccounts(data);
          if (data.length > 0) {
            setNextAccountId(Math.max(...data.map((a: Account) => parseInt(a.id) || 0)) + 1);
          }
        }
      } catch (e) {
        console.error('Failed to fetch accounts:', e);
      }
    };
    fetchAccounts();
  }, []);

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

  const addAccount = (accountData: Omit<Account, 'id'>) => {
    const newAccount: Account = {
      ...accountData,
      id: nextAccountId.toString()
    };
    setAccounts(prev => [...prev, newAccount]);
    setNextAccountId(prev => prev + 1);
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
    <AuthContext.Provider value={{ user, accounts, transfer, addAccount, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};