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
import Login from './pages/Login';
import RegisterPage from './pages/RegisterPage';
import AppShell from './components/AppShell';
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
        <Route path="/" element={<Dashboard />} />
        <Route path="/accounts" element={<Accounts />} />
        <Route path="/transactions" element={<Transactions />} />
        <Route path="/transfers" element={<Transfers />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/settings" element={<Settings />} />
        {isAdmin && <Route path="/admin" element={<AdminPage />} />}
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
      <AuthProvider>
        <AccountProvider>
          <Router>
            <AppContent />
          </Router>
        </AccountProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
