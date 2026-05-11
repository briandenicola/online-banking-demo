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
  Tabs,
  Tab,
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
import AssessmentIcon from '@mui/icons-material/Assessment';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import ReplayIcon from '@mui/icons-material/Replay';
import apiClient from '../api/client';
import AdminEvalTab from '../components/AdminEvalTab';
import AdminUserManagementTab from '../components/AdminUserManagementTab';
import AdminLoginAuditTab from '../components/AdminLoginAuditTab';
import AdminFoundryStatusTab from '../components/AdminFoundryStatusTab';

interface AdminStats {
  totalFlagged: number;
  pendingReview: number;
  cleared: number;
  avgRiskScore: number;
  totalScored: number;
  highRiskCount: number;
  aiCallsToday: number;
}

interface FlaggedTransaction {
  id: string;
  transactionId: string;
  accountId: string;
  amount: number;
  type: string;
  riskScore: number;
  reason: string;
  flags: string[];
  flaggedAt: string;
  status: string;
  notes?: string;
}

interface ScoredTransaction {
  id: string;
  transactionId: string;
  accountId: string;
  amount: number;
  type: string;
  description: string;
  category: string;
  categoryConfidence: number;
  categoryReasoning: string;
  riskScore: number;
  explanation: string;
  flags: string[];
  scoredAt: string;
  status: string;
  notes?: string;
}

type FlaggedSortField = 'flaggedAt' | 'amount' | 'riskScore' | 'status';
type AllSortField = 'scoredAt' | 'amount' | 'riskScore';
type SortDirection = 'asc' | 'desc';

const getRiskColor = (score: number): 'error' | 'warning' | 'success' => {
  if (score > 0.7) return 'error';
  if (score > 0.3) return 'warning';
  return 'success';
};

