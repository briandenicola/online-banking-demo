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
import TaskMeasurementBar from '../components/comparison/TaskMeasurementBar';

interface AdminStats {
  totalFlagged: number;
  pendingReview: number;
  cleared: number;
  avgRiskScore: number;
  totalScored: number;
  highRiskCount: number;
  aiTokensToday: number;
  aiCallsToday?: number;
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

/**
 * Tab identity for the surface comparison.
 *
 * A "region" is a place the user must move their attention to. In Classic Admin
 * that is a tab; in the Copilot harness it is a pane. Moving between two of them
 * is one context switch on either surface — the same rule, applied to whatever
 * each surface actually makes you traverse.
 */
const ADMIN_TABS: { label: string; regionId: string }[] = [
  { label: 'Account Applications', regionId: 'admin-applications' },
  { label: 'User Management', regionId: 'admin-users' },
  { label: 'All Transactions', regionId: 'admin-transactions' },
  { label: 'Flagged Transactions', regionId: 'admin-flagged' },
  { label: 'Chatbot Prompt', regionId: 'admin-prompt' },
  { label: 'AI Evaluation', regionId: 'admin-eval' },
  { label: 'Login Audit', regionId: 'admin-audit' },
  { label: 'System Health', regionId: 'admin-health' },
];

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
                  {stats.aiTokensToday.toLocaleString()}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  AI Tokens Today
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/*
        Tab Navigation.

        Each tab declares itself a `data-comparison-region`, and so does the
        panel it reveals. That attribute is the ONLY instrumentation in this
        file: the counting rules live in TaskMeasurementBar and are shared
        verbatim with the Copilot harness. Classic Admin is not counted more
        coarsely than the harness, and it is not counted more finely either —
        which is the whole reason the recorder sat unused through Phase 1.
      */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={activeTab} onChange={(_, newValue) => setActiveTab(newValue)}>
          {ADMIN_TABS.map((tab) => (
            <Tab key={tab.regionId} label={tab.label} data-comparison-region={tab.regionId} />
          ))}
        </Tabs>
      </Box>

      <Box data-comparison-region={ADMIN_TABS[activeTab]?.regionId || 'admin'}>
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
    </Box>
  );
};

/**
 * Classic Admin, wrapped in the shared measurement harness.
 *
 * Same component, same props, same rules as the Copilot surface. Wrapping at
 * the page boundary rather than sprinkling callbacks through the eight tabs is
 * deliberate: there is no place in this file where someone could quietly add or
 * drop a count on one surface only.
 */
const InstrumentedAdminPage: React.FC = () => (
  <TaskMeasurementBar surface="classic">
    <AdminPage />
  </TaskMeasurementBar>
);

export default InstrumentedAdminPage;
