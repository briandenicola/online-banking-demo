import React from 'react';
import { Box, Typography, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Button } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { useAuth } from '../context/AuthContext';

const Accounts: React.FC = () => {
  const { accounts } = useAuth();

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Accounts
      </Typography>
      
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

      <Button variant="contained" startIcon={<AddIcon />} sx={{ mt: 2 }} disabled>
        Open New Account
      </Button>
    </Box>
  );
};

export default Accounts;