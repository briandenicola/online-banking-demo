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
  Button,
  TextField,
  CircularProgress,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  IconButton,
  Tooltip,
  Checkbox,
  LinearProgress,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import CompareArrowsIcon from '@mui/icons-material/CompareArrows';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import RefreshIcon from '@mui/icons-material/Refresh';
import DownloadIcon from '@mui/icons-material/Download';
import apiClient from '../api/client';

interface PromptTemplate {
  id: string;
  name: string;
  description?: string;
  target: string;
  systemPrompt: string;
  version: number;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

interface QualityScores {
  coherence: number;
  fluency: number;
  relevance: number;
  passRate: number;
}

interface SafetyResult {
  passed: boolean;
  averageScore: number;
  failedCount: number;
}

interface SafetyScores {
  violence: SafetyResult;
  hateUnfairness: SafetyResult;
  selfHarm: SafetyResult;
  sexual: SafetyResult;
}

interface EvaluationRunSummary {
  id: string;
  templateId: string;
  templateName: string;
  templateVersion: number;
  status: string;
  transactionCount: number;
  qualityScores?: QualityScores;
  safetyScores?: SafetyScores;
  createdAt: string;
  completedAt?: string;
}

interface EvaluationOutputItem {
  transactionId: string;
  query: string;
  response: string;
  queryMessages?: unknown[];
  responseMessages?: unknown[];
  scores?: Record<string, { score: number; passed: boolean }>;
  status?: string;
  coherenceScore: number;
  fluencyScore: number;
  relevanceScore: number;
  safetyPassed: boolean;
  safetyDetails: Record<string, number>;
}

interface EvaluationRunDetail extends EvaluationRunSummary {
  outputItems?: EvaluationOutputItem[];
  error?: string;
}

interface ScoredTransaction {
  id: string;
  transactionId: string;
  amount: number;
  type: string;
  description: string;
  riskScore: number;
}

interface ActivePrompt {
  name: string;
  type: string;
  enabled: boolean;
  systemPrompt: string;
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

const AdminEvalTab: React.FC = () => {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [runs, setRuns] = useState<EvaluationRunSummary[]>([]);
  const [transactions, setTransactions] = useState<ScoredTransaction[]>([]);
  const [activePrompts, setActivePrompts] = useState<ActivePrompt[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvaluationRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<PromptTemplate | null>(null);
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [selectedTxIds, setSelectedTxIds] = useState<string[]>([]);
  const [runningEval, setRunningEval] = useState(false);
  const [detailDialogOpen, setDetailDialogOpen] = useState(false);

  // Template form state
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formTarget, setFormTarget] = useState('risk-scoring');
  const [formPrompt, setFormPrompt] = useState('');

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [templatesRes, runsRes, txRes, promptsRes] = await Promise.all([
        apiClient.get('/evaluations/prompts'),
        apiClient.get('/evaluations?pageSize=50'),
        apiClient.get('/admin/transactions'),
        apiClient.get('/admin/prompts'),
      ]);
      setTemplates(templatesRes.data);
      setRuns(runsRes.data.items || []);
      setTransactions(txRes.data?.slice(0, 50) || []);
      setActivePrompts(promptsRes.data || []);
    } catch (err) {
      setError('Failed to load evaluation data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Poll for running evaluations
  useEffect(() => {
    const hasRunning = runs.some(r => r.status === 'running' || r.status === 'pending');
    if (!hasRunning) return;
    const interval = setInterval(async () => {
      try {
        const res = await apiClient.get('/evaluations?pageSize=50');
        setRuns(res.data.items || []);
      } catch { /* ignore */ }
    }, 5000);
    return () => clearInterval(interval);
  }, [runs]);

  const handleSaveTemplate = async () => {
    try {
      if (editingTemplate) {
        await apiClient.put(`/evaluations/prompts/${editingTemplate.id}`, {
          name: formName, description: formDescription, systemPrompt: formPrompt
        });
      } else {
        await apiClient.post('/evaluations/prompts', {
          name: formName, description: formDescription, target: formTarget, systemPrompt: formPrompt
        });
      }
      setTemplateDialogOpen(false);
      resetForm();
      fetchData();
    } catch {
      setError('Failed to save template.');
    }
  };

  const handleDeleteTemplate = async (id: string) => {
    try {
      await apiClient.delete(`/evaluations/prompts/${id}`);
      fetchData();
    } catch {
      setError('Failed to delete template.');
    }
  };

  const handleRunEval = async () => {
    if (!selectedTemplateId || selectedTxIds.length === 0) return;
    setRunningEval(true);
    try {
      await apiClient.post('/evaluations/run', {
        templateId: selectedTemplateId,
        transactionIds: selectedTxIds
      });
      setRunDialogOpen(false);
      setSelectedTxIds([]);
      fetchData();
    } catch {
      setError('Failed to start evaluation.');
    } finally {
      setRunningEval(false);
    }
  };

  const handleViewRun = async (id: string) => {
    try {
      const res = await apiClient.get(`/evaluations/${id}`);
      setSelectedRun(res.data);
      setDetailDialogOpen(true);
    } catch {
      setError('Failed to load run details.');
    }
  };

  const handleDownloadJson = () => {
    if (!selectedRun?.outputItems) return;
    const data = selectedRun.outputItems.map(item => ({
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

  const openEditTemplate = (t: PromptTemplate) => {
    setEditingTemplate(t);
    setFormName(t.name);
    setFormDescription(t.description || '');
    setFormTarget(t.target);
    setFormPrompt(t.systemPrompt);
    setTemplateDialogOpen(true);
  };

  const openNewTemplate = () => {
    resetForm();
    setEditingTemplate(null);
    setTemplateDialogOpen(true);
  };

  const resetForm = () => {
    setFormName(''); setFormDescription(''); setFormTarget('risk-scoring'); setFormPrompt('');
  };

  const toggleTx = (id: string) => {
    setSelectedTxIds(prev => prev.includes(id) ? prev.filter(t => t !== id) : [...prev, id]);
  };

  if (loading) return <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>;

  return (
    <Box>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}

      {/* Active Prompts Section */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>Active AI Prompts</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          These are the system prompts currently used by the AI service for risk scoring and categorization.
        </Typography>
        <Grid container spacing={2}>
          {activePrompts.map((prompt, idx) => (
            <Grid size={{ xs: 12, md: 6 }} key={idx}>
              <Card variant="outlined">
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{prompt.name}</Typography>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Chip label={prompt.type} size="small" variant="outlined" />
                      <Chip
                        label={prompt.enabled ? 'Active' : 'Disabled'}
                        color={prompt.enabled ? 'success' : 'default'}
                        size="small"
                      />
                    </Box>
                  </Box>
                  <Box sx={{
                    p: 1.5, bgcolor: 'grey.50', borderRadius: 1, fontFamily: 'monospace', fontSize: '0.75rem',
                    maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.5
                  }}>
                    {prompt.systemPrompt}
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
          {activePrompts.length === 0 && (
            <Grid size={12}>
              <Alert severity="info">No active prompts found. The AI service may not be running.</Alert>
            </Grid>
          )}
        </Grid>
      </Box>

      {/* Prompt Templates Section */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6">Prompt Templates</Typography>
        <Button startIcon={<AddIcon />} variant="contained" size="small" onClick={openNewTemplate}>
          New Template
        </Button>
      </Box>

      <Grid container spacing={2} sx={{ mb: 4 }}>
        {templates.length === 0 ? (
          <Grid size={12}>
            <Alert severity="info">No prompt templates yet. Create one to get started with evaluations.</Alert>
          </Grid>
        ) : templates.map(t => (
          <Grid size={{ xs: 12, md: 6 }} key={t.id}>
            <Card variant="outlined">
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <Box>
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{t.name}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {t.target} · v{t.version} · Updated {new Date(t.updatedAt).toLocaleDateString()}
                    </Typography>
                    {t.description && (
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{t.description}</Typography>
                    )}
                  </Box>
                  <Box>
                    <Tooltip title="Edit"><IconButton size="small" onClick={() => openEditTemplate(t)}><EditIcon fontSize="small" /></IconButton></Tooltip>
                    <Tooltip title="Delete"><IconButton size="small" onClick={() => handleDeleteTemplate(t.id)}><DeleteIcon fontSize="small" /></IconButton></Tooltip>
                    <Tooltip title="Run Evaluation">
                      <IconButton size="small" color="primary" onClick={() => {
                        setSelectedTemplateId(t.id);
                        setRunDialogOpen(true);
                      }}>
                        <PlayArrowIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                </Box>
                <Typography variant="body2" sx={{
                  mt: 1, p: 1, bgcolor: 'grey.50', borderRadius: 1, fontFamily: 'monospace', fontSize: '0.75rem',
                  maxHeight: 80, overflow: 'hidden', whiteSpace: 'pre-wrap'
                }}>
                  {t.systemPrompt.substring(0, 200)}{t.systemPrompt.length > 200 ? '...' : ''}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Evaluation Runs Section */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6">Evaluation Runs</Typography>
        <IconButton onClick={fetchData}><RefreshIcon /></IconButton>
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
              <TableRow><TableCell colSpan={10} align="center"><Typography color="text.secondary">No evaluation runs yet</Typography></TableCell></TableRow>
            ) : runs.map(run => (
              <TableRow key={run.id} hover sx={{ cursor: 'pointer' }} onClick={() => handleViewRun(run.id)}>
                <TableCell>
                  <Typography variant="body2">{run.templateName}</Typography>
                  <Typography variant="caption" color="text.secondary">v{run.templateVersion}</Typography>
                </TableCell>
                <TableCell>
                  {run.status === 'running' || run.status === 'pending' ? (
                    <Chip label={run.status} color="warning" size="small" icon={<CircularProgress size={12} />} />
                  ) : run.status === 'completed' ? (
                    <Chip label="Completed" color="success" size="small" />
                  ) : (
                    <Chip label="Failed" color="error" size="small" />
                  )}
                </TableCell>
                <TableCell>{run.transactionCount}</TableCell>
                <TableCell>{run.qualityScores ? <ScoreChip score={run.qualityScores.coherence} /> : '—'}</TableCell>
                <TableCell>{run.qualityScores ? <ScoreChip score={run.qualityScores.fluency} /> : '—'}</TableCell>
                <TableCell>{run.qualityScores ? <ScoreChip score={run.qualityScores.relevance} /> : '—'}</TableCell>
                <TableCell>{run.qualityScores ? (
                  <Chip label={`${(run.qualityScores.passRate * 100).toFixed(0)}%`} color={run.qualityScores.passRate >= 0.8 ? 'success' : 'warning'} size="small" variant="outlined" />
                ) : '—'}</TableCell>
                <TableCell>
                  {run.safetyScores ? (
                    <Chip
                      label={Object.values(run.safetyScores).every((s: SafetyResult) => s.passed) ? 'All Pass' : 'Issues'}
                      color={Object.values(run.safetyScores).every((s: SafetyResult) => s.passed) ? 'success' : 'error'}
                      size="small" variant="outlined"
                    />
                  ) : '—'}
                </TableCell>
                <TableCell><Typography variant="caption">{new Date(run.createdAt).toLocaleString()}</Typography></TableCell>
                <TableCell>
                  <Button size="small" onClick={(e) => { e.stopPropagation(); handleViewRun(run.id); }}>Details</Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Template Create/Edit Dialog */}
      <Dialog open={templateDialogOpen} onClose={() => setTemplateDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{editingTemplate ? 'Edit Template' : 'New Prompt Template'}</DialogTitle>
        <DialogContent>
          <TextField fullWidth label="Name" value={formName} onChange={e => setFormName(e.target.value)} sx={{ mt: 1, mb: 2 }} />
          <TextField fullWidth label="Description" value={formDescription} onChange={e => setFormDescription(e.target.value)} sx={{ mb: 2 }} />
          {!editingTemplate && (
            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>Target</InputLabel>
              <Select value={formTarget} label="Target" onChange={e => setFormTarget(e.target.value)}>
                <MenuItem value="risk-scoring">Risk Scoring</MenuItem>
                <MenuItem value="categorization">Categorization</MenuItem>
              </Select>
            </FormControl>
          )}
          <TextField
            fullWidth multiline rows={12} label="System Prompt"
            value={formPrompt} onChange={e => setFormPrompt(e.target.value)}
            slotProps={{ input: { style: { fontFamily: 'monospace', fontSize: '0.85rem' } } }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTemplateDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSaveTemplate} disabled={!formName || !formPrompt}>Save</Button>
        </DialogActions>
      </Dialog>

      {/* Run Evaluation Dialog */}
      <Dialog open={runDialogOpen} onClose={() => setRunDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Run Evaluation</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Select transactions to evaluate against the selected prompt template.
          </Typography>
          {runningEval && <LinearProgress sx={{ mb: 2 }} />}
          <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 400 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox">
                    <Checkbox
                      checked={selectedTxIds.length === transactions.length && transactions.length > 0}
                      indeterminate={selectedTxIds.length > 0 && selectedTxIds.length < transactions.length}
                      onChange={() => setSelectedTxIds(selectedTxIds.length === transactions.length ? [] : transactions.map(t => t.id))}
                    />
                  </TableCell>
                  <TableCell>Description</TableCell>
                  <TableCell>Amount</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Risk Score</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {transactions.map(tx => (
                  <TableRow key={tx.id} hover onClick={() => toggleTx(tx.id)} sx={{ cursor: 'pointer' }}>
                    <TableCell padding="checkbox">
                      <Checkbox
                        checked={selectedTxIds.includes(tx.id)}
                        onChange={(e) => { e.stopPropagation(); toggleTx(tx.id); }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </TableCell>
                    <TableCell>{tx.description || tx.type}</TableCell>
                    <TableCell>${tx.amount.toFixed(2)}</TableCell>
                    <TableCell>{tx.type}</TableCell>
                    <TableCell><ScoreChip score={tx.riskScore} max={1} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            {selectedTxIds.length} transaction(s) selected
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRunDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleRunEval} disabled={selectedTxIds.length === 0 || runningEval}
            startIcon={runningEval ? <CircularProgress size={16} /> : <PlayArrowIcon />}>
            Run Evaluation
          </Button>
        </DialogActions>
      </Dialog>

      {/* Run Detail Dialog */}
      <Dialog open={detailDialogOpen} onClose={() => setDetailDialogOpen(false)} maxWidth="lg" fullWidth>
        <DialogTitle>
          Evaluation Results: {selectedRun?.templateName} v{selectedRun?.templateVersion}
        </DialogTitle>
        <DialogContent>
          {selectedRun && (
            <Box>
              {/* Summary Scores */}
              <Grid container spacing={2} sx={{ mb: 3 }}>
                {selectedRun.qualityScores && (
                  <>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Card variant="outlined"><CardContent sx={{ textAlign: 'center', py: 1 }}>
                        <Typography variant="caption" color="text.secondary">Coherence</Typography>
                        <Typography variant="h5">{selectedRun.qualityScores.coherence.toFixed(1)}</Typography>
                      </CardContent></Card>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Card variant="outlined"><CardContent sx={{ textAlign: 'center', py: 1 }}>
                        <Typography variant="caption" color="text.secondary">Fluency</Typography>
                        <Typography variant="h5">{selectedRun.qualityScores.fluency.toFixed(1)}</Typography>
                      </CardContent></Card>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Card variant="outlined"><CardContent sx={{ textAlign: 'center', py: 1 }}>
                        <Typography variant="caption" color="text.secondary">Relevance</Typography>
                        <Typography variant="h5">{selectedRun.qualityScores.relevance.toFixed(1)}</Typography>
                      </CardContent></Card>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Card variant="outlined"><CardContent sx={{ textAlign: 'center', py: 1 }}>
                        <Typography variant="caption" color="text.secondary">Pass Rate</Typography>
                        <Typography variant="h5">{(selectedRun.qualityScores.passRate * 100).toFixed(0)}%</Typography>
                      </CardContent></Card>
                    </Grid>
                  </>
                )}
              </Grid>

              {/* Safety Results */}
              {selectedRun.safetyScores && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>Safety Checks</Typography>
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                    <Box>Violence: <SafetyChip result={selectedRun.safetyScores.violence} /></Box>
                    <Box>Hate/Unfairness: <SafetyChip result={selectedRun.safetyScores.hateUnfairness} /></Box>
                    <Box>Self-Harm: <SafetyChip result={selectedRun.safetyScores.selfHarm} /></Box>
                    <Box>Sexual: <SafetyChip result={selectedRun.safetyScores.sexual} /></Box>
                  </Box>
                </Box>
              )}

              {/* Per-Transaction Results */}
              {selectedRun.outputItems && selectedRun.outputItems.length > 0 && (
                <Box>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>Per-Transaction Results</Typography>
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
                            <TableCell><Typography variant="caption">{item.transactionId.substring(0, 8)}...</Typography></TableCell>
                            <TableCell><ScoreChip score={item.coherenceScore} /></TableCell>
                            <TableCell><ScoreChip score={item.fluencyScore} /></TableCell>
                            <TableCell><ScoreChip score={item.relevanceScore} /></TableCell>
                            <TableCell>
                              <Chip
                                label={item.safetyPassed ? 'Pass' : 'Fail'}
                                color={item.safetyPassed ? 'success' : 'error'}
                                size="small" variant="outlined"
                              />
                            </TableCell>
                            <TableCell>
                              <Typography variant="caption" sx={{ maxWidth: 300, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
                <Alert severity="error" sx={{ mt: 2 }}>{selectedRun.error}</Alert>
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
          <Button onClick={() => setDetailDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default AdminEvalTab;
