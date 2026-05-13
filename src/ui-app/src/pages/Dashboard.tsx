import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Grid,
  Card,
  CardContent,
  Button,
  ButtonBase,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Chip,
  Divider,
  Avatar,
  CircularProgress,
} from '@mui/material';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import ChatIcon from '@mui/icons-material/Chat';
import PaymentIcon from '@mui/icons-material/Payment';
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import AddBusinessIcon from '@mui/icons-material/AddBusiness';
import { useNavigate } from 'react-router-dom';
import { useAuthContext } from '../contexts/AuthContext';
import { useAccountContext } from '../contexts/AccountContext';
import apiClient from '../api/client';
import { logger } from '../utils/logger';
import ApplicationStatus from '../components/account-opening/ApplicationStatus';
import { ACCOUNT_OPENING_STORAGE_KEY } from '../api/accountOpening';

interface RecentTransaction {
  id: string;
  description: string;
  amount: number;
  timestamp: string;
  category?: string;
}

const quickActions = [
  { label: 'Transfer Money', icon: <SwapHorizIcon />, path: '/transfers' },
  { label: 'Pay Bills', icon: <PaymentIcon />, path: '/transfers' },
  { label: 'View Statements', icon: <ReceiptLongIcon />, path: '/transactions' },
  { label: 'Chat Assistant', icon: <ChatIcon />, path: '/chat' },
  { label: 'Open Account', icon: <AddBusinessIcon />, path: '/account-opening' },
];

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { user, token } = useAuthContext();
  const { accounts } = useAccountContext();
  const [transactions, setTransactions] = useState<RecentTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [applicationId, setApplicationId] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    const fetchRecentTransactions = async () => {
      try {
        const response = await apiClient.get('/transactions/my');
        const data = Array.isArray(response.data) ? response.data : (response.data.transactions || []);
        setTransactions(data.slice(0, 5));
      } catch (e) {
        logger.error('Failed to fetch recent transactions', e);
      } finally {
        setLoading(false);
      }
    };
    fetchRecentTransactions();
  }, [token]);

  useEffect(() => {
    setApplicationId(localStorage.getItem(ACCOUNT_OPENING_STORAGE_KEY));
  }, []);

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'morning';
    if (hour < 17) return 'afternoon';
    return 'evening';
  };

  return (
    <Box>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: 'primary.dark' }}>
          Good {getGreeting()}, {user?.firstName || 'User'}
        </Typography>
        <Typography variant="subtitle1" color="text.secondary" sx={{ mt: 0.5 }}>
          Here&apos;s your financial overview
        </Typography>
      </Box>

      <Grid container spacing={3} sx={{ mb: 4 }}>
        {accounts.length === 0 && !loading ? (
          <Grid size={{ xs: 12 }}>
            <Typography color="text.secondary">No accounts found. Create one to get started.</Typography>
          </Grid>
        ) : accounts.map((account) => (
          <Grid key={account.id} size={{ xs: 12, md: 4 }}>
            <ButtonBase
              onClick={() => navigate('/accounts')}
              sx={{ width: '100%', textAlign: 'left', display: 'block' }}
              aria-label={`View ${account.name}`}
            >
              <Card
                sx={{
                  transition: 'transform 0.2s, box-shadow 0.2s',
                  '&:hover': {
                    transform: 'translateY(-2px)',
                    boxShadow: '0 8px 16px rgba(0,48,135,0.12)',
                  },
                }}
              >
                <CardContent sx={{ p: 3 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                    <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 500 }}>
                      {account.name}
                    </Typography>
                    <Avatar
                      sx={{
                        width: 36,
                        height: 36,
                        bgcolor: account.type === 'credit' ? 'warning.main' : 'primary.main',
                      }}
                    >
                      <AccountBalanceWalletIcon sx={{ fontSize: 18 }} />
                    </Avatar>
                  </Box>
                  <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>
                    {account.balance < 0 ? '-' : ''}${Math.abs(account.balance).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {account.number}
                  </Typography>
                </CardContent>
              </Card>
            </ButtonBase>
          </Grid>
        ))}
      </Grid>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Card>
            <CardContent sx={{ p: 0 }}>
              <Box sx={{ p: 3, pb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography variant="h6" sx={{ fontWeight: 600 }}>
                  Recent Transactions
                </Typography>
                <Button size="small" onClick={() => navigate('/transactions')}>
                  View All
                </Button>
              </Box>
              <List disablePadding>
                {loading ? (
                  <ListItem sx={{ justifyContent: 'center', py: 3 }}>
                    <CircularProgress size={24} />
                  </ListItem>
                ) : transactions.length === 0 ? (
                  <ListItem sx={{ px: 3, py: 2 }}>
                    <ListItemText primary="No recent transactions" />
                  </ListItem>
                ) : transactions.map((tx, index) => (
                  <React.Fragment key={tx.id}>
                    {index > 0 && <Divider />}
                    <ListItem sx={{ px: 3, py: 1.5 }}>
                      <ListItemIcon>
                        <Avatar
                          sx={{
                            width: 40,
                            height: 40,
                            bgcolor: tx.amount > 0 ? 'success.main' : 'grey.100',
                            color: tx.amount > 0 ? 'white' : 'text.secondary',
                          }}
                        >
                          {tx.amount > 0 ? <TrendingUpIcon /> : <ShoppingCartIcon />}
                        </Avatar>
                      </ListItemIcon>
                      <ListItemText
                        primary={tx.description}
                        secondary={new Date(tx.timestamp).toLocaleDateString()}
                        slotProps={{ primary: { sx: { fontWeight: 500, fontSize: '0.9rem' } }, secondary: { sx: { fontSize: '0.75rem' } } }}
                      />
                      <Typography
                        variant="body2"
                        sx={{ fontWeight: 600 }}
                        color={tx.amount > 0 ? 'success.main' : 'text.primary'}
                      >
                        {tx.amount > 0 ? '+' : '-'}${Math.abs(tx.amount).toFixed(2)}
                      </Typography>
                    </ListItem>
                  </React.Fragment>
                ))}
              </List>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 5 }}>
          <Card>
            <CardContent sx={{ p: 3 }}>
              <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
                Quick Actions
              </Typography>
              <Grid container spacing={2}>
                {quickActions.map((action) => (
                  <Grid key={action.label} size={{ xs: 6 }}>
                    <ButtonBase
                      onClick={() => navigate(action.path)}
                      sx={{
                        width: '100%',
                        p: 2,
                        borderRadius: 2,
                        border: '1px solid',
                        borderColor: 'divider',
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: 1,
                        transition: 'all 0.2s',
                        '&:hover': {
                          borderColor: 'primary.main',
                          bgcolor: 'rgba(0,48,135,0.04)',
                        },
                      }}
                    >
                      <Avatar sx={{ bgcolor: 'primary.main', width: 44, height: 44 }}>
                        {action.icon}
                      </Avatar>
                      <Typography variant="caption" sx={{ fontWeight: 500, textAlign: 'center' }}>
                        {action.label}
                      </Typography>
                    </ButtonBase>
                  </Grid>
                ))}
              </Grid>
            </CardContent>
          </Card>

          <Card sx={{ mt: 3 }}>
            <CardContent sx={{ p: 3 }}>
              <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
                Account Status
              </Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                <Chip label="All accounts active" color="success" size="small" variant="outlined" />
                <Chip label="No alerts" color="info" size="small" variant="outlined" />
                <Chip label="Auto-pay enabled" size="small" variant="outlined" />
              </Box>
            </CardContent>
          </Card>

          <Box sx={{ mt: 3 }}>
            {applicationId ? (
              <ApplicationStatus applicationId={applicationId} />
            ) : (
              <Card>
                <CardContent sx={{ p: 3 }}>
                  <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>
                    Open a New Account
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    Start a new checking or savings application in minutes.
                  </Typography>
                  <Button variant="contained" onClick={() => navigate('/account-opening')}>
                    Start Application
                  </Button>
                </CardContent>
              </Card>
            )}
          </Box>
        </Grid>
      </Grid>
    </Box>
  );
};

export default Dashboard;
