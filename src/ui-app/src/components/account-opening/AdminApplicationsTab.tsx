import React from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import {
  ApplicationResponse,
  ApplicationStatus,
  AgentStage,
  listApplications,
  reviewApplication,
} from '../../api/accountOpening';

export interface Application {
  id: string;
  status: 'pending_review' | 'approved' | 'rejected';
  createdAt: string;
  formData: {
    firstName: string;
    lastName: string;
    email: string;
    phone: string;
    accountType: string;
  };
}

interface AdminApplicationsTabProps {
  onFetchApplications?: () => Promise<Application[]>;
  applications?: Application[];
  onApproveApplication?: (applicationId: string, notes: string) => Promise<void>;
  onRejectApplication?: (applicationId: string, notes: string) => Promise<void>;
}

type SortField = 'createdAt' | 'status' | 'riskTier';

type FilterValue = ApplicationStatus | 'all';

type ReviewMode = 'approve' | 'reject';

const filterOptions: { label: string; value: FilterValue }[] = [
  { label: 'All', value: 'all' },
  { label: 'Pending Review', value: 'pending_review' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
];

const statusChip = (status: ApplicationStatus) => {
  switch (status) {
    case 'approved':
      return <Chip label="approved" color="success" size="small" aria-label="approved" />;
    case 'rejected':
      return <Chip label="rejected" color="error" size="small" aria-label="rejected" />;
    case 'pending_review':
      return <Chip label="pending review" color="warning" size="small" aria-label="pending_review" />;
    default:
      return <Chip label={status} size="small" />;
  }
};

const statusChipControlled = (status: Application['status']) => {
  switch (status) {
    case 'approved':
      return <Chip label="approved" color="success" size="small" />;
    case 'rejected':
      return <Chip label="rejected" color="error" size="small" />;
    case 'pending_review':
      return <Chip label="pending_review" color="warning" size="small" />;
    default:
      return <Chip label={status} size="small" />;
  }
};

const riskTierRank = (tier?: string) => {
  if (!tier) return 0;
  switch (tier.toLowerCase()) {
    case 'high':
      return 3;
    case 'medium':
      return 2;
    case 'low':
      return 1;
    default:
      return 0;
  }
};

const resolveApplicantName = (application: ApplicationResponse) => {
  const first = application.firstName ?? application.formData?.firstName ?? '';
  const last = application.lastName ?? application.formData?.lastName ?? '';
  return `${first} ${last}`.trim() || '—';
};

const renderStages = (stages?: AgentStage[]) => {
  if (!stages || stages.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No stage data available.
      </Typography>
    );
  }
  return stages.map((stage) => (
    <Box key={stage.name} sx={{ mb: 1 }}>
      <Typography variant="body2">
        {stage.name}: {stage.status}
      </Typography>
      {typeof stage.confidence === 'number' && (
        <Typography variant="caption" color="text.secondary">
          Confidence: {(stage.confidence * 100).toFixed(0)}%
        </Typography>
      )}
      {stage.reasoning && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {stage.reasoning}
        </Typography>
      )}
    </Box>
  ));
};

