import React from 'react';
import { Box, Typography, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';

const Transactions: React.FC = () => {
  const transactions = [
    { id: '1', date: '2026-05-04', description: 'Grocery Store', amount: -87.56, balance: 2543.78 },
    { id: '2', date: '2026-05-03', description: 'Paycheck Deposit', amount: 3500.00, balance: 2631.34 },
    { id: '3', date: '2026-05-02', description: 'Gas Station', amount: -45.30, balance: -868.66 },
    { id: '4', date: '2026-05-01', description: 'Online Transfer', amount: -500.00, balance: -913.96 },
  ];

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Transactions
      </Typography>
      
      <TableContainer component={Paper} sx={{ mt: 2 }}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Description</TableCell>
              <TableCell align="right">Amount</TableCell>
              <TableCell align="right">Balance</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {transactions.map((txn) => (
              <TableRow key={txn.id}>
                <TableCell>{txn.date}</TableCell>
                <TableCell>{txn.description}</TableCell>
                <TableCell align="right">
                  <Typography color={txn.amount < 0 ? 'error' : 'success'}>
                    ${Math.abs(txn.amount).toFixed(2)}
                  </Typography>
                </TableCell>
                <TableCell align="right">${txn.balance.toFixed(2)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default Transactions;