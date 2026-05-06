import React from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem,
  Button,
  Box,
} from '@mui/material';

interface AddAccountDialogProps {
  open: boolean;
  onClose: () => void;
  onAdd: (account: { name: string; number: string; balance: number; type: string }) => void;
}

const AddAccountDialog: React.FC<AddAccountDialogProps> = ({ open, onClose, onAdd }) => {
  const [newAccount, setNewAccount] = React.useState({
    name: '',
    number: '',
    balance: '',
    type: 'Checking',
  });

  const handleAdd = () => {
    if (newAccount.name && newAccount.number && newAccount.balance) {
      onAdd({
        name: newAccount.name,
        number: newAccount.number,
        balance: parseFloat(newAccount.balance),
        type: newAccount.type,
      });
      setNewAccount({ name: '', number: '', balance: '', type: 'Checking' });
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add New Account</DialogTitle>
      <DialogContent>
        <Box sx={{ pt: 1 }}>
          <TextField
            fullWidth
            label="Account Name"
            value={newAccount.name}
            onChange={(e) => setNewAccount({ ...newAccount, name: e.target.value })}
            margin="dense"
            placeholder="e.g., My Savings Account"
          />
          <TextField
            fullWidth
            label="Account Number"
            value={newAccount.number}
            onChange={(e) => setNewAccount({ ...newAccount, number: e.target.value })}
            margin="dense"
            placeholder="e.g., ****-5678"
          />
          <TextField
            fullWidth
            label="Initial Balance"
            type="number"
            value={newAccount.balance}
            onChange={(e) => setNewAccount({ ...newAccount, balance: e.target.value })}
            margin="dense"
          />
          <TextField
            fullWidth
            select
            label="Account Type"
            value={newAccount.type}
            onChange={(e) => setNewAccount({ ...newAccount, type: e.target.value })}
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
        <Button onClick={onClose}>Cancel</Button>
        <Button
          onClick={handleAdd}
          variant="contained"
          disabled={!newAccount.name || !newAccount.number || !newAccount.balance}
        >
          Add Account
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default AddAccountDialog;
