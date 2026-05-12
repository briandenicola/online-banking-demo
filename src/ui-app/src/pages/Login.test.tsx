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

  test('initializes with empty fields', () => {
    renderLogin();

    const emailInput = screen.getByLabelText(/Email Address/i) as HTMLInputElement;
    const passwordInput = screen.getByLabelText(/Password/i) as HTMLInputElement;

    expect(emailInput.value).toBe('');
    expect(passwordInput.value).toBe('');
  });

  test('shows validation errors when submitting empty form', async () => {
    renderLogin();

    const button = screen.getByRole('button', { name: /Sign In/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText('Email is required')).toBeInTheDocument();
      expect(screen.getByText('Password is required')).toBeInTheDocument();
    });
  });

  test('does not show demo hint when REACT_APP_DEMO_MODE is not set', () => {
    renderLogin();

    expect(screen.queryByText(/Demo mode/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Demo Login/i })).not.toBeInTheDocument();
  });

  test('shows server error message on failed login', async () => {
    const apiClient = require('../api/client').default;
    apiClient.post.mockRejectedValueOnce({
      response: { status: 401, data: { message: 'Invalid credentials' } },
    });

    renderLogin();

    fireEvent.change(screen.getByLabelText(/Email Address/i), { target: { value: 'bad@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: 'wrongpass' } });

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

    fireEvent.change(screen.getByLabelText(/Email Address/i), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: 'somepass' } });

    const button = screen.getByRole('button', { name: /Sign In/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText(/Unable to connect/i)).toBeInTheDocument();
    });
  });

  test('calls login API on form submit with entered credentials', async () => {
    const apiClient = require('../api/client').default;
    apiClient.post.mockResolvedValueOnce({
      data: { token: 'mock-token', userId: '1', username: 'test@example.com' }
    });

    renderLogin();

    fireEvent.change(screen.getByLabelText(/Email Address/i), { target: { value: 'test@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: 'mypassword' } });

    const button = screen.getByRole('button', { name: /Sign In/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/auth/login', {
        username: 'test@example.com',
        password: 'mypassword'
      });
    });
  });
});
