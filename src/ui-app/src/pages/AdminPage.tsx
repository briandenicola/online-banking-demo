import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Grid,
  Button,
  CircularProgress,
  Alert,
  Tabs,
  Tab,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import SecurityIcon from '@mui/icons-material/Security';
import PendingActionsIcon from '@mui/icons-material/PendingActions';
import VerifiedIcon from '@mui/icons-material/Verified';
import AssessmentIcon from '@mui/icons-material/Assessment';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import apiClient from '../api/client';
import AdminEvalTab from '../components/AdminEvalTab';
import AdminUserManagementTab from '../components/AdminUserManagementTab';
import AdminLoginAuditTab from '../components/AdminLoginAuditTab';
import AdminFoundryStatusTab from '../components/AdminFoundryStatusTab';
import AdminChatbotPromptTab from '../components/AdminChatbotPromptTab';
import AdminApplicationsTab from '../components/account-opening/AdminApplicationsTab';
import FlaggedTransactionsTab, {
  FlaggedTransaction,
} from '../components/FlaggedTransactionsTab';
import AllTransactionsTab, { ScoredTransaction } from '../components/AllTransactionsTab';

interface AdminStats {
  totalFlagged: number;
  pendingReview: number;
  cleared: number;
  avgRiskScore: number;
  totalScored: number;
  highRiskCount: number;
  aiCallsToday: number;
}

// Risk scores are 0.0–1.0 from the model. Anything outside that range is
// almost certainly poisoned data (e.g., legacy rows where the sorted-set
// score was a Unix timestamp instead of a probability — see issue #119).
// Render a dash so the dashboard never advertises a 10-digit "risk score".
function formatRiskScore(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value < 0 || value > 1) {
    return '—';
  }
  return value.toFixed(2);
}

const AdminPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState(0);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [flaggedTransactions, setFlaggedTransactions] = useState<FlaggedTransaction[]>([]);
  const [allTransactions, setAllTransactions] = useState<ScoredTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    } catch {
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

  if (loading) {
    return (
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          minHeight: '400px',
        }}
      >
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
        <Button variant="outlined" startIcon={<RefreshIcon />} onClick={fetchData}>
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
                  {formatRiskScore(stats.avgRiskScore)}
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
        <Tabs value={activeTab} onChange={(_, newValue) => setActiveTab(newValue)}>
          <Tab label="Account Applications" />
          <Tab label="User Management" />
          <Tab label="All Transactions" />
          <Tab label="Flagged Transactions" />
          <Tab label="Chatbot Prompt" />
          <Tab label="AI Evaluation" />
          <Tab label="Login Audit" />
          <Tab label="System Health" />
        </Tabs>
      </Box>

      {activeTab === 0 && <AdminApplicationsTab />}
      {activeTab === 1 && <AdminUserManagementTab />}

      {activeTab === 2 && (
        <AllTransactionsTab
          transactions={allTransactions}
          onRefresh={fetchData}
          onError={setError}
        />
      )}

      {activeTab === 3 && (
        <FlaggedTransactionsTab
          transactions={flaggedTransactions}
          onRefresh={fetchData}
          onError={setError}
        />
      )}

      {activeTab === 4 && <AdminChatbotPromptTab />}
      {activeTab === 5 && <AdminEvalTab />}
      {activeTab === 6 && <AdminLoginAuditTab />}
      {activeTab === 7 && <AdminFoundryStatusTab />}
    </Box>
  );
};

export default AdminPage;
