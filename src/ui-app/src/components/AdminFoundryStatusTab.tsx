import React, { useState } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Button,
  CircularProgress,
  Alert,
  Chip,
  Stack,
  Divider,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import NetworkCheckIcon from '@mui/icons-material/NetworkCheck';
import apiClient from '../api/client';

interface AgentStatus {
  name: string;
  status: 'ok' | 'error' | 'degraded';
  error?: string;
}

interface FoundryResponse {
  status: 'ok' | 'error' | 'degraded';
  agents?: Record<string, { status: string; error?: string }>;
  error?: string;
}

interface ServiceResult {
  service: string;
  agents: AgentStatus[];
  error?: string;
}

const statusIcon = (status: string) => {
  switch (status) {
    case 'ok':
      return <CheckCircleIcon sx={{ color: 'success.main' }} />;
    case 'error':
      return <ErrorIcon sx={{ color: 'error.main' }} />;
    case 'degraded':
      return <WarningAmberIcon sx={{ color: 'warning.main' }} />;
    default:
      return <WarningAmberIcon sx={{ color: 'text.secondary' }} />;
  }
};

const statusChipColor = (status: string): 'success' | 'error' | 'warning' | 'default' => {
  switch (status) {
    case 'ok': return 'success';
    case 'error': return 'error';
    case 'degraded': return 'warning';
    default: return 'default';
  }
};

const parseAgents = (service: string, data: FoundryResponse): ServiceResult => {
  if (data.agents) {
    const agents: AgentStatus[] = Object.entries(data.agents).map(([name, info]) => ({
      name,
      status: info.status as AgentStatus['status'],
      error: info.error,
    }));
    return { service, agents };
  }
  // Fallback: treat the whole response as a single agent status
  return {
    service,
    agents: [{ name: service, status: data.status, error: data.error }],
  };
};

const AdminFoundryStatusTab: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<ServiceResult[]>([]);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const checkStatus = async () => {
    setLoading(true);
    setFetchError(null);
    const serviceResults: ServiceResult[] = [];

    // Check AI service (transaction-categorizer, risk-assessor)
    try {
      const aiRes = await apiClient.get<FoundryResponse>('/admin/foundry-status');
      serviceResults.push(parseAgents('AI Service', aiRes.data));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Network error';
      serviceResults.push({
        service: 'AI Service',
        agents: [],
        error: `Failed to reach AI service: ${message}`,
      });
    }

    // Check Chatbot service (chat agent)
    try {
      const chatRes = await apiClient.get<FoundryResponse>('/chat/admin/foundry-status');
      serviceResults.push(parseAgents('Chatbot Service', chatRes.data));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Network error';
      serviceResults.push({
        service: 'Chatbot Service',
        agents: [],
        error: `Failed to reach Chatbot service: ${message}`,
      });
    }

    setResults(serviceResults);
    setLastChecked(new Date());
    setLoading(false);
  };

  const overallStatus = (): 'ok' | 'error' | 'degraded' | null => {
    if (results.length === 0) return null;
    const hasError = results.some(r => r.error || r.agents.some(a => a.status === 'error'));
    const hasDegraded = results.some(r => r.agents.some(a => a.status === 'degraded'));
    if (hasError) return 'error';
    if (hasDegraded) return 'degraded';
    return 'ok';
  };

  const overall = overallStatus();

  return (
    <Box>
      <Card elevation={2}>
        <CardContent>
          <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <NetworkCheckIcon color="primary" />
              <Typography variant="h6">Azure AI Foundry Connectivity</Typography>
            </Stack>
            <Button
              variant="contained"
              onClick={checkStatus}
              disabled={loading}
              startIcon={loading ? <CircularProgress size={18} /> : <NetworkCheckIcon />}
            >
              {loading ? 'Checking…' : 'Check Foundry Status'}
            </Button>
          </Stack>

          {lastChecked && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Last checked: {lastChecked.toLocaleString()}
            </Typography>
          )}

          {overall && !loading && (
            <Alert
              severity={overall === 'ok' ? 'success' : overall === 'degraded' ? 'warning' : 'error'}
              sx={{ mb: 2 }}
            >
              {overall === 'ok' && 'All Foundry agents are connected and operational.'}
              {overall === 'degraded' && 'Some Foundry agents are experiencing issues.'}
              {overall === 'error' && 'One or more Foundry agents are unreachable.'}
            </Alert>
          )}

          {fetchError && (
            <Alert severity="error" sx={{ mb: 2 }}>{fetchError}</Alert>
          )}

          {results.length > 0 && (
            <Stack spacing={2}>
              {results.map((svc) => (
                <Card key={svc.service} variant="outlined">
                  <CardContent>
                    <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                      {svc.service}
                    </Typography>

                    {svc.error ? (
                      <Alert severity="error" variant="outlined">{svc.error}</Alert>
                    ) : (
                      <Stack spacing={1} divider={<Divider flexItem />}>
                        {svc.agents.map((agent) => (
                          <Box key={agent.name}>
                            <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
                              {statusIcon(agent.status)}
                              <Typography variant="body1">{agent.name}</Typography>
                              <Chip
                                label={agent.status.toUpperCase()}
                                color={statusChipColor(agent.status)}
                                size="small"
                                variant="outlined"
                              />
                            </Stack>
                            {agent.error && (
                              <Typography variant="body2" color="error" sx={{ ml: 4.5, mt: 0.5 }}>
                                {agent.error}
                              </Typography>
                            )}
                          </Box>
                        ))}
                      </Stack>
                    )}
                  </CardContent>
                </Card>
              ))}
            </Stack>
          )}

          {!loading && results.length === 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
              Click "Check Foundry Status" to validate connectivity to Azure AI Foundry agents.
            </Typography>
          )}
        </CardContent>
      </Card>
    </Box>
  );
};

export default AdminFoundryStatusTab;
