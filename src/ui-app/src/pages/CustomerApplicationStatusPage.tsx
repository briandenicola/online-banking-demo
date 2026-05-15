import React from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Typography,
} from '@mui/material';
import ErrorOutlineRounded from '@mui/icons-material/ErrorOutlineRounded';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import { useParams, useNavigate } from 'react-router-dom';
import ApplicationStages from '../components/account-opening/ApplicationStages';
import {
  ACCOUNT_OPENING_STORAGE_KEY,
  ApplicationResponse,
  getApplication,
  resubmitApplication,
} from '../api/accountOpening';
import { resolveApiError } from '../api/errors';

const isTerminal = (status?: string) => {
  return ['approved', 'rejected', 'pending_review', 'failed'].includes(status ?? '');
};

const CustomerApplicationStatusPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [application, setApplication] = React.useState<ApplicationResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [resubmitting, setResubmitting] = React.useState(false);
  const [resubmitError, setResubmitError] = React.useState<string | null>(null);
  const pollIntervalRef = React.useRef<NodeJS.Timeout | null>(null);

  const fetchApplication = React.useCallback(async () => {
    if (!id) return;
    try {
      setError(null);
      const data = await getApplication(id);
      setApplication(data);
    } catch (err: unknown) {
      setError(resolveApiError(err, 'Unable to load application status.'));
    } finally {
      setLoading(false);
    }
  }, [id]);

  React.useEffect(() => {
    fetchApplication();
  }, [fetchApplication]);

  React.useEffect(() => {
    if (!id) return;
    try {
      localStorage.setItem(ACCOUNT_OPENING_STORAGE_KEY, id);
    } catch {
      // No-op when storage is unavailable.
    }
  }, [id]);

  React.useEffect(() => {
    if (!application || isTerminal(application.status)) {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      return;
    }

    pollIntervalRef.current = setInterval(() => {
      fetchApplication();
    }, 2000);

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [application, fetchApplication]);

  const handleResubmit = async () => {
    if (!id) return;
    setResubmitting(true);
    setResubmitError(null);
    try {
      await resubmitApplication(id);
      await fetchApplication();
    } catch (err: unknown) {
      const errorData = (err as { response?: { status?: number; data?: { message?: string } } })?.response;
      if (errorData?.status === 409) {
        setResubmitError(errorData.data?.message ?? 'Retry limit reached. Please contact support.');
      } else {
        setResubmitError(resolveApiError(err, 'Unable to retry application.'));
      }
    } finally {
      setResubmitting(false);
    }
  };

  const handleStartNewApplication = () => {
    try {
      localStorage.removeItem(ACCOUNT_OPENING_STORAGE_KEY);
    } catch {
      // No-op when storage is unavailable.
    }
    navigate('/account-opening');
  };

  if (!id) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
        <Typography variant="h6" color="text.secondary">
          Application ID not found
        </Typography>
      </Box>
    );
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error}</Alert>
        <Button variant="outlined" onClick={handleStartNewApplication} sx={{ mt: 2 }}>
          Back to Application Form
        </Button>
      </Box>
    );
  }

  if (!application) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="warning">Application not found</Alert>
        <Button variant="outlined" onClick={handleStartNewApplication} sx={{ mt: 2 }}>
          Back to Application Form
        </Button>
      </Box>
    );
  }

  const stages = application.stages ?? [];
  const showRetry =
    application.status === 'failed' &&
    application.lastError?.retryable === true &&
    application.failedStage &&
    (application.stageAttempts?.[application.failedStage] ?? 0) < 2;

  const showContactSupport =
    application.status === 'failed' &&
    (!application.lastError?.retryable ||
      (application.failedStage && (application.stageAttempts?.[application.failedStage] ?? 0) >= 2));

  const renderTerminalMessage = () => {
    if (!isTerminal(application.status)) return null;

    if (application.status === 'approved') {
      return (
        <Card sx={{ mt: 3, bgcolor: 'success.light', color: 'success.contrastText' }}>
          <CardContent>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <CheckCircleIcon />
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                🎉 Welcome!
              </Typography>
            </Box>
            {application.customerExplanation && (
              <Typography variant="body1">{application.customerExplanation}</Typography>
            )}
          </CardContent>
        </Card>
      );
    }

    if (application.status === 'rejected') {
      return (
        <Card sx={{ mt: 3, bgcolor: 'error.light', color: 'error.contrastText' }}>
          <CardContent>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <CancelIcon />
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                Application Update
              </Typography>
            </Box>
            {application.customerExplanation && (
              <Typography variant="body1">{application.customerExplanation}</Typography>
            )}
          </CardContent>
        </Card>
      );
    }

    if (application.status === 'pending_review') {
      return (
        <Card sx={{ mt: 3, bgcolor: 'warning.light', color: 'warning.contrastText' }}>
          <CardContent>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>
              Application Under Review
            </Typography>
            {application.customerExplanation && (
              <Typography variant="body1">{application.customerExplanation}</Typography>
            )}
          </CardContent>
        </Card>
      );
    }

    if (application.status === 'failed') {
      return (
        <Card sx={{ mt: 3 }}>
          <CardContent>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>
              Processing Issue
            </Typography>
            {application.customerExplanation && (
              <Typography variant="body1">{application.customerExplanation}</Typography>
            )}
          </CardContent>
        </Card>
      );
    }

    return null;
  };

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" sx={{ fontWeight: 700 }}>
          Application Status
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Track your account opening progress
        </Typography>
      </Box>

      {application.status === 'failed' && application.lastError && (
        <Alert
          severity={showRetry ? 'warning' : 'error'}
          icon={<ErrorOutlineRounded />}
          sx={{ mb: 3 }}
          action={
            showRetry ? (
              <Button
                color="inherit"
                size="small"
                onClick={handleResubmit}
                disabled={resubmitting}
              >
                {resubmitting ? 'Retrying...' : 'Retry'}
              </Button>
            ) : undefined
          }
        >
          {application.lastError.message}
        </Alert>
      )}

      {resubmitError && (
        <Alert severity="error" sx={{ mb: 3 }} onClose={() => setResubmitError(null)}>
          {resubmitError}
        </Alert>
      )}

      {showContactSupport && (
        <Alert severity="info" sx={{ mb: 3 }}>
          We're experiencing issues processing your application. Please contact support for assistance.
        </Alert>
      )}

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
            Application Processing Pipeline
          </Typography>
          <ApplicationStages stages={stages} showDetails={false} />
        </CardContent>
      </Card>

      {renderTerminalMessage()}

      <Box sx={{ mt: 3 }}>
        <Button variant="outlined" onClick={handleStartNewApplication}>
          Start New Application
        </Button>
      </Box>
    </Box>
  );
};

export default CustomerApplicationStatusPage;
