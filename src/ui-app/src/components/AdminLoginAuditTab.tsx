import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
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
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import apiClient from '../api/client';

interface LoginAuditEntry {
  id: string;
  userId: string;
  username: string;
  timestamp: string;
  ipAddress: string;
  geolocation: string | null;
  browser: string | null;
  userAgent: string | null;
  success: boolean;
  failureReason: string | null;
}

const AdminLoginAuditTab: React.FC = () => {
  const [audits, setAudits] = useState<LoginAuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(100);

  const fetchAudits = useCallback(async () => {
    try {
      setError(null);
      setLoading(true);
      const res = await apiClient.get(`/admin/login-audits?limit=${limit}`);
      const sorted = (res.data as LoginAuditEntry[]).sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      );
      setAudits(sorted);
    } catch {
      setError('Failed to load login audits. Please try again.');
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    fetchAudits();
  }, [fetchAudits]);

  const formatTimestamp = (ts: string) =>
    new Date(ts).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });

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

      <Box sx={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 2, mb: 2 }}>
        <FormControl size="small" sx={{ minWidth: 100 }}>
          <InputLabel>Limit</InputLabel>
          <Select
            value={limit}
            label="Limit"
            onChange={(e) => setLimit(e.target.value as number)}
          >
            <MenuItem value={50}>50</MenuItem>
            <MenuItem value={100}>100</MenuItem>
            <MenuItem value={250}>250</MenuItem>
          </Select>
        </FormControl>
        <Button startIcon={<RefreshIcon />} onClick={fetchAudits} variant="outlined" size="small">
          Refresh
        </Button>
      </Box>

      <TableContainer component={Paper} elevation={2}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Username</TableCell>
              <TableCell>Timestamp</TableCell>
              <TableCell>IP Address</TableCell>
              <TableCell>Browser</TableCell>
              <TableCell>Result</TableCell>
              <TableCell>Failure Reason</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {audits.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center">
                  No login audits found
                </TableCell>
              </TableRow>
            ) : (
              audits.map((audit) => (
                <TableRow key={audit.id}>
                  <TableCell>{audit.username}</TableCell>
                  <TableCell>{formatTimestamp(audit.timestamp)}</TableCell>
                  <TableCell>{audit.ipAddress}</TableCell>
                  <TableCell>{audit.browser || '—'}</TableCell>
                  <TableCell>
                    <Chip
                      label={audit.success ? 'Success' : 'Failed'}
                      color={audit.success ? 'success' : 'error'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>{audit.failureReason || '—'}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default AdminLoginAuditTab;
