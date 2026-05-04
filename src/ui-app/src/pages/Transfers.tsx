import React, { useState } from 'react';
import { Box, Typography, Paper, TextField, Button, MenuItem, Alert } from '@mui/material';
import { useAuth } from '../context/AuthContext';

const Transfers: React.FC = () => {
  const [fromAccount, setFromAccount] = useState('');
  const [toAccount, setToAccount] = useState('');
  const [amount, setAmount] = useState('');
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');
  const { accounts, transfer } = useAuth();

  const eligibleAccounts = accounts.filter(acc => acc.type !== 'Credit');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    
    const amt = parseFloat(amount);
    if (isNaN(amt) || amt <= 0) {
      setError('Please enter a valid amount');
      return;
    }

    const fromAcc = accounts.find(a => a.id === fromAccount);
    if (fromAcc && fromAcc.balance < amt) {
      setError('Insufficient funds');
      return;
    }

    if (fromAccount === toAccount) {
      setError('Cannot transfer to the same account');
      return;
    }

    transfer(fromAccount, toAccount, amt);
    setSuccess(true);
    setAmount('');
    setTimeout(() => setSuccess(false), 3000);
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Make a Transfer
      </Typography>
      
      <Paper sx={{ p: 3, maxWidth: 500, mt: 2 }}>
        {success && <Alert severity="success" sx={{ mb: 2 }}>Transfer completed successfully!</Alert>}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        
        <Box component="form" onSubmit={handleSubmit}>
          <TextField
            select
            label="From Account"
            value={fromAccount}
            onChange={(e) => setFromAccount(e.target.value)}
            fullWidth
            margin="normal"
            required
          >
            {eligibleAccounts.map((option) => (
              <MenuItem key={option.id} value={option.id}>
                {option.name} ({option.number}) - ${option.balance.toFixed(2)}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            label="To Account"
            value={toAccount}
            onChange={(e) => setToAccount(e.target.value)}
            fullWidth
            margin="normal"
            required
          >
            {eligibleAccounts
              .filter(acc => acc.id !== fromAccount)
              .map((option) => (
                <MenuItem key={option.id} value={option.id}>
                  {option.name} ({option.number})
                </MenuItem>
              ))}
          </TextField>

          <TextField
            label="Amount"
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            fullWidth
            margin="normal"
            required
          />

          <Button type="submit" variant="contained" fullWidth sx={{ mt: 2 }}>
            Send Transfer
          </Button>
        </Box>
      </Paper>
    </Box>
  );
};

export default Transfers;