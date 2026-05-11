import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';

export interface Application {
  id: string;
  status: 'pending_review' | 'approved' | 'rejected' | string;
  createdAt: string;
  formData: {
    firstName: string;
    lastName: string;
    email: string;
    phone?: string;
    accountType?: string;
  };
}

interface AdminApplicationsTabProps {
  applications?: Application[];
  onFetchApplications?: () => Promise<Application[]>;
  onApproveApplication?: (id: string, notes: string) => Promise<void>;
  onRejectApplication?: (id: string, notes: string) => Promise<void>;
}

const filterTabs = [
  { label: 'All', value: 'all' },
  { label: 'Pending Review', value: 'pending_review' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
];

const AdminApplicationsTab: React.FC<AdminApplicationsTabProps> = ({
  applications = [],
  onFetchApplications,
  onApproveApplication,
  onRejectApplication,
}) => {
  const [items, setItems] = useState<Application[]>(applications);
  const [activeFilter, setActiveFilter] = useState('all');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [selected, setSelected] = useState<Application | null>(null);
  const [reviewNotes, setReviewNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setItems(applications);
  }, [applications]);

  useEffect(() => {
    if (!onFetchApplications) return;
    onFetchApplications()
      .then((result) => {
        if (result) setItems(result);
        setError(null);
      })
      .catch((err: Error) => {
        setError(err.message || 'Failed to load applications');
      });
  }, [onFetchApplications]);

  const filteredItems = useMemo(() => {
    if (activeFilter === 'all') return items;
    return items.filter((item) => item.status === activeFilter);
  }, [items, activeFilter]);

  const openDetails = (application: Application) => {
    setSelected(application);
    setDetailsOpen(true);
  };

  const openApprove = (application: Application) => {
    setSelected(application);
    setReviewNotes('');
    setApproveOpen(true);
  };

  const openReject = (application: Application) => {
    setSelected(application);
    setReviewNotes('');
    setRejectOpen(true);
  };

  const handleApprove = async () => {
    if (!selected || !onApproveApplication) return;
    setSubmitting(true);
    await onApproveApplication(selected.id, reviewNotes);
    setSubmitting(false);
    setApproveOpen(false);
    onFetchApplications?.();
  };

  const handleReject = async () => {
    if (!selected || !onRejectApplication) return;
    setSubmitting(true);
    await onRejectApplication(selected.id, reviewNotes);
    setSubmitting(false);
    setRejectOpen(false);
    onFetchApplications?.();
  };

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Account Applications
      </Typography>

      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Tabs value={activeFilter} onChange={(_, value) => setActiveFilter(value)} sx={{ mb: 2 }}>
        {filterTabs.map((tab) => (
          <Tab key={tab.value} label={tab.label} value={tab.value} />
        ))}
      </Tabs>

      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Application ID</TableCell>
            <TableCell>Applicant</TableCell>
            <TableCell>Email</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Created</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {filteredItems.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6}>
                <Typography variant="body2" color="text.secondary">
                  No applications found
                </Typography>
              </TableCell>
            </TableRow>
          ) : (
            filteredItems.map((app) => (
              <TableRow key={app.id}>
                <TableCell>{app.id}</TableCell>
                <TableCell>{`${app.formData.firstName} ${app.formData.lastName}`}</TableCell>
                <TableCell>{app.formData.email}</TableCell>
                <TableCell>
                  <Chip label={app.status} size="small" />
                </TableCell>
                <TableCell>{new Date(app.createdAt).toLocaleString()}</TableCell>
                <TableCell align="right">
                  <Button size="small" onClick={() => openDetails(app)}>View</Button>
                  {app.status === 'pending_review' && (
                    <>
                      <Button size="small" onClick={() => openApprove(app)}>Approve</Button>
                      <Button size="small" color="error" onClick={() => openReject(app)}>Reject</Button>
                    </>
                  )}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      <Dialog open={detailsOpen} onClose={() => setDetailsOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Application Details</DialogTitle>
        <DialogContent>
          {selected && (
            <Box sx={{ mt: 1 }}>
              <Typography variant="subtitle1" sx={{ mb: 1 }}>Personal Information</Typography>
              <Typography>{`${selected.formData.firstName} ${selected.formData.lastName}`}</Typography>
              <Typography>{selected.formData.email}</Typography>
              <Typography>{selected.formData.phone}</Typography>
              <Typography>{selected.formData.accountType}</Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetailsOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={approveOpen} onClose={() => setApproveOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Approve Application</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="Review Notes"
            value={reviewNotes}
            onChange={(event) => setReviewNotes(event.target.value)}
            multiline
            rows={3}
            sx={{ mt: 2 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setApproveOpen(false)} disabled={submitting}>Cancel</Button>
          <Button onClick={handleApprove} disabled={submitting}>Approve</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={rejectOpen} onClose={() => setRejectOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Reject Application</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="Review Notes"
            value={reviewNotes}
            onChange={(event) => setReviewNotes(event.target.value)}
            multiline
            rows={3}
            sx={{ mt: 2 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectOpen(false)} disabled={submitting}>Cancel</Button>
          <Button onClick={handleReject} disabled={!reviewNotes.trim() || submitting}>Reject</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default AdminApplicationsTab;