const getRiskChipSx = (score: number) => {
  if (score > 0.7) return {};
  if (score > 0.5) return { bgcolor: '#ed6c02', color: '#fff' };
  if (score > 0.3) return { bgcolor: '#ffc107', color: 'rgba(0,0,0,0.87)' };
  return {};
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
  const [activeTab, setActiveTab] = useState(0);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [flaggedTransactions, setFlaggedTransactions] = useState<FlaggedTransaction[]>([]);
  const [allTransactions, setAllTransactions] = useState<ScoredTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [flaggedSortField, setFlaggedSortField] = useState<FlaggedSortField>('riskScore');
  const [flaggedSortDirection, setFlaggedSortDirection] = useState<SortDirection>('desc');
  const [allSortField, setAllSortField] = useState<AllSortField>('riskScore');
  const [allSortDirection, setAllSortDirection] = useState<SortDirection>('desc');
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [statsRes, flaggedRes, allRes] = await Promise.all([
        apiClient.get('/admin/stats'),
        apiClient.get('/admin/flagged-transactions'),
        apiClient.get('/admin/transactions'),
      ]);
      setStats(statsRes.data);
      setFlaggedTransactions(flaggedRes.data);
      setAllTransactions(allRes.data);
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
      const status = action === 'review' ? 'reviewed' : 'cleared';
      await apiClient.put(`/admin/flagged-transactions/${id}/review`, { status, notes: `Marked as ${status} by admin` });
      await fetchData();
    } catch {
      setError(`Failed to ${action} transaction. Please try again.`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleRescore = async (id: string) => {
    setActionLoading(id);
    try {
      await apiClient.post(`/admin/scored-transactions/${id}/rescore`);
      await fetchData();
    } catch {
      setError('Failed to rescore transaction. Please try again.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleFlaggedSort = (field: FlaggedSortField) => {
    if (flaggedSortField === field) {
      setFlaggedSortDirection(flaggedSortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setFlaggedSortField(field);
      setFlaggedSortDirection('desc');
    }
  };

  const handleAllSort = (field: AllSortField) => {
    if (allSortField === field) {
      setAllSortDirection(allSortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setAllSortField(field);
      setAllSortDirection('desc');
    }
  };

  const sortedFlaggedTransactions = [...flaggedTransactions].sort((a, b) => {
    const modifier = flaggedSortDirection === 'asc' ? 1 : -1;
    switch (flaggedSortField) {
      case 'flaggedAt':
        return modifier * (new Date(a.flaggedAt).getTime() - new Date(b.flaggedAt).getTime());
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

  const sortedAllTransactions = [...allTransactions].sort((a, b) => {
    const modifier = allSortDirection === 'asc' ? 1 : -1;
    switch (allSortField) {
      case 'scoredAt':
        return modifier * (new Date(a.scoredAt).getTime() - new Date(b.scoredAt).getTime());
      case 'amount':
        return modifier * (a.amount - b.amount);
      case 'riskScore':
        return modifier * (a.riskScore - b.riskScore);
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
          <Grid size={{ xs: 12, sm: 6, md: 2 }}>
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
          <Grid size={{ xs: 12, sm: 6, md: 2 }}>
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
          <Grid size={{ xs: 12, sm: 6, md: 2 }}>
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
          <Grid size={{ xs: 12, sm: 6, md: 2 }}>
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
          <Grid size={{ xs: 12, sm: 6, md: 2 }}>
            <Card>
              <CardContent sx={{ textAlign: 'center' }}>
                <AssessmentIcon color="primary" sx={{ fontSize: 40 }} />
                <Typography variant="h4" sx={{ mt: 1 }}>
                  {stats.totalScored}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Total Scored
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 2 }}>
            <Card>
              <CardContent sx={{ textAlign: 'center' }}>
                <SmartToyIcon color="secondary" sx={{ fontSize: 40 }} />
                <Typography variant="h4" sx={{ mt: 1 }}>
                  {stats.aiCallsToday}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  AI Calls Today
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Tab Navigation */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={activeTab} onChange={(_, newValue) => { setActiveTab(newValue); setExpandedRow(null); }}>
          <Tab label="Flagged Transactions" />
          <Tab label="All Transactions" />
          <Tab label="AI Evaluation" />
          <Tab label="User Management" />
          <Tab label="Login Audit" />
          <Tab label="System Health" />
        </Tabs>
      </Box>

      {/* Flagged Transactions Tab */}
      {activeTab === 0 && (
        <TableContainer component={Paper} elevation={2}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell />
                <TableCell>
                  <TableSortLabel
                    active={flaggedSortField === 'flaggedAt'}
                    direction={flaggedSortField === 'flaggedAt' ? flaggedSortDirection : 'asc'}
                    onClick={() => handleFlaggedSort('flaggedAt')}
                  >
                    Date
                  </TableSortLabel>
                </TableCell>
                <TableCell>Account</TableCell>
                <TableCell>
                  <TableSortLabel
                    active={flaggedSortField === 'amount'}
                    direction={flaggedSortField === 'amount' ? flaggedSortDirection : 'asc'}
                    onClick={() => handleFlaggedSort('amount')}
                  >
                    Amount
                  </TableSortLabel>
                </TableCell>
                <TableCell>Type</TableCell>
                <TableCell>
                  <TableSortLabel
                    active={flaggedSortField === 'riskScore'}
                    direction={flaggedSortField === 'riskScore' ? flaggedSortDirection : 'asc'}
                    onClick={() => handleFlaggedSort('riskScore')}
                  >
                    Risk Score
                  </TableSortLabel>
                </TableCell>
                <TableCell>Reason</TableCell>
                <TableCell>
                  <TableSortLabel
                    active={flaggedSortField === 'status'}
                    direction={flaggedSortField === 'status' ? flaggedSortDirection : 'asc'}
                    onClick={() => handleFlaggedSort('status')}
                  >
                    Status
                  </TableSortLabel>
                </TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sortedFlaggedTransactions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} align="center">
                    <Typography variant="body1" sx={{ py: 4 }} color="text.secondary">
                      No flagged transactions found.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                sortedFlaggedTransactions.map((tx) => (
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
                        {new Date(tx.flaggedAt).toLocaleDateString()}
                      </TableCell>
                      <TableCell>{tx.accountId}</TableCell>
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
                          sx={getRiskChipSx(tx.riskScore)}
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
                              AI Explanation
                            </Typography>
                            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                              {tx.reason}
                            </Typography>

                            {tx.flags && tx.flags.length > 0 && (
                              <Box sx={{ mb: 2 }}>
                                <Typography variant="subtitle2" gutterBottom>
                                  Risk Flags
                                </Typography>
                                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                                  {tx.flags.map((flag, idx) => (
                                    <Chip key={idx} label={flag} color="error" size="small" variant="outlined" />
                                  ))}
                                </Box>
                              </Box>
                            )}

                            <Typography variant="subtitle2" gutterBottom>
                              Transaction Metadata
                            </Typography>
                            <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                              <Typography variant="body2" color="text.secondary">
                                <strong>Transaction ID:</strong> {tx.transactionId}
                              </Typography>
                              <Typography variant="body2" color="text.secondary">
                                <strong>Account:</strong> {tx.accountId}
                              </Typography>
                              <Typography variant="body2" color="text.secondary">
                                <strong>Amount:</strong> ${tx.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                              </Typography>
                              <Typography variant="body2" color="text.secondary">
                                <strong>Type:</strong> {tx.type}
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
      )}

      {/* All Transactions Tab */}
      {activeTab === 1 && (
        <TableContainer component={Paper} elevation={2}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell />
                <TableCell>
                  <TableSortLabel
                    active={allSortField === 'scoredAt'}
                    direction={allSortField === 'scoredAt' ? allSortDirection : 'asc'}
                    onClick={() => handleAllSort('scoredAt')}
                  >
                    Date
                  </TableSortLabel>
                </TableCell>
                <TableCell>Account</TableCell>
                <TableCell>
                  <TableSortLabel
                    active={allSortField === 'amount'}
                    direction={allSortField === 'amount' ? allSortDirection : 'asc'}
                    onClick={() => handleAllSort('amount')}
                  >
                    Amount
                  </TableSortLabel>
                </TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Category</TableCell>
                <TableCell>
                  <TableSortLabel
                    active={allSortField === 'riskScore'}
                    direction={allSortField === 'riskScore' ? allSortDirection : 'asc'}
                    onClick={() => handleAllSort('riskScore')}
                  >
                    Risk Score
                  </TableSortLabel>
                </TableCell>
                <TableCell>Description</TableCell>
                <TableCell align="center">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sortedAllTransactions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} align="center">
                    <Typography variant="body1" sx={{ py: 4 }} color="text.secondary">
                      No scored transactions found.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                sortedAllTransactions.map((tx) => (
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
                        {new Date(tx.scoredAt).toLocaleDateString()}
                      </TableCell>
                      <TableCell>{tx.accountId}</TableCell>
                      <TableCell>
                        ${tx.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </TableCell>
                      <TableCell>{tx.type}</TableCell>
                      <TableCell>
                        <Chip label={tx.category || 'Uncategorized'} size="small" variant="outlined" />
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={tx.riskScore.toFixed(2)}
                          color={getRiskColor(tx.riskScore)}
                          size="small"
                          variant="filled"
                          sx={getRiskChipSx(tx.riskScore)}
                        />
                      </TableCell>
                      <TableCell>{tx.description}</TableCell>
                      <TableCell align="center">
                        <Tooltip title="Resend for AI Analysis">
                          <IconButton
                            size="small"
                            color="primary"
                            disabled={actionLoading === tx.id}
                            onClick={(e) => { e.stopPropagation(); handleRescore(tx.id); }}
                          >
                            {actionLoading === tx.id ? <CircularProgress size={18} /> : <ReplayIcon />}
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell colSpan={9} sx={{ py: 0, borderBottom: expandedRow === tx.id ? undefined : 'none' }}>
                        <Collapse in={expandedRow === tx.id} timeout="auto" unmountOnExit>
                          <Box sx={{ py: 2, px: 3 }}>
                            <Typography variant="subtitle2" gutterBottom sx={{ fontWeight: 700 }}>
                              AI Processing Steps
                            </Typography>

                            {/* Step 1: Categorization */}
                            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 1.5 }}>
                              <Chip label="1" size="small" color="info" sx={{ minWidth: 24, fontWeight: 700 }} />
                              <Box>
                                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                  Categorization
                                </Typography>
                                <Typography variant="body2" color="text.secondary">
                                  Category: <strong>{tx.category || 'Uncategorized'}</strong>
                                  {tx.categoryConfidence > 0 && (
                                    <> — Confidence: {(tx.categoryConfidence * 100).toFixed(0)}%</>
                                  )}
                                </Typography>
                                {tx.categoryReasoning && (
                                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                                    {tx.categoryReasoning}
                                  </Typography>
                                )}
                              </Box>
                            </Box>

                            {/* Step 2: Risk Scoring */}
                            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 1.5 }}>
                              <Chip label="2" size="small" color="warning" sx={{ minWidth: 24, fontWeight: 700 }} />
                              <Box>
                                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                  Risk Scoring
                                </Typography>
                                <Typography variant="body2" color="text.secondary">
                                  Score: <strong>{tx.riskScore.toFixed(2)}</strong>
                                  {tx.flags.length > 0 && (
                                    <> — Flags: {tx.flags.join(', ')}</>
                                  )}
                                </Typography>
                                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                                  {tx.explanation}
                                </Typography>
                              </Box>
                            </Box>

                            {tx.notes && (
                              <Box sx={{ mt: 1, pl: 4.5 }}>
                                <Typography variant="caption" color="text.secondary">
                                  Admin notes: {tx.notes}
                                </Typography>
                              </Box>
                            )}
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
      )}

      {/* AI Evaluation Tab */}
      {activeTab === 2 && <AdminEvalTab />}

      {/* User Management Tab */}
      {activeTab === 3 && <AdminUserManagementTab />}

      {/* Login Audit Tab */}
      {activeTab === 4 && <AdminLoginAuditTab />}

      {/* System Health Tab */}
      {activeTab === 5 && <AdminFoundryStatusTab />}
    </Box>
  );
};

export default AdminPage;
