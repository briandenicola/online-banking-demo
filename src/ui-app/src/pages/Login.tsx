import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuthContext } from '../contexts/AuthContext';
import {
  Container,
  Box,
  Typography,
  TextField,
  Button,
  Paper,
  Alert,
  Link,
  Divider,
} from '@mui/material';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';

const isDemoMode = process.env.REACT_APP_DEMO_MODE === 'true';

const Login: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const { login } = useAuthContext();
  const navigate = useNavigate();
  const location = useLocation();
  const successMessage = (location.state as any)?.message || '';

  const validate = (): boolean => {
    const errors: { email?: string; password?: string } = {};
    if (!email.trim()) errors.email = 'Email is required';
    if (!password) errors.password = 'Password is required';
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const performLogin = async (loginEmail: string, loginPassword: string) => {
    setError('');
    setFieldErrors({});
    try {
      await login(loginEmail, loginPassword);
      navigate('/');
    } catch (err: any) {
      const serverMessage = err.response?.data?.message;
      setError(serverMessage || 'Unable to connect. Please try again later.');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    await performLogin(email.trim(), password);
  };

  const handleDemoLogin = async () => {
    setEmail('demo@banking-demo.com');
    setPassword('password123');
    await performLogin('demo@banking-demo.com', 'password123');
  };

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        bgcolor: '#f5f7fa',
      }}
    >
      <Box sx={{ bgcolor: 'primary.main', py: 2, px: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <AccountBalanceIcon sx={{ color: 'white', fontSize: 32 }} />
          <Typography variant="h6" component="span" sx={{ color: 'white', fontWeight: 700 }}>
            SecureBank
          </Typography>
        </Box>
      </Box>

      <Container component="main" maxWidth="sm" sx={{ flex: 1, display: 'flex', alignItems: 'center', py: 4 }}>
        <Paper
          elevation={2}
          sx={{
            p: { xs: 3, sm: 5 },
            width: '100%',
            border: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Box sx={{ textAlign: 'center', mb: 4 }}>
            <Box
              sx={{
                width: 56,
                height: 56,
                borderRadius: '50%',
                bgcolor: 'primary.main',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                mx: 'auto',
                mb: 2,
              }}
            >
              <LockOutlinedIcon sx={{ color: 'white', fontSize: 28 }} />
            </Box>
            <Typography component="h1" variant="h5" sx={{ fontWeight: 700, color: 'primary.dark' }}>
              Welcome to Secure Bank
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Sign in to access your accounts securely
            </Typography>
            {isDemoMode && (
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                Demo mode: use the Demo Login button below
              </Typography>
            )}
          </Box>

          <Box component="form" onSubmit={handleSubmit}>
            {successMessage && (
              <Alert severity="success" sx={{ mb: 2 }}>{successMessage}</Alert>
            )}
            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
            )}

            <TextField
              margin="normal"
              required
              fullWidth
              label="Email Address"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setFieldErrors((prev) => ({ ...prev, email: undefined })); }}
              autoComplete="email"
              autoFocus
              variant="outlined"
              error={!!fieldErrors.email}
              helperText={fieldErrors.email}
            />
            <TextField
              margin="normal"
              required
              fullWidth
              label="Password"
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setFieldErrors((prev) => ({ ...prev, password: undefined })); }}
              autoComplete="current-password"
              variant="outlined"
              error={!!fieldErrors.password}
              helperText={fieldErrors.password}
            />

            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 1 }}>
              <Link
                component="button"
                type="button"
                variant="body2"
                sx={{ color: 'primary.main', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
              >
                Forgot password?
              </Link>
            </Box>

            <Button
              type="submit"
              fullWidth
              variant="contained"
              size="large"
              sx={{ mt: 3, mb: 2, py: 1.5 }}
            >
              Sign In
            </Button>

            {isDemoMode && (
              <Button
                fullWidth
                variant="outlined"
                size="small"
                onClick={handleDemoLogin}
                sx={{ mb: 2, py: 1, color: 'text.secondary', borderColor: 'divider' }}
              >
                Demo Login
              </Button>
            )}

            <Divider sx={{ my: 2 }}>
              <Typography variant="caption" color="text.secondary">
                New to SecureBank?
              </Typography>
            </Divider>

            <Button
              fullWidth
              variant="outlined"
              onClick={() => navigate('/register')}
              sx={{ py: 1.2 }}
            >
              Enroll Now
            </Button>
          </Box>
        </Paper>
      </Container>

      <Box sx={{ textAlign: 'center', py: 2, px: 2, bgcolor: '#f5f7fa' }}>
        <Typography variant="caption" color="text.secondary">
          SecureBank is FDIC insured. {'\u00A9'} {new Date().getFullYear()} SecureBank. All rights reserved.
        </Typography>
      </Box>
    </Box>
  );
};

export default Login;
