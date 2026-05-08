import React, { useState, useEffect, useCallback } from 'react';
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
  MenuItem,
  Autocomplete
} from '@mui/material';
import { Warning as WarningIcon, CheckCircle as CheckCircleIcon, Add as AddIcon } from '@mui/icons-material';
import { useAuthContext } from '../contexts/AuthContext';
import { useAccountContext } from '../contexts/AccountContext';
import AddAccountDialog from '../components/AddAccountDialog';
import apiClient from '../api/client';

interface Transaction {
  id: string;
  accountId: string;
  date: string;
  description: string;
  amount: number;
  category?: string;
  type?: string;
  riskScore?: number;
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
  const { token } = useAuthContext();
  const { accounts, addAccount } = useAccountContext();
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
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
  const [userCategories, setUserCategories] = useState<string[]>([]);

  // Update default accountId when accounts load
  useEffect(() => {
    if (accounts.length > 0 && newTransaction.accountId === 'acc-001') {
      setNewTransaction(prev => ({ ...prev, accountId: accounts[0].id }));
    }
  }, [accounts, newTransaction.accountId]);

  // Load user-defined category preferences for autocomplete
  useEffect(() => {
    const loadCategories = async () => {
      try {
        const res = await apiClient.get('/users/me/categories');
        setUserCategories(res.data.categories || []);
      } catch { /* no categories */ }
    };
    loadCategories();
  }, []);

  const fetchTransactions = useCallback(async () => {
    try {
      setLoading(true);
      const [txResponse, scoredResponse] = await Promise.all([
        apiClient.get('/transactions/my'),
        apiClient.get('/admin/transactions').catch(() => ({ data: [] })),
      ]);
      const data = Array.isArray(txResponse.data) ? txResponse.data : (txResponse.data.transactions || []);
      const scored = Array.isArray(scoredResponse.data) ? scoredResponse.data : [];

      // Build lookup by transactionId for risk scores and AI categories
      const scoreMap = new Map<string, { riskScore: number; explanation: string; category?: string }>();
      for (const s of scored) {
        if (s.transactionId) {
          scoreMap.set(s.transactionId, { riskScore: s.riskScore, explanation: s.explanation, category: s.category });
        }
      }

      setTransactions(data.map((t: Record<string, unknown>) => {
        const score = scoreMap.get(t.id as string);
        return {
          id: t.id as string,
          accountId: t.accountId as string,
          date: t.timestamp as string,
          description: t.description as string,
          amount: t.amount as number,
          category: (score?.category && score.category !== 'Uncategorized' ? score.category : null) 
            || (t.category as string | undefined) 
            || undefined,
          type: t.type as string | undefined,
          riskScore: score?.riskScore,
          aiExplanation: score?.explanation,
        };
      }));
    } catch (e) {
      setError('Failed to load transactions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (token) {
      fetchTransactions();
    }
  }, [token, fetchTransactions]);

  const handleSubmitTransaction = async () => {
    setSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      const response = await apiClient.post('/transactions', {
        accountId: newTransaction.accountId,
        amount: parseFloat(newTransaction.amount),
        type: newTransaction.type,
        description: newTransaction.description,
        category: newTransaction.category || undefined,
        autoCategorize: newTransaction.autoCategorize
      });

      if (response.status === 200 || response.status === 201) {
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
        await fetchTransactions();
      }
    } catch (e) {
      setError('Failed to connect to transaction service');
    } finally {
      setSubmitting(false);
    }
  };

  const handleAddAccount = async (account: { name: string; number: string; balance: number; type: string }) => {
    try {
      await addAccount(account);
      setAccountDialogOpen(false);
    } catch (e) {
      console.error('Failed to add account:', e);
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
              <TableCell>Account</TableCell>
              <TableCell>Description</TableCell>
              <TableCell align="right">Amount</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Risk</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {transactions.map((txn) => {
              const account = accounts.find(a => a.id === txn.accountId);
              return (
                <TableRow key={txn.id}>
                  <TableCell>
                    {new Date(txn.date).toLocaleDateString()}
                  </TableCell>
                  <TableCell>
                    {account ? `${account.name} (${account.number})` : txn.accountId?.slice(0, 8) || '—'}
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{txn.description}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {txn.category || 'Uncategorized'}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography color={txn.amount < 0 ? 'error' : 'success.main'} sx={{ fontWeight: 500 }}>
                      ${Math.abs(txn.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip label={txn.type || 'Unknown'} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell>
                    {txn.riskScore == null ? (
                      <Chip label="Unscored" size="small" variant="outlined" />
                    ) : txn.riskScore >= 0.7 ? (
                      <Chip
                        icon={<WarningIcon />}
                        label={`High (${txn.riskScore.toFixed(2)})`}
                        color="error"
                        size="small"
                        title={txn.aiExplanation || 'Suspicious transaction'}
                      />
                    ) : txn.riskScore >= 0.3 ? (
                      <Chip
                        icon={<WarningIcon />}
                        label={`Medium (${txn.riskScore.toFixed(2)})`}
                        color="warning"
                        size="small"
                        title={txn.aiExplanation}
                      />
                    ) : (
                      <Chip
                        icon={<CheckCircleIcon />}
                        label={`Normal (${txn.riskScore.toFixed(2)})`}
                        color="success"
                        size="small"
                      />
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Add Transaction Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add New Transaction</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 1 }}>
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-end' }}>
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
              <Button
                variant="outlined"
                size="small"
                onClick={() => setAccountDialogOpen(true)}
                sx={{ mb: 1, minWidth: 'auto' }}
                title="Add new account"
              >
                <AddIcon />
              </Button>
            </Box>
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
            <Autocomplete
              freeSolo
              options={userCategories}
              value={newTransaction.category || ''}
              onInputChange={(_e, value) => setNewTransaction({...newTransaction, category: value})}
              disabled={newTransaction.autoCategorize}
              renderInput={(params) => (
                <TextField
                  {...params}
                  fullWidth
                  label="Category (optional)"
                  margin="dense"
                  helperText={newTransaction.autoCategorize ? "AI will auto-categorize" : "Type or pick from your saved categories"}
                />
              )}
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

      {/* Shared Add Account Dialog */}
      <AddAccountDialog
        open={accountDialogOpen}
        onClose={() => setAccountDialogOpen(false)}
        onAdd={handleAddAccount}
      />
    </Box>
  );
};

export default Transactions;