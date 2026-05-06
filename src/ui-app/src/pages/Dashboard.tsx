import React from 'react';
import { Box, Typography, Grid, Paper, Button, ButtonBase } from '@mui/material';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import ChatIcon from '@mui/icons-material/Chat';
import { useNavigate } from 'react-router-dom';

const Dashboard: React.FC = () => {
  const navigate = useNavigate();

  const features = [
    {
      title: 'Accounts',
      description: 'View and manage your bank accounts',
      icon: <AccountBalanceWalletIcon sx={{ fontSize: 40 }} />,
      path: '/accounts',
      color: 'primary',
    },
    {
      title: 'Transfers',
      description: 'Transfer money between accounts',
      icon: <SwapHorizIcon sx={{ fontSize: 40 }} />,
      path: '/transfers',
      color: 'secondary',
    },
    {
      title: 'Chat Assistant',
      description: 'Get AI-powered financial advice',
      icon: <ChatIcon sx={{ fontSize: 40 }} />,
      path: '/chat',
      color: 'success',
    },
  ];

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Welcome to Online Banking
      </Typography>
      <Typography variant="subtitle1" color="text.secondary">
        Access your accounts, make transfers, and get financial insights.
      </Typography>

      <Grid container spacing={3} sx={{ mt: 2 }}>
        {features.map((feature) => (
          <Grid key={feature.title} size={{ xs: 12, md: 4 }}>
            <ButtonBase
              onClick={() => navigate(feature.path)}
              aria-label={`Navigate to ${feature.title}`}
              sx={{ width: '100%', textAlign: 'left', display: 'block' }}
            >
              <Paper
                elevation={3}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  transition: 'transform 0.2s',
                  '&:hover': { transform: 'scale(1.03)' },
                }}
              >
                <Box sx={{ color: `${feature.color}.main`, mb: 2 }}>{feature.icon}</Box>
                <Typography variant="h6" gutterBottom>
                  {feature.title}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {feature.description}
                </Typography>
              </Paper>
            </ButtonBase>
          </Grid>
        ))}
      </Grid>

      <Paper elevation={2} sx={{ p: 3, mt: 4 }}>
        <Typography variant="h6" gutterBottom>
          Quick Actions
        </Typography>
        <Button variant="contained" sx={{ mr: 2 }} onClick={() => navigate('/transfers')}>
          New Transfer
        </Button>
        <Button variant="outlined" onClick={() => navigate('/transactions')}>
          View Statements
        </Button>
      </Paper>
    </Box>
  );
};

export default Dashboard;