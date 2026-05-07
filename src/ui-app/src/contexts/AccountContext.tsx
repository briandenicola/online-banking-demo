import React, { createContext, useContext, useState, ReactNode, useEffect, useCallback } from 'react';
import apiClient from '../api/client';
import { useAuthContext } from './AuthContext';

export interface Account {
  id: string;
  name: string;
  number: string;
  balance: number;
  type: string;
  currency?: string;
}

interface AccountContextType {
  accounts: Account[];
  fetchAccounts: () => Promise<void>;
  addAccount: (account: Omit<Account, 'id'>) => Promise<void>;
  transfer: (fromId: string, toId: string, amount: number) => Promise<boolean>;
}

const AccountContext = createContext<AccountContextType | undefined>(undefined);

export const useAccountContext = () => {
  const context = useContext(AccountContext);
  if (!context) throw new Error('useAccountContext must be used within AccountProvider');
  return context;
};

export const AccountProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { user, token } = useAuthContext();
  const [accounts, setAccounts] = useState<Account[]>([]);

  const fetchAccounts = useCallback(async () => {
    if (!user || !token) return;
    try {
      const response = await apiClient.get('/accounts');
      const mapped: Account[] = (response.data || []).map((a: Record<string, unknown>) => ({
        id: a.id as string,
        name: `${a.accountType} Account`,
        number: a.accountNumber as string,
        balance: a.balance as number,
        type: (a.accountType as string || '').toLowerCase(),
        currency: a.currency as string,
      }));
      setAccounts(mapped);
    } catch (e) {
      console.error('Failed to fetch accounts:', e);
    }
  }, [user, token]);

  // Fetch accounts only when user is logged in and token exists
  useEffect(() => {
    fetchAccounts();
  }, [fetchAccounts]);

  const addAccount = async (accountData: Omit<Account, 'id'>): Promise<void> => {
    const response = await apiClient.post('/accounts', {
      accountType: accountData.type,
      initialBalance: accountData.balance,
      currency: accountData.currency,
    });
    const a = response.data;
    const newAccount: Account = {
      id: a.id as string,
      name: `${a.accountType} Account`,
      number: a.accountNumber as string,
      balance: a.balance as number,
      type: (a.accountType as string || '').toLowerCase(),
      currency: a.currency as string,
    };
    setAccounts(prev => [...prev, newAccount]);
  };

  const transfer = async (fromId: string, toId: string, amount: number): Promise<boolean> => {
    try {
      await apiClient.post('/transfers', { fromAccountId: fromId, toAccountId: toId, amount });
      // Update local state on success
      setAccounts(prev => prev.map(acc => {
        if (acc.id === fromId) return { ...acc, balance: acc.balance - amount };
        if (acc.id === toId) return { ...acc, balance: acc.balance + amount };
        return acc;
      }));
      return true;
    } catch (e) {
      console.error('Transfer failed:', e);
      return false;
    }
  };

  return (
    <AccountContext.Provider value={{ accounts, fetchAccounts, addAccount, transfer }}>
      {children}
    </AccountContext.Provider>
  );
};
