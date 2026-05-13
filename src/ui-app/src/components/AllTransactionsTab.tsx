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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ReplayIcon from '@mui/icons-material/Replay';
import apiClient from '../api/client';

export interface ScoredTransaction {
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

type SortField = 'scoredAt' | 'amount' | 'riskScore';
type SortDirection = 'asc' | 'desc';

interface AllTransactionsTabProps {
  transactions: ScoredTransaction[];
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

const AllTransactionsTab: React.FC<AllTransactionsTabProps> = ({
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

  const handleRescore = async (id: string) => {
    setActionLoading(id);
    try {
      await apiClient.post(`/admin/scored-transactions/${id}/rescore`);
      await onRefresh();
    } catch {
      onError('Failed to rescore transaction. Please try again.');
    } finally {
      setActionLoading(null);
    }
  };

  const sorted = [...transactions].sort((a, b) => {
    const modifier = sortDirection === 'asc' ? 1 : -1;
    switch (sortField) {
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

  return (
    <TableContainer component={Paper} elevation={2}>
      <Table>
        <TableHead>
          <TableRow>
            <TableCell />
            <TableCell>
              <TableSortLabel
                active={sortField === 'scoredAt'}
                direction={sortField === 'scoredAt' ? sortDirection : 'asc'}
                onClick={() => handleSort('scoredAt')}
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
            <TableCell>Category</TableCell>
            <TableCell>
              <TableSortLabel
                active={sortField === 'riskScore'}
                direction={sortField === 'riskScore' ? sortDirection : 'asc'}
                onClick={() => handleSort('riskScore')}
              >
                Risk Score
              </TableSortLabel>
            </TableCell>
            <TableCell>Description</TableCell>
            <TableCell align="center">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {sorted.length === 0 ? (
            <TableRow>
              <TableCell colSpan={9} align="center">
                <Typography variant="body1" sx={{ py: 4 }} color="text.secondary">
                  No scored transactions found.
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
                  <TableCell>{new Date(tx.scoredAt).toLocaleDateString()}</TableCell>
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
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRescore(tx.id);
                        }}
                      >
                        {actionLoading === tx.id ? <CircularProgress size={18} /> : <ReplayIcon />}
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell
                    colSpan={9}
                    sx={{ py: 0, borderBottom: expandedRow === tx.id ? undefined : 'none' }}
                  >
                    <Collapse in={expandedRow === tx.id} timeout="auto" unmountOnExit>
                      <Box sx={{ py: 2, px: 3 }}>
                        <Typography variant="subtitle2" gutterBottom sx={{ fontWeight: 700 }}>
                          AI Processing Steps
                        </Typography>

                        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 1.5 }}>
                          <Chip
                            label="1"
                            size="small"
                            color="info"
                            sx={{ minWidth: 24, fontWeight: 700 }}
                          />
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
                              <Typography
                                variant="caption"
                                color="text.secondary"
                                sx={{ display: 'block', mt: 0.25 }}
                              >
                                {tx.categoryReasoning}
                              </Typography>
                            )}
                          </Box>
                        </Box>

                        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 1.5 }}>
                          <Chip
                            label="2"
                            size="small"
                            color="warning"
                            sx={{ minWidth: 24, fontWeight: 700 }}
                          />
                          <Box>
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>
                              Risk Scoring
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              Score: <strong>{tx.riskScore.toFixed(2)}</strong>
                              {tx.flags.length > 0 && <> — Flags: {tx.flags.join(', ')}</>}
                            </Typography>
                            <Typography
                              variant="caption"
                              color="text.secondary"
                              sx={{ display: 'block', mt: 0.25 }}
                            >
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
  );
};

export default AllTransactionsTab;
