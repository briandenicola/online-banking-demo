import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Grid,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  IconButton,
  Button,
  Collapse,
  CircularProgress,
  Alert,
  Tooltip,
  TableSortLabel,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import RateReviewIcon from '@mui/icons-material/RateReview';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import SecurityIcon from '@mui/icons-material/Security';
import PendingActionsIcon from '@mui/icons-material/PendingActions';
import VerifiedIcon from '@mui/icons-material/Verified';
import apiClient from '../api/client';

interface AdminStats {
  totalFlagged: number;
  pendingReview: number;
  cleared: number;
  avgRiskScore: number;
}

interface FlaggedTransaction {
  id: string;
  date: string;
  account: string;
  amount: number;
  type: string;
  riskScore: number;
  reason: string;
  status: string;
  riskAssessment?: string;
}

type SortField = 'date' | 'amount' | 'riskScore' | 'status';
type SortDirection = 'asc' | 'desc';

const getRiskColor = (score: number): 'error' | 'warning' | 'info' | 'success' => {
  if (score > 0.8) return 'error';
  if (score > 0.6) return 'warning';
  if (score > 0.4) return 'info';
  return 'success';
};

const getStatusChip = (status: string) => {
  switch (status.toLowerCase()) {
    case 'pending':
      return <Chip label="Pending" color="warning" size="small" />;
    case 'reviewed':
      return <Chip label="Reviewed" color="info" size="small" />;
    case 'cleared':
      return <Chip label="Cleared" color="success" size="small" />;
    default:
      return <Chip label={status} size="small" />;
  }
};

