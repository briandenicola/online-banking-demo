import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  Container,
  Box,
  Typography,
  TextField,
  Button,
  Paper,
  Alert,
} from '@mui/material';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';

const Login: React.FC = () => {
  const [email, setEmail] = useState('demo@banking-demo.com');
  const [password, setPassword] = useState('password123');
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await login(email, password);
      navigate('/');
    } catch (err) {
      setError('Login failed. Please try again.');
    }
  };

  return (
    <Container component="main" maxWidth="xs">
      <Box
        sx={{
          marginTop: 8,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
        }}
      >
        <Paper elevation={3} sx={{ padding: 4, width: '100%' }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <LockOutlinedIcon sx={{ fontSize: 40, color: 'primary.main', mb: 1 }} />
            <Typography component="h1" variant="h5">
              Sign in to Online Banking
            </Typography>
            <Box component="form" onSubmit={handleSubmit} sx={{ mt: 1, width: '100%' }}>
              {error && <Alert severity="error">{error}</Alert>}
              <TextField
                margin="normal"
                required
                fullWidth
                label="Email Address"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                autoFocus
              />
              <TextField
                margin="normal"
                required
                fullWidth
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
              <Button type="submit" fullWidth variant="contained" sx={{ mt: 3, mb: 2 }}>
                Sign In
              </Button>
              <Typography variant="body2" color="text.secondary" align="center">
                Demo credentials: demo@banking-demo.com / password123
              </Typography>
            </Box>
          </Box>
        </Paper>
      </Box>
    </Container>
  );
};

export default Login;