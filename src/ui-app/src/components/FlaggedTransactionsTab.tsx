import React, { useState } from 'react';
import {
  Box,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  IconButton,
  Collapse,
  CircularProgress,
  Tooltip,
  TableSortLabel,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import RateReviewIcon from '@mui/icons-material/RateReview';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import apiClient from '../api/client';

export interface FlaggedTransaction {
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

type SortField = 'flaggedAt' | 'amount' | 'riskScore' | 'status';
type SortDirection = 'asc' | 'desc';

interface FlaggedTransactionsTabProps {
  transactions: FlaggedTransaction[];
  onRefresh: () => Promise<void> | void;
  onError: (message: string) => void;
}

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

const FlaggedTransactionsTab: React.FC<FlaggedTransactionsTabProps> = ({
  transactions,
  onRefresh,
  onError,
}) => {
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>('riskScore');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const handleAction = async (id: string, action: 'review' | 'clear') => {
    setActionLoading(id);
    try {
      const status = action === 'review' ? 'reviewed' : 'cleared';
      await apiClient.put(`/admin/flagged-transactions/${id}/review`, {
        status,
        notes: `Marked as ${status} by admin`,
      });
      await onRefresh();
    } catch {
      onError(`Failed to ${action} transaction. Please try again.`);
    } finally {
      setActionLoading(null);
    }
  };

  const sorted = [...transactions].sort((a, b) => {
    const modifier = sortDirection === 'asc' ? 1 : -1;
    switch (sortField) {
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

  return (
    <TableContainer component={Paper} elevation={2}>
      <Table>
        <TableHead>
          <TableRow>
            <TableCell />
            <TableCell>
              <TableSortLabel
                active={sortField === 'flaggedAt'}
                direction={sortField === 'flaggedAt' ? sortDirection : 'asc'}
                onClick={() => handleSort('flaggedAt')}
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
          {sorted.length === 0 ? (
            <TableRow>
              <TableCell colSpan={9} align="center">
                <Typography variant="body1" sx={{ py: 4 }} color="text.secondary">
                  No flagged transactions found.
                </Typography>
              </TableCell>
            </TableRow>
          ) : (
            sorted.map((tx) => (
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
                  <TableCell>{new Date(tx.flaggedAt).toLocaleDateString()}</TableCell>
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
                  <TableCell
                    colSpan={9}
                    sx={{ py: 0, borderBottom: expandedRow === tx.id ? undefined : 'none' }}
                  >
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
                                <Chip
                                  key={idx}
                                  label={flag}
                                  color="error"
                                  size="small"
                                  variant="outlined"
                                />
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
                            <strong>Amount:</strong> $
                            {tx.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
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
  );
};

export default FlaggedTransactionsTab;
