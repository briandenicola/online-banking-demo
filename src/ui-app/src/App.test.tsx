import React from 'react';
import { render, screen } from '@testing-library/react';
import App from './App';

test('renders login page when not authenticated', () => {
  render(<App />);
  const signInElement = screen.getByText(/Sign in to Online Banking/i);
  expect(signInElement).toBeInTheDocument();
});

test('renders email input field', () => {
  render(<App />);
  const emailField = screen.getByLabelText(/Email Address/i);
  expect(emailField).toBeInTheDocument();
});

test('renders password input field', () => {
  render(<App />);
  const passwordField = screen.getByLabelText(/Password/i);
  expect(passwordField).toBeInTheDocument();
});

test('renders sign in button', () => {
  render(<App />);
  const button = screen.getByRole('button', { name: /Sign In/i });
  expect(button).toBeInTheDocument();
});
