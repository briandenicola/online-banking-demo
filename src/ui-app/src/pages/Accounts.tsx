import React, { useState } from 'react';
import { Box, Typography, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Button, Alert } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { useAccountContext } from '../contexts/AccountContext';
import AddAccountDialog from '../components/AddAccountDialog';
import { logger } from '../utils/logger';

const Accounts: React.FC = () => {
  const { accounts, addAccount } = useAccountContext();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAddAccount = async (account: { name: string; number: string; balance: number; type: string }) => {
    try {
      setError(null);
      await addAccount(account);
      setSuccess(true);
      setDialogOpen(false);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e) {
      logger.error('Failed to add account', e);
      setError('Failed to add account. Please try again.');
      setTimeout(() => setError(null), 5000);
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h4">
          Accounts
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setDialogOpen(true)}
        >
          Add Account
        </Button>
      </Box>

      {success && <Alert severity="success" sx={{ mb: 2 }}>Account added successfully!</Alert>}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      
      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Account Name</TableCell>
              <TableCell>Account Number</TableCell>
              <TableCell>Type</TableCell>
              <TableCell align="right">Balance</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {accounts.map((account) => (
              <TableRow key={account.id}>
                <TableCell>{account.name}</TableCell>
                <TableCell>{account.number}</TableCell>
                <TableCell>{account.type}</TableCell>
                <TableCell align="right">
                  <Typography color={account.balance < 0 ? 'error' : 'success'}>
                    ${Math.abs(account.balance).toFixed(2)}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <AddAccountDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onAdd={handleAddAccount}
      />
    </Box>
  );
};

export default Accounts;