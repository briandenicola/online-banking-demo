import React from 'react';
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
} from '@mui/material';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import ChatIcon from '@mui/icons-material/Chat';
import PaymentIcon from '@mui/icons-material/Payment';
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import RestaurantIcon from '@mui/icons-material/Restaurant';
import LocalGasStationIcon from '@mui/icons-material/LocalGasStation';
import SubscriptionsIcon from '@mui/icons-material/Subscriptions';
import { useNavigate } from 'react-router-dom';
import { useAuthContext } from '../contexts/AuthContext';

const mockAccounts = [
  { name: 'Checking Account', number: '****4521', balance: 12847.93, type: 'checking' },
  { name: 'Savings Account', number: '****8834', balance: 45230.17, type: 'savings' },
  { name: 'Credit Card', number: '****2201', balance: -1543.22, type: 'credit' },
];

const mockTransactions = [
  { id: 1, description: 'Amazon.com', amount: -89.99, date: 'Today', icon: <ShoppingCartIcon /> },
  { id: 2, description: 'Direct Deposit - Payroll', amount: 3250.00, date: 'Yesterday', icon: <TrendingUpIcon /> },
  { id: 3, description: 'Whole Foods Market', amount: -67.43, date: 'Dec 18', icon: <RestaurantIcon /> },
  { id: 4, description: 'Shell Gas Station', amount: -45.20, date: 'Dec 17', icon: <LocalGasStationIcon /> },
  { id: 5, description: 'Netflix Subscription', amount: -15.99, date: 'Dec 15', icon: <SubscriptionsIcon /> },
];

const quickActions = [
  { label: 'Transfer Money', icon: <SwapHorizIcon />, path: '/transfers' },
  { label: 'Pay Bills', icon: <PaymentIcon />, path: '/transfers' },
  { label: 'View Statements', icon: <ReceiptLongIcon />, path: '/transactions' },
  { label: 'Chat Assistant', icon: <ChatIcon />, path: '/chat' },
];

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuthContext();

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
        {mockAccounts.map((account) => (
          <Grid key={account.number} size={{ xs: 12, md: 4 }}>
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
                {mockTransactions.map((tx, index) => (
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
                          {tx.icon}
                        </Avatar>
                      </ListItemIcon>
                      <ListItemText
                        primary={tx.description}
                        secondary={tx.date}
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
        </Grid>
      </Grid>
    </Box>
  );
};

export default Dashboard;
