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
import BankerCopilotPage from './pages/BankerCopilotPage';
import Settings from './pages/Settings';
import AccountOpeningPage from './pages/AccountOpeningPage';
import CustomerApplicationStatusPage from './pages/CustomerApplicationStatusPage';
import Login from './pages/Login';
import RegisterPage from './pages/RegisterPage';
import AppShell from './components/AppShell';
import ErrorBoundary from './components/ErrorBoundary';
import FlagDisabledNotice from './components/FlagDisabledNotice';
import { AuthProvider, useAuthContext } from './contexts/AuthContext';
import { AccountProvider } from './contexts/AccountContext';
import { FeatureFlagProvider, useFeatureFlags } from './contexts/FeatureFlagContext';
import { setComparisonEnabled } from './telemetry/comparison';

const AppContent: React.FC = () => {
  const { user, isAdmin } = useAuthContext();
  const { isEnabled } = useFeatureFlags();

  // Keep the comparison recorder in step with its flag. Instrumentation is a
  // behaviour toggle, not a surface toggle, so it gates collection rather than
  // a route.
  const comparisonEnabled = isEnabled('comparisonInstrumentation');
  React.useEffect(() => {
    setComparisonEnabled(comparisonEnabled);
  }, [comparisonEnabled]);

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

        {/*
          Surface routes are gated by BOTH the role check and a feature flag.
          The two do different jobs and must not be confused:
            - `isAdmin` is the (client-side mirror of the) authorisation check.
            - the flag is a presentation toggle for the coexistence comparison.
          The flag renders an explanatory, reversible notice rather than a 404,
          precisely so it is never mistaken for an access denial. See
          src/config/featureFlags.ts.
        */}
        {isAdmin && (
          <Route
            path="/admin"
            element={
              <ErrorBoundary section="Admin">
                {isEnabled('classicAdminTabs') ? (
                  <AdminPage />
                ) : (
                  <FlagDisabledNotice flag="classicAdminTabs" />
                )}
              </ErrorBoundary>
            }
          />
        )}
        {isAdmin && (
          <Route
            path="/copilot"
            element={
              <ErrorBoundary section="Banker Copilot">
                {isEnabled('bankerCopilot') ? (
                  <BankerCopilotPage />
                ) : (
                  <FlagDisabledNotice flag="bankerCopilot" />
                )}
              </ErrorBoundary>
            }
          />
        )}
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
        <FeatureFlagProvider>
          <AuthProvider>
            <AccountProvider>
              <Router>
                <AppContent />
              </Router>
            </AccountProvider>
          </AuthProvider>
        </FeatureFlagProvider>
      </ErrorBoundary>
    </ThemeProvider>
  );
}

export default App;
