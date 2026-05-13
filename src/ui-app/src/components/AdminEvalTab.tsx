import React, { useState, useEffect, useCallback } from 'react';
import { Box, Alert, CircularProgress } from '@mui/material';
import apiClient from '../api/client';
import PromptTemplateEditor from './eval/PromptTemplateEditor';
import EvaluationRunner from './eval/EvaluationRunner';
import EvaluationResults from './eval/EvaluationResults';
import {
  PromptTemplate,
  EvaluationRunSummary,
  EvalScoredTransaction,
  ActivePrompt,
} from './eval/types';

const AdminEvalTab: React.FC = () => {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [runs, setRuns] = useState<EvaluationRunSummary[]>([]);
  const [transactions, setTransactions] = useState<EvalScoredTransaction[]>([]);
  const [activePrompts, setActivePrompts] = useState<ActivePrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');

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
    } catch {
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
    const hasRunning = runs.some((r) => r.status === 'running' || r.status === 'pending');
    if (!hasRunning) return;
    const interval = setInterval(async () => {
      try {
        const res = await apiClient.get('/evaluations?pageSize=50');
        setRuns(res.data.items || []);
      } catch {
        /* ignore */
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [runs]);

  const handleRunRequested = (templateId: string) => {
    setSelectedTemplateId(templateId);
    setRunDialogOpen(true);
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <PromptTemplateEditor
        templates={templates}
        activePrompts={activePrompts}
        onChanged={fetchData}
        onRunRequested={handleRunRequested}
        onError={setError}
      />

      <EvaluationResults runs={runs} onRefresh={fetchData} onError={setError} />

      <EvaluationRunner
        open={runDialogOpen}
        templateId={selectedTemplateId}
        transactions={transactions}
        onClose={() => setRunDialogOpen(false)}
        onStarted={fetchData}
        onError={setError}
      />
    </Box>
  );
};

export default AdminEvalTab;
