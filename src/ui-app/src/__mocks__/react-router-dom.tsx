import React from 'react';

const useNavigate = () => jest.fn();
const useLocation = () => ({ pathname: '/', search: '', hash: '', state: null });
const useParams = () => ({});
const useSearchParams = () => [new URLSearchParams(), jest.fn()];

const BrowserRouter: React.FC<{ children: React.ReactNode }> = ({ children }) => <>{children}</>;
const Routes: React.FC<{ children: React.ReactNode }> = ({ children }) => <>{children}</>;
const Route: React.FC<{ path?: string; element?: React.ReactNode }> = ({ element }) => <>{element}</>;
const Navigate: React.FC<{ to: string }> = () => null;
const Link: React.FC<{ to: string; children: React.ReactNode }> = ({ children }) => <a>{children}</a>;

export {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  Link,
  useNavigate,
  useLocation,
  useParams,
  useSearchParams,
};
