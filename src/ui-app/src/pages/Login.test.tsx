import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Login from './Login';
import { AuthProvider } from '../contexts/AuthContext';
import { AccountProvider } from '../contexts/AccountContext';

// Mock the API client
jest.mock('../api/client', () => ({
  __esModule: true,
  default: {
    post: jest.fn(),
    get: jest.fn(),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() },
    },
  },
}));

const renderLogin = () => {
  return render(
    <AuthProvider>
      <AccountProvider>
        <Login />
      </AccountProvider>
    </AuthProvider>
  );
};

describe('Login Page', () => {
  test('renders login form with email and password fields', () => {
    renderLogin();

    expect(screen.getByLabelText(/Email Address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Sign In/i })).toBeInTheDocument();
  });

  test('renders sign in title', () => {
    renderLogin();

    expect(screen.getByText(/Welcome to Secure Bank/i)).toBeInTheDocument();
  });

  test('has pre-filled demo credentials', () => {
    renderLogin();

    const emailInput = screen.getByLabelText(/Email Address/i) as HTMLInputElement;
    const passwordInput = screen.getByLabelText(/Password/i) as HTMLInputElement;

    expect(emailInput.value).toBe('');
    expect(passwordInput.value).toBe('password123');
  });

  test('shows demo credentials hint', () => {
    renderLogin();

    expect(screen.getByText(/Demo credentials/i)).toBeInTheDocument();
  });

  test('shows server error message on failed login', async () => {
    const apiClient = require('../api/client').default;
    apiClient.post.mockRejectedValueOnce({
      response: { status: 401, data: { message: 'Invalid credentials' } },
    });

    renderLogin();

    const button = screen.getByRole('button', { name: /Sign In/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText('Invalid credentials')).toBeInTheDocument();
    });
  });

  test('shows fallback error on network failure', async () => {
    const apiClient = require('../api/client').default;
    apiClient.post.mockRejectedValueOnce(new Error('Network Error'));

    renderLogin();

    const button = screen.getByRole('button', { name: /Sign In/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText(/Unable to connect/i)).toBeInTheDocument();
    });
  });

  test('calls login API on form submit', async () => {
    const apiClient = require('../api/client').default;
    apiClient.post.mockResolvedValueOnce({
      data: { token: 'mock-token', userId: '1', username: 'demo@banking-demo.com' }
    });

    renderLogin();

    const button = screen.getByRole('button', { name: /Sign In/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/auth/login', {
        username: 'demo@banking-demo.com',
        password: 'password123'
      });
    });
  });
});
