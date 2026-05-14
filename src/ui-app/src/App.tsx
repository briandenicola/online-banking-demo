import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import theme from './theme';

// Pages
import Dashboard from './pages/Dashboard';
import Accounts from './pages/Accounts';
import Transactions from './pages/Transactions';
import Transfers from './pages/Transfers';
import Chat from './pages/Chat';
import AdminPage from './pages/AdminPage';
import Settings from './pages/Settings';
import AccountOpeningPage from './pages/AccountOpeningPage';
import CustomerApplicationStatusPage from './pages/CustomerApplicationStatusPage';
import Login from './pages/Login';
import RegisterPage from './pages/RegisterPage';
import AppShell from './components/AppShell';
import ErrorBoundary from './components/ErrorBoundary';
import { AuthProvider, useAuthContext } from './contexts/AuthContext';
import { AccountProvider } from './contexts/AccountContext';

const AppContent: React.FC = () => {
  const { user, isAdmin } = useAuthContext();

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="*" element={<Navigate to="/login" />} />
      </Routes>
    );
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<ErrorBoundary section="Dashboard"><Dashboard /></ErrorBoundary>} />
        <Route path="/accounts" element={<ErrorBoundary section="Accounts"><Accounts /></ErrorBoundary>} />
        <Route path="/transactions" element={<ErrorBoundary section="Transactions"><Transactions /></ErrorBoundary>} />
        <Route path="/transfers" element={<ErrorBoundary section="Transfers"><Transfers /></ErrorBoundary>} />
        <Route path="/chat" element={<ErrorBoundary section="Chat"><Chat /></ErrorBoundary>} />
        <Route path="/settings" element={<ErrorBoundary section="Settings"><Settings /></ErrorBoundary>} />
        <Route path="/account-opening" element={<ErrorBoundary section="Account Opening"><AccountOpeningPage /></ErrorBoundary>} />
        <Route path="/applications/:id/status" element={<ErrorBoundary section="Application Status"><CustomerApplicationStatusPage /></ErrorBoundary>} />
        {isAdmin && <Route path="/admin" element={<ErrorBoundary section="Admin"><AdminPage /></ErrorBoundary>} />}
        <Route path="/login" element={<Navigate to="/" />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </AppShell>
  );
};

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <ErrorBoundary>
        <AuthProvider>
          <AccountProvider>
            <Router>
              <AppContent />
            </Router>
          </AccountProvider>
        </AuthProvider>
      </ErrorBoundary>
    </ThemeProvider>
  );
}

export default App;
