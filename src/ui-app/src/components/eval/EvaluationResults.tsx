import React, { useState } from 'react';
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
  Button,
  CircularProgress,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import RefreshIcon from '@mui/icons-material/Refresh';
import DownloadIcon from '@mui/icons-material/Download';
import apiClient from '../../api/client';
import { EvaluationRunSummary, EvaluationRunDetail, SafetyResult } from './types';

interface EvaluationResultsProps {
  runs: EvaluationRunSummary[];
  onRefresh: () => Promise<void> | void;
  onError: (message: string) => void;
}

const ScoreChip: React.FC<{ score: number; max?: number }> = ({ score, max = 5 }) => {
  const ratio = score / max;
  const color = ratio >= 0.6 ? 'success' : ratio >= 0.4 ? 'warning' : 'error';
  return <Chip label={score.toFixed(1)} color={color} size="small" />;
};

const SafetyChip: React.FC<{ result: SafetyResult }> = ({ result }) => (
  <Chip
    icon={result.passed ? <CheckCircleIcon /> : <CancelIcon />}
    label={result.passed ? 'Pass' : `Fail (${result.failedCount})`}
    color={result.passed ? 'success' : 'error'}
    size="small"
    variant="outlined"
  />
);

const EvaluationResults: React.FC<EvaluationResultsProps> = ({ runs, onRefresh, onError }) => {
  const [selectedRun, setSelectedRun] = useState<EvaluationRunDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const handleViewRun = async (id: string) => {
    try {
      const res = await apiClient.get(`/evaluations/${id}`);
      setSelectedRun(res.data);
      setDetailOpen(true);
    } catch {
      onError('Failed to load run details.');
    }
  };

  const handleDownloadJson = () => {
    if (!selectedRun?.outputItems) return;
    const data = selectedRun.outputItems.map((item) => ({
      query: item.query,
      response: item.response,
      query_messages: item.queryMessages || [],
      response_messages: item.responseMessages || [],
      scores: item.scores || {},
      status: item.status || '',
    }));
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `eval-${selectedRun.id}-results.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <Box
        sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}
      >
        <Typography variant="h6">Evaluation Runs</Typography>
        <IconButton onClick={() => onRefresh()}>
          <RefreshIcon />
        </IconButton>
      </Box>

      <TableContainer component={Paper} variant="outlined" sx={{ mb: 3 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Template</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Transactions</TableCell>
              <TableCell>Coherence</TableCell>
              <TableCell>Fluency</TableCell>
              <TableCell>Relevance</TableCell>
              <TableCell>Pass Rate</TableCell>
              <TableCell>Safety</TableCell>
              <TableCell>Date</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {runs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} align="center">
                  <Typography color="text.secondary">No evaluation runs yet</Typography>
                </TableCell>
              </TableRow>
            ) : (
              runs.map((run) => (
                <TableRow
                  key={run.id}
                  hover
                  sx={{ cursor: 'pointer' }}
                  onClick={() => handleViewRun(run.id)}
                >
                  <TableCell>
                    <Typography variant="body2">{run.templateName}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      v{run.templateVersion}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    {run.status === 'running' || run.status === 'pending' ? (
                      <Chip
                        label={run.status}
                        color="warning"
                        size="small"
                        icon={<CircularProgress size={12} />}
                      />
                    ) : run.status === 'completed' ? (
                      <Chip label="Completed" color="success" size="small" />
                    ) : (
                      <Chip label="Failed" color="error" size="small" />
                    )}
                  </TableCell>
                  <TableCell>{run.transactionCount}</TableCell>
                  <TableCell>
                    {run.qualityScores ? <ScoreChip score={run.qualityScores.coherence} /> : '—'}
                  </TableCell>
                  <TableCell>
                    {run.qualityScores ? <ScoreChip score={run.qualityScores.fluency} /> : '—'}
                  </TableCell>
                  <TableCell>
                    {run.qualityScores ? <ScoreChip score={run.qualityScores.relevance} /> : '—'}
                  </TableCell>
                  <TableCell>
                    {run.qualityScores ? (
                      <Chip
                        label={`${(run.qualityScores.passRate * 100).toFixed(0)}%`}
                        color={run.qualityScores.passRate >= 0.8 ? 'success' : 'warning'}
                        size="small"
                        variant="outlined"
                      />
                    ) : (
                      '—'
                    )}
                  </TableCell>
                  <TableCell>
                    {run.safetyScores ? (
                      <Chip
                        label={
                          Object.values(run.safetyScores).every((s: SafetyResult) => s.passed)
                            ? 'All Pass'
                            : 'Issues'
                        }
                        color={
                          Object.values(run.safetyScores).every((s: SafetyResult) => s.passed)
                            ? 'success'
                            : 'error'
                        }
                        size="small"
                        variant="outlined"
                      />
                    ) : (
                      '—'
                    )}
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">
                      {new Date(run.createdAt).toLocaleString()}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Button
                      size="small"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleViewRun(run.id);
                      }}
                    >
                      Details
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Detail Dialog */}
      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} maxWidth="lg" fullWidth>
        <DialogTitle>
          Evaluation Results: {selectedRun?.templateName} v{selectedRun?.templateVersion}
        </DialogTitle>
        <DialogContent>
          {selectedRun && (
            <Box>
              <Grid container spacing={2} sx={{ mb: 3 }}>
                {selectedRun.qualityScores && (
                  <>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Card variant="outlined">
                        <CardContent sx={{ textAlign: 'center', py: 1 }}>
                          <Typography variant="caption" color="text.secondary">
                            Coherence
                          </Typography>
                          <Typography variant="h5">
                            {selectedRun.qualityScores.coherence.toFixed(1)}
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Card variant="outlined">
                        <CardContent sx={{ textAlign: 'center', py: 1 }}>
                          <Typography variant="caption" color="text.secondary">
                            Fluency
                          </Typography>
                          <Typography variant="h5">
                            {selectedRun.qualityScores.fluency.toFixed(1)}
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Card variant="outlined">
                        <CardContent sx={{ textAlign: 'center', py: 1 }}>
                          <Typography variant="caption" color="text.secondary">
                            Relevance
                          </Typography>
                          <Typography variant="h5">
                            {selectedRun.qualityScores.relevance.toFixed(1)}
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Card variant="outlined">
                        <CardContent sx={{ textAlign: 'center', py: 1 }}>
                          <Typography variant="caption" color="text.secondary">
                            Pass Rate
                          </Typography>
                          <Typography variant="h5">
                            {(selectedRun.qualityScores.passRate * 100).toFixed(0)}%
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                  </>
                )}
              </Grid>

              {selectedRun.safetyScores && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>
                    Safety Checks
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                    <Box>
                      Violence: <SafetyChip result={selectedRun.safetyScores.violence} />
                    </Box>
                    <Box>
                      Hate/Unfairness:{' '}
                      <SafetyChip result={selectedRun.safetyScores.hateUnfairness} />
                    </Box>
                    <Box>
                      Self-Harm: <SafetyChip result={selectedRun.safetyScores.selfHarm} />
                    </Box>
                    <Box>
                      Sexual: <SafetyChip result={selectedRun.safetyScores.sexual} />
                    </Box>
                  </Box>
                </Box>
              )}

              {selectedRun.outputItems && selectedRun.outputItems.length > 0 && (
                <Box>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>
                    Per-Transaction Results
                  </Typography>
                  <TableContainer component={Paper} variant="outlined">
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Transaction</TableCell>
                          <TableCell>Coherence</TableCell>
                          <TableCell>Fluency</TableCell>
                          <TableCell>Relevance</TableCell>
                          <TableCell>Safety</TableCell>
                          <TableCell>Response Preview</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {selectedRun.outputItems.map((item, idx) => (
                          <TableRow key={idx}>
                            <TableCell>
                              <Typography variant="caption">
                                {item.transactionId.substring(0, 8)}...
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <ScoreChip score={item.coherenceScore} />
                            </TableCell>
                            <TableCell>
                              <ScoreChip score={item.fluencyScore} />
                            </TableCell>
                            <TableCell>
                              <ScoreChip score={item.relevanceScore} />
                            </TableCell>
                            <TableCell>
                              <Chip
                                label={item.safetyPassed ? 'Pass' : 'Fail'}
                                color={item.safetyPassed ? 'success' : 'error'}
                                size="small"
                                variant="outlined"
                              />
                            </TableCell>
                            <TableCell>
                              <Typography
                                variant="caption"
                                sx={{
                                  maxWidth: 300,
                                  display: 'block',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {item.response.substring(0, 100)}
                              </Typography>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}

              {selectedRun.error && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  {selectedRun.error}
                </Alert>
              )}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          {selectedRun?.outputItems && selectedRun.outputItems.length > 0 && (
            <Button onClick={handleDownloadJson} startIcon={<DownloadIcon />}>
              Download JSON
            </Button>
          )}
          <Button onClick={() => setDetailOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default EvaluationResults;
