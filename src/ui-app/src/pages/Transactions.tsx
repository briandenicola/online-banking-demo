import React, { useState, useEffect } from 'react';
import { 
  Box, 
  Typography, 
  Paper, 
  Table, 
  TableBody, 
  TableCell, 
  TableContainer, 
  TableHead, 
  TableRow,
  Chip,
  Alert,
  CircularProgress,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem
} from '@mui/material';
import { Warning as WarningIcon, CheckCircle as CheckCircleIcon, Add as AddIcon } from '@mui/icons-material';
import { useAuth } from '../context/AuthContext';

interface Transaction {
  id: string;
  date: string;
  description: string;
  amount: number;
  balance: number;
  category?: string;
  isAnomalous?: boolean;
  aiExplanation?: string;
}

interface NewTransaction {
  accountId: string;
  amount: string;
  type: string;
  description: string;
  category?: string;
  autoCategorize: boolean;
}

const Transactions: React.FC = () => {
  const { accounts } = useAuth();
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [newTransaction, setNewTransaction] = useState<NewTransaction>({
    accountId: accounts.length > 0 ? accounts[0].id : 'acc-001',
    amount: '',
    type: 'Debit',
    description: '',
    category: '',
    autoCategorize: true
  });
  const [success, setSuccess] = useState<string | null>(null);

  // Update default accountId when accounts load
  useEffect(() => {
    if (accounts.length > 0 && newTransaction.accountId === 'acc-001') {
      setNewTransaction(prev => ({ ...prev, accountId: accounts[0].id }));
    }
  }, [accounts, newTransaction.accountId]);

  // Fetch transactions from the transaction service
  const fetchTransactions = async () => {
    try {
      setLoading(true);
      // In production, this would call the transaction service
      // For demo, we use mock data but check each for anomalies
      const mockData: Transaction[] = [
        { id: '1', date: '2026-05-04', description: 'Grocery Store', amount: -87.56, balance: 2543.78 },
        { id: '2', date: '2026-05-03', description: 'Paycheck Deposit', amount: 3500.00, balance: 2631.34 },
        { id: '3', date: '2026-05-02', description: 'Gas Station', amount: -45.30, balance: -868.66 },
        { id: '4', date: '2026-05-01', description: 'Online Transfer', amount: -500.00, balance: -913.96 },
      ];

      // Check each transaction for anomalies using the anomaly service
      const checkedTransactions = await Promise.all(
        mockData.map(async (txn) => {
          try {
            const anomalyResponse = await fetch('/api/anomaly/detect', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                id: txn.id,
                transactionId: txn.id,
                accountId: 'acc-001',
                amount: Math.abs(txn.amount),
                type: txn.amount < 0 ? 'Debit' : 'Credit',
                category: 'Uncategorized',
                description: txn.description
              })
            });
            
            if (anomalyResponse.ok) {
              const anomaly = await anomalyResponse.json();
              return { ...txn, isAnomalous: anomaly.isAnomalous, aiExplanation: anomaly.aiExplanation };
            }
            return txn;
          } catch (e) {
            return txn;
          }
        })
      );

      // Categorize uncategorized transactions using the budget service
      const categorizedTransactions = await Promise.all(
        checkedTransactions.map(async (txn) => {
          try {
            const catResponse = await fetch(`/api/budget/categorize?description=${encodeURIComponent(txn.description)}`);
            if (catResponse.ok) {
              const cat = await catResponse.json();
              return { ...txn, category: cat.category };
            }
            return { ...txn, category: 'Uncategorized' };
          } catch (e) {
            return { ...txn, category: 'Uncategorized' };
          }
        })
      );

      setTransactions(categorizedTransactions);
    } catch (e) {
      setError('Failed to load transactions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTransactions();
  }, []);

  const handleSubmitTransaction = async () => {
    setSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      const response = await fetch('/api/transactions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          accountId: newTransaction.accountId,
          amount: parseFloat(newTransaction.amount),
          type: newTransaction.type,
          description: newTransaction.description,
          category: newTransaction.category || undefined,
          autoCategorize: newTransaction.autoCategorize
        })
      });

      if (response.ok) {
        const selectedAccount = accounts.find(a => a.id === newTransaction.accountId);
        setSuccess(`Transaction added to ${selectedAccount?.name || 'account'}! AI categorization will run automatically.`);
        setDialogOpen(false);
        setNewTransaction({
          accountId: accounts.length > 0 ? accounts[0].id : 'acc-001',
          amount: '',
          type: 'Debit',
          description: '',
          category: '',
          autoCategorize: true
        });
        // Refresh transactions
        await fetchTransactions();
      } else {
        const error = await response.text();
        setError(error || 'Failed to add transaction');
      }
    } catch (e) {
      setError('Failed to connect to transaction service');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '200px' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h4">
          Transactions
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setDialogOpen(true)}
        >
          Add Transaction
        </Button>
      </Box>
      
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}
      
      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Description</TableCell>
              <TableCell>Category</TableCell>
              <TableCell align="right">Amount</TableCell>
              <TableCell align="right">Balance</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {transactions.map((txn) => (
              <TableRow key={txn.id}>
                <TableCell>{txn.date}</TableCell>
                <TableCell>{txn.description}</TableCell>
                <TableCell>
                  <Chip label={txn.category || 'Uncategorized'} size="small" variant="outlined" />
                </TableCell>
                <TableCell align="right">
                  <Typography color={txn.amount < 0 ? 'error' : 'success'}>
                    ${Math.abs(txn.amount).toFixed(2)}
                  </Typography>
                </TableCell>
                <TableCell align="right">${txn.balance.toFixed(2)}</TableCell>
                <TableCell>
                  {txn.isAnomalous ? (
                    <Chip
                      icon={<WarningIcon />}
                      label="Flagged"
                      color="error"
                      size="small"
                      title={txn.aiExplanation || 'Suspicious transaction'}
                    />
                  ) : (
                    <Chip
                      icon={<CheckCircleIcon />}
                      label="Normal"
                      color="success"
                      size="small"
                    />
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Add Transaction Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add New Transaction</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 1 }}>
            <TextField
              fullWidth
              select
              label="Account"
              value={newTransaction.accountId}
              onChange={(e) => setNewTransaction({...newTransaction, accountId: e.target.value})}
              margin="dense"
              required
              helperText="Select the account for this transaction"
            >
              {accounts.map((account) => (
                <MenuItem key={account.id} value={account.id}>
                  {account.name} ({account.number}) - ${Math.abs(account.balance).toFixed(2)} {account.balance < 0 ? 'CR' : 'DR'}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              fullWidth
              label="Amount"
              type="number"
              value={newTransaction.amount}
              onChange={(e) => setNewTransaction({...newTransaction, amount: e.target.value})}
              margin="dense"
              required
              helperText="Positive for deposits, negative for withdrawals"
            />
            <TextField
              fullWidth
              select
              label="Type"
              value={newTransaction.type}
              onChange={(e) => setNewTransaction({...newTransaction, type: e.target.value})}
              margin="dense"
            >
              <MenuItem value="Debit">Debit</MenuItem>
              <MenuItem value="Credit">Credit</MenuItem>
              <MenuItem value="Transfer">Transfer</MenuItem>
            </TextField>
            <TextField
              fullWidth
              label="Description"
              value={newTransaction.description}
              onChange={(e) => setNewTransaction({...newTransaction, description: e.target.value})}
              margin="dense"
              required
              placeholder="e.g., Starbucks Coffee, Amazon Purchase"
            />
            <TextField
              fullWidth
              label="Category (optional)"
              value={newTransaction.category}
              onChange={(e) => setNewTransaction({...newTransaction, category: e.target.value})}
              margin="dense"
              disabled={newTransaction.autoCategorize}
              helperText={newTransaction.autoCategorize ? "AI will auto-categorize" : "Leave empty for manual"}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button 
            onClick={handleSubmitTransaction} 
            variant="contained" 
            disabled={submitting || !newTransaction.amount || !newTransaction.description}
          >
            {submitting ? <CircularProgress size={20} /> : 'Add Transaction'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Transactions;