const ControlledAdminApplicationsTab: React.FC<AdminApplicationsTabProps> = ({
  onFetchApplications,
  applications,
  onApproveApplication,
  onRejectApplication,
}) => {
  const [fetchedApplications, setFetchedApplications] = React.useState<Application[]>([]);
  const [filter, setFilter] = React.useState<FilterValue>('all');
  const [loading, setLoading] = React.useState(!applications);
  const [error, setError] = React.useState<string | null>(null);
  const [selectedApplication, setSelectedApplication] = React.useState<Application | null>(null);
  const [reviewing, setReviewing] = React.useState<{ mode: ReviewMode; app: Application } | null>(null);
  const [notes, setNotes] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);

  const loadApplications = React.useCallback(async () => {
    if (!onFetchApplications) return;
    if (!applications) {
      setLoading(true);
    }
    try {
      const result = await onFetchApplications();
      if (!applications && result) {
        setFetchedApplications(result);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load applications';
      setError(message);
    } finally {
      if (!applications) {
        setLoading(false);
      }
    }
  }, [onFetchApplications, applications]);

  React.useEffect(() => {
    loadApplications();
  }, [loadApplications]);

  const data = applications ?? fetchedApplications;
  const filteredApplications = filter === 'all'
    ? data
    : data.filter((application) => application.status === filter);

  const handleReviewSubmit = async () => {
    if (!reviewing) return;
    const { mode, app } = reviewing;
    setSubmitting(true);
    try {
      if (mode === 'approve') {
        await onApproveApplication?.(app.id, notes);
      } else {
        await onRejectApplication?.(app.id, notes);
      }
      setReviewing(null);
      setNotes('');
      await loadApplications();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to submit review.';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCloseReview = () => {
    if (submitting) return;
    setReviewing(null);
    setNotes('');
  };

  return (
    <Box>
      <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
        Account Applications
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Tabs
        value={filter}
        onChange={(_, value) => setFilter(value)}
        sx={{ mb: 2 }}
      >
        {filterOptions.map((option) => (
          <Tab key={option.value} label={option.label} value={option.value} />
        ))}
      </Tabs>

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
          <CircularProgress />
        </Box>
      )}

      {!loading && filteredApplications.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No applications found
        </Typography>
      )}

      {!loading && filteredApplications.length > 0 && (
        <TableContainer component={Paper} elevation={2}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Application ID</TableCell>
                <TableCell>Applicant</TableCell>
                <TableCell>Email</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredApplications.map((application) => {
                const fullName = `${application.formData.firstName} ${application.formData.lastName}`;
                return (
                  <TableRow key={application.id} hover>
                    <TableCell>{application.id}</TableCell>
                    <TableCell>{fullName}</TableCell>
                    <TableCell>{application.formData.email}</TableCell>
                    <TableCell>{statusChipControlled(application.status)}</TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
                        <Button size="small" onClick={() => setSelectedApplication(application)}>
                          View
                        </Button>
                        {application.status === 'pending_review' && (
                          <>
                            <Button
                              size="small"
                              variant="contained"
                              onClick={() => setReviewing({ mode: 'approve', app: application })}
                            >
                              Approve
                            </Button>
                            <Button
                              size="small"
                              variant="outlined"
                              color="error"
                              onClick={() => setReviewing({ mode: 'reject', app: application })}
                            >
                              Reject
                            </Button>
                          </>
                        )}
                      </Stack>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog open={Boolean(selectedApplication)} onClose={() => setSelectedApplication(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Application Details</DialogTitle>
        <DialogContent dividers>
          {selectedApplication && (
            <Stack spacing={1}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                Personal Information
              </Typography>
              <Typography>{selectedApplication.formData.firstName} {selectedApplication.formData.lastName}</Typography>
              <Typography>{selectedApplication.formData.email}</Typography>
              <Typography>{selectedApplication.formData.phone}</Typography>
              <Typography>{selectedApplication.formData.accountType}</Typography>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSelectedApplication(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(reviewing)} onClose={handleCloseReview} maxWidth="sm" fullWidth>
        <DialogTitle>
          {reviewing?.mode === 'approve' ? 'Approve Application' : 'Reject Application'}
        </DialogTitle>
        <DialogContent dividers>
          <TextField
            fullWidth
            label="Review Notes"
            multiline
            minRows={3}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseReview} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color={reviewing?.mode === 'reject' ? 'error' : 'primary'}
            onClick={handleReviewSubmit}
            disabled={submitting || (reviewing?.mode === 'reject' && !notes.trim())}
          >
            {reviewing?.mode === 'approve' ? 'Approve' : 'Reject'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

const ApiAdminApplicationsTab: React.FC = () => {
  const [applications, setApplications] = React.useState<ApplicationResponse[]>([]);
  const [filter, setFilter] = React.useState<FilterValue>('all');
  const [sortField, setSortField] = React.useState<SortField>('createdAt');
  const [sortDirection, setSortDirection] = React.useState<'asc' | 'desc'>('desc');
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const fetchApplications = React.useCallback(async () => {
    try {
      setError(null);
      const response = await listApplications();
      const items = Array.isArray(response) ? response : response.items ?? [];
      setApplications(items);
    } catch {
      setError('Unable to load applications. Please try again.');
    }
  }, []);

  React.useEffect(() => {
    fetchApplications();
  }, [fetchApplications]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const filteredApplications = React.useMemo(() => {
    const filtered = filter === 'all'
      ? applications
      : applications.filter((application) => application.status === filter);
    return [...filtered].sort((a, b) => {
      let compare = 0;
      if (sortField === 'createdAt') {
        compare = new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime();
      }
      if (sortField === 'riskTier') {
        compare = riskTierRank(a.riskTier) - riskTierRank(b.riskTier);
      }
      if (sortField === 'status') {
        compare = (a.status || '').localeCompare(b.status || '');
      }
      return sortDirection === 'asc' ? compare : -compare;
    });
  }, [applications, filter, sortDirection, sortField]);

  const handleReview = async (applicationId: string, decision: 'approved' | 'rejected') => {
    await reviewApplication(applicationId, { decision });
    await fetchApplications();
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Tabs
        value={filter}
        onChange={(_, value) => setFilter(value)}
        sx={{ mb: 2 }}
      >
        {filterOptions.map((option) => (
          <Tab key={option.value} label={option.label} value={option.value} />
        ))}
      </Tabs>

      <TableContainer component={Paper} elevation={2}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell />
              <TableCell>
                <TableSortLabel
                  active={sortField === 'createdAt'}
                  direction={sortField === 'createdAt' ? sortDirection : 'asc'}
                  onClick={() => handleSort('createdAt')}
                >
                  Date
                </TableSortLabel>
              </TableCell>
              <TableCell>Applicant Name</TableCell>
              <TableCell>
                <TableSortLabel
                  active={sortField === 'status'}
                  direction={sortField === 'status' ? sortDirection : 'asc'}
                  onClick={() => handleSort('status')}
                >
                  Status
                </TableSortLabel>
              </TableCell>
              <TableCell>
                <TableSortLabel
                  active={sortField === 'riskTier'}
                  direction={sortField === 'riskTier' ? sortDirection : 'asc'}
                  onClick={() => handleSort('riskTier')}
                >
                  Risk Tier
                </TableSortLabel>
              </TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filteredApplications.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center">
                  <Typography variant="body2" color="text.secondary" sx={{ py: 3 }}>
                    No applications found.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              filteredApplications.map((application) => {
                const isExpanded = expandedId === application.id;
                return (
                  <React.Fragment key={application.id}>
                    <TableRow hover>
                      <TableCell>
                        <IconButton
                          size="small"
                          aria-label="Expand"
                          onClick={() => setExpandedId(isExpanded ? null : application.id)}
                        >
                          {isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                        </IconButton>
                      </TableCell>
                      <TableCell>{new Date(application.createdAt).toLocaleDateString()}</TableCell>
                      <TableCell>{resolveApplicantName(application)}</TableCell>
                      <TableCell>{statusChip(application.status)}</TableCell>
                      <TableCell>{application.riskTier || '—'}</TableCell>
                      <TableCell align="right">
                        {application.status === 'pending_review' && (
                          <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
                            <Button
                              size="small"
                              variant="contained"
                              startIcon={<CheckCircleIcon />}
                              onClick={() => handleReview(application.id, 'approved')}
                            >
                              Approve
                            </Button>
                            <Button
                              size="small"
                              variant="outlined"
                              color="error"
                              startIcon={<CloseIcon />}
                              onClick={() => handleReview(application.id, 'rejected')}
                            >
                              Reject
                            </Button>
                          </Box>
                        )}
                      </TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell colSpan={6} sx={{ py: 0 }}>
                        <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                          <Box sx={{ p: 2 }}>
                            <Typography variant="subtitle2" sx={{ mb: 1 }}>
                              Agent Stages
                            </Typography>
                            {renderStages(application.stages)}
                          </Box>
                        </Collapse>
                      </TableCell>
                    </TableRow>
                  </React.Fragment>
                );
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

const AdminApplicationsTab: React.FC<AdminApplicationsTabProps> = (props) => {
  if (props.onFetchApplications || props.applications || props.onApproveApplication || props.onRejectApplication) {
    return <ControlledAdminApplicationsTab {...props} />;
  }
  return <ApiAdminApplicationsTab />;
};

export default AdminApplicationsTab;
