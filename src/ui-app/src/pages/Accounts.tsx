import React, { useState } from 'react';
import { Box, Typography, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Button, Dialog, DialogTitle, DialogContent, DialogActions, TextField, MenuItem, Alert } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { useAuth } from '../context/AuthContext';

const Accounts: React.FC = () => {
  const { accounts, addAccount } = useAuth();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newAccount, setNewAccount] = useState({
    name: '',
    number: '',
    balance: '',
    type: 'Checking'
  });
  const [success, setSuccess] = useState(false);

  const handleAddAccount = () => {
    if (newAccount.name && newAccount.number && newAccount.balance) {
      addAccount({
        name: newAccount.name,
        number: newAccount.number,
        balance: parseFloat(newAccount.balance),
        type: newAccount.type
      });
      setSuccess(true);
      setDialogOpen(false);
      setNewAccount({
        name: '',
        number: '',
        balance: '',
        type: 'Checking'
      });
      setTimeout(() => setSuccess(false), 3000);
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

      {/* Add Account Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add New Account</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 1 }}>
            <TextField
              fullWidth
              label="Account Name"
              value={newAccount.name}
              onChange={(e) => setNewAccount({...newAccount, name: e.target.value})}
              margin="dense"
              placeholder="e.g., My Savings Account"
            />
            <TextField
              fullWidth
              label="Account Number"
              value={newAccount.number}
              onChange={(e) => setNewAccount({...newAccount, number: e.target.value})}
              margin="dense"
              placeholder="e.g., ****-5678"
            />
            <TextField
              fullWidth
              label="Initial Balance"
              type="number"
              value={newAccount.balance}
              onChange={(e) => setNewAccount({...newAccount, balance: e.target.value})}
              margin="dense"
            />
            <TextField
              fullWidth
              select
              label="Account Type"
              value={newAccount.type}
              onChange={(e) => setNewAccount({...newAccount, type: e.target.value})}
              margin="dense"
            >
              <MenuItem value="Checking">Checking</MenuItem>
              <MenuItem value="Savings">Savings</MenuItem>
              <MenuItem value="Credit">Credit Card</MenuItem>
              <MenuItem value="Investment">Investment</MenuItem>
            </TextField>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>
            Cancel
          </Button>
          <Button 
            onClick={handleAddAccount} 
            variant="contained"
            disabled={!newAccount.name || !newAccount.number || !newAccount.balance}
          >
            Add Account
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Accounts;