const AdminPage: React.FC = () => {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [transactions, setTransactions] = useState<FlaggedTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>('riskScore');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [statsRes, txRes] = await Promise.all([
        apiClient.get('/admin/stats'),
        apiClient.get('/admin/flagged-transactions'),
      ]);
      setStats(statsRes.data);
      setTransactions(txRes.data);
    } catch (err) {
      setError('Failed to load admin data. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleAction = async (id: string, action: 'review' | 'clear') => {
    setActionLoading(id);
    try {
      await apiClient.put(`/admin/flagged-transactions/${id}/review`, { action });
      await fetchData();
    } catch {
      setError(`Failed to ${action} transaction. Please try again.`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const sortedTransactions = [...transactions].sort((a, b) => {
    const modifier = sortDirection === 'asc' ? 1 : -1;
    switch (sortField) {
      case 'date':
        return modifier * (new Date(a.date).getTime() - new Date(b.date).getTime());
      case 'amount':
        return modifier * (a.amount - b.amount);
      case 'riskScore':
        return modifier * (a.riskScore - b.riskScore);
      case 'status':
        return modifier * a.status.localeCompare(b.status);
      default:
        return 0;
    }
  });

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4" gutterBottom>
            Admin Dashboard
          </Typography>
          <Typography variant="subtitle1" color="text.secondary">
            Monitor and review flagged transactions
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={<RefreshIcon />}
          onClick={fetchData}
        >
          Refresh
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Stats Cards */}
      {stats && (
        <Grid container spacing={3} sx={{ mb: 4 }}>
          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card>
              <CardContent sx={{ textAlign: 'center' }}>
                <WarningAmberIcon color="error" sx={{ fontSize: 40 }} />
                <Typography variant="h4" sx={{ mt: 1 }}>
                  {stats.totalFlagged}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Total Flagged
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card>
              <CardContent sx={{ textAlign: 'center' }}>
                <PendingActionsIcon color="warning" sx={{ fontSize: 40 }} />
                <Typography variant="h4" sx={{ mt: 1 }}>
                  {stats.pendingReview}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Pending Review
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card>
              <CardContent sx={{ textAlign: 'center' }}>
                <VerifiedIcon color="success" sx={{ fontSize: 40 }} />
                <Typography variant="h4" sx={{ mt: 1 }}>
                  {stats.cleared}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Cleared
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card>
              <CardContent sx={{ textAlign: 'center' }}>
                <SecurityIcon color="info" sx={{ fontSize: 40 }} />
                <Typography variant="h4" sx={{ mt: 1 }}>
                  {stats.avgRiskScore.toFixed(2)}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Avg Risk Score
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Flagged Transactions Table */}
      <TableContainer component={Paper} elevation={2}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell />
              <TableCell>
                <TableSortLabel
                  active={sortField === 'date'}
                  direction={sortField === 'date' ? sortDirection : 'asc'}
                  onClick={() => handleSort('date')}
                >
                  Date
                </TableSortLabel>
              </TableCell>
              <TableCell>Account</TableCell>
              <TableCell>
                <TableSortLabel
                  active={sortField === 'amount'}
                  direction={sortField === 'amount' ? sortDirection : 'asc'}
                  onClick={() => handleSort('amount')}
                >
                  Amount
                </TableSortLabel>
              </TableCell>
              <TableCell>Type</TableCell>
              <TableCell>
                <TableSortLabel
                  active={sortField === 'riskScore'}
                  direction={sortField === 'riskScore' ? sortDirection : 'asc'}
                  onClick={() => handleSort('riskScore')}
                >
                  Risk Score
                </TableSortLabel>
              </TableCell>
              <TableCell>Reason</TableCell>
              <TableCell>
                <TableSortLabel
                  active={sortField === 'status'}
                  direction={sortField === 'status' ? sortDirection : 'asc'}
                  onClick={() => handleSort('status')}
                >
                  Status
                </TableSortLabel>
              </TableCell>
              <TableCell>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sortedTransactions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} align="center">
                  <Typography variant="body1" sx={{ py: 4 }} color="text.secondary">
                    No flagged transactions found.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              sortedTransactions.map((tx) => (
                <React.Fragment key={tx.id}>
                  <TableRow
                    hover
                    sx={{ cursor: 'pointer' }}
                    onClick={() => setExpandedRow(expandedRow === tx.id ? null : tx.id)}
                  >
                    <TableCell>
                      <IconButton size="small">
                        {expandedRow === tx.id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                      </IconButton>
                    </TableCell>
                    <TableCell>
                      {new Date(tx.date).toLocaleDateString()}
                    </TableCell>
                    <TableCell>{tx.account}</TableCell>
                    <TableCell>
                      ${tx.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </TableCell>
                    <TableCell>{tx.type}</TableCell>
                    <TableCell>
                      <Chip
                        label={tx.riskScore.toFixed(2)}
                        color={getRiskColor(tx.riskScore)}
                        size="small"
                        variant="filled"
                      />
                    </TableCell>
                    <TableCell>{tx.reason}</TableCell>
                    <TableCell>{getStatusChip(tx.status)}</TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 0.5 }} onClick={(e) => e.stopPropagation()}>
                        <Tooltip title="Mark as Reviewed">
                          <IconButton
                            size="small"
                            color="info"
                            onClick={() => handleAction(tx.id, 'review')}
                            disabled={actionLoading === tx.id || tx.status === 'reviewed'}
                          >
                            {actionLoading === tx.id ? (
                              <CircularProgress size={20} />
                            ) : (
                              <RateReviewIcon />
                            )}
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Clear Transaction">
                          <IconButton
                            size="small"
                            color="success"
                            onClick={() => handleAction(tx.id, 'clear')}
                            disabled={actionLoading === tx.id || tx.status === 'cleared'}
                          >
                            <CheckCircleIcon />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell colSpan={9} sx={{ py: 0, borderBottom: expandedRow === tx.id ? undefined : 'none' }}>
                      <Collapse in={expandedRow === tx.id} timeout="auto" unmountOnExit>
                        <Box sx={{ py: 2, px: 3 }}>
                          <Typography variant="subtitle2" gutterBottom>
                            Risk Assessment Details
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            {tx.riskAssessment || `Transaction flagged due to: ${tx.reason}. Risk score: ${tx.riskScore.toFixed(2)}. Current status: ${tx.status}.`}
                          </Typography>
                          <Box sx={{ mt: 1 }}>
                            <Typography variant="caption" color="text.secondary">
                              Transaction ID: {tx.id} | Date: {new Date(tx.date).toLocaleString()} | Account: {tx.account}
                            </Typography>
                          </Box>
                        </Box>
                      </Collapse>
                    </TableCell>
                  </TableRow>
                </React.Fragment>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default AdminPage;
