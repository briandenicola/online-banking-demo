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
  CircularProgress
} from '@mui/material';
import { Warning as WarningIcon, CheckCircle as CheckCircleIcon } from '@mui/icons-material';

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

const Transactions: React.FC = () => {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch transactions from the transaction service
  useEffect(() => {
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

    fetchTransactions();
  }, []);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '200px' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Transactions
      </Typography>
      
      {error && <Alert severity="error">{error}</Alert>}
      
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
    </Box>
  );
};

export default Transactions;