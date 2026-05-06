import React from 'react';
import { render, screen } from '@testing-library/react';
import App from './App';

test('renders login page when not authenticated', () => {
  render(<App />);
  const signInButtons = screen.getAllByRole('button', { name: /Sign In/i });
  expect(signInButtons.length).toBeGreaterThan(0);
});

test('renders email input field', () => {
  render(<App />);
  const emailFields = screen.getAllByLabelText(/Email Address/i);
  expect(emailFields.length).toBeGreaterThan(0);
});

test('renders password input field', () => {
  render(<App />);
  const passwordFields = screen.getAllByLabelText(/Password/i);
  expect(passwordFields.length).toBeGreaterThan(0);
});

test('renders sign in button', () => {
  render(<App />);
  const buttons = screen.getAllByRole('button', { name: /Sign In/i });
  expect(buttons.length).toBeGreaterThan(0);
});
