import React from 'react';
import { render, screen } from '@testing-library/react';
import Accounts from './Accounts';
import { AccountProvider } from '../contexts/AccountContext';
import { AuthProvider } from '../contexts/AuthContext';

// Mock the API client
jest.mock('../api/client', () => ({
  __esModule: true,
  default: {
    post: jest.fn(),
    get: jest.fn().mockResolvedValue({ data: [] }),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() },
    },
  },
}));

const renderAccounts = () => {
  return render(
    <AuthProvider>
      <AccountProvider>
        <Accounts />
      </AccountProvider>
    </AuthProvider>
  );
};

describe('Accounts Page', () => {
  test('renders accounts heading', () => {
    renderAccounts();

    expect(screen.getByText('Accounts')).toBeInTheDocument();
  });

  test('renders add account button', () => {
    renderAccounts();

    expect(screen.getByRole('button', { name: /Add Account/i })).toBeInTheDocument();
  });

  test('renders table headers', () => {
    renderAccounts();

    expect(screen.getByText('Account Name')).toBeInTheDocument();
    expect(screen.getByText('Account Number')).toBeInTheDocument();
    expect(screen.getByText('Type')).toBeInTheDocument();
    expect(screen.getByText('Balance')).toBeInTheDocument();
  });

  test('renders empty table when no accounts', () => {
    renderAccounts();

    // Table should exist but with no data rows
    const table = screen.getByRole('table');
    expect(table).toBeInTheDocument();
  });
});
