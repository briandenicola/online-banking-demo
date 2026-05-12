import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  Typography,
} from '@mui/material';
import {
  ApplicationResponse,
  ApplicationStatus as ApplicationStatusType,
  AgentStage,
  getApplication,
} from '../../api/accountOpening';
import AgentPipeline from './AgentPipeline';

export interface ApplicationStatusData {
  id: string;
  status: ApplicationStatusType;
  createdAt: string;
  updatedAt: string;
  userId?: string;
  accountId?: string;
  agentResults?: {
    documentExtraction?: { status?: string; timestamp?: string };
    identityVerification?: { verified?: boolean; confidence?: number; timestamp?: string };
    complianceCheck?: { kycStatus?: string; riskTier?: string; timestamp?: string };
  };
}

interface ApplicationStatusProps {
  applicationId: string;
  statusData?: ApplicationStatusData | null;
  onRefresh?: () => void;
  pollInterval?: number;
  application?: ApplicationResponse;
}

const terminalStatuses: ApplicationStatusType[] = ['approved', 'rejected', 'pending_review'];

const defaultStages: AgentStage[] = [
  { name: 'Document Extraction', status: 'pending' },
  { name: 'Identity Verification', status: 'pending' },
  { name: 'Compliance Check', status: 'pending' },
  { name: 'Provisioning', status: 'pending' },
];

const statusColors: Record<ApplicationStatusType, 'success' | 'warning' | 'error' | 'info'> = {
  submitted: 'info',
  document_extraction: 'info',
  identity_verification: 'info',
  compliance_check: 'warning',
  pending_review: 'warning',
  approved: 'success',
  rejected: 'error',
};

const statusMessages: Record<ApplicationStatusType, string> = {
  submitted: 'Your application has been submitted and is being processed.',
  document_extraction: 'We are extracting details from your documents.',
  identity_verification: 'We are verifying your identity.',
  compliance_check: 'We are completing compliance checks.',
  pending_review: 'Your application requires manual review.',
  approved: 'Congratulations! Your application has been approved.',
  rejected: 'Unfortunately, your application has been rejected.',
};

const formatStatusLabel = (status: ApplicationStatusType) =>
  status.replace(/_/g, ' ').toUpperCase();

const ApplicationStatus: React.FC<ApplicationStatusProps> = ({
  applicationId,
  statusData,
  onRefresh,
  pollInterval,
  application: initialApplication,
}) => {
  const isControlled =
    typeof pollInterval !== 'undefined' || typeof statusData !== 'undefined' || typeof onRefresh !== 'undefined';

  const [application, setApplication] = useState<ApplicationResponse | null>(
    initialApplication ?? null
  );
  const [loading, setLoading] = useState(!isControlled && !initialApplication);
  const [error, setError] = useState<string | null>(null);

  const fetchApplication = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getApplication(applicationId);
      setApplication(result);
    } catch (err) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err as { message?: string })?.message ||
        'Unable to load application status.';
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isControlled) return;
    if (!initialApplication) {
      fetchApplication();
    }
  }, [applicationId, isControlled]);

  useEffect(() => {
    if (!isControlled) return undefined;
    if (!onRefresh || !pollInterval || pollInterval <= 0) return undefined;
    const interval = setInterval(() => {
      onRefresh();
    }, pollInterval);
    return () => clearInterval(interval);
  }, [onRefresh, pollInterval, isControlled]);

  useEffect(() => {
    if (isControlled) return undefined;
    if (!application) return undefined;
    if (terminalStatuses.includes(application.status)) return undefined;

    const interval = setInterval(() => {
      fetchApplication();
    }, 2000);

    return () => clearInterval(interval);
  }, [application?.status, applicationId, isControlled]);

  const stages = useMemo(() => {
    if (!application?.stages?.length) return defaultStages;
    return application.stages;
  }, [application]);

  const banner = useMemo(() => {
    if (!application) return null;
    if (application.status === 'approved') {
      return { severity: 'success' as const, text: 'Decision finalized.' };
    }
    if (application.status === 'rejected') {
      return { severity: 'error' as const, text: 'Decision finalized.' };
    }
    if (application.status === 'pending_review') {
      return { severity: 'warning' as const, text: 'Manual check required.' };
    }
    return null;
  }, [application]);

  const renderControlledStatus = () => {
    if (statusData === undefined) {
      return (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
          <CircularProgress />
        </Box>
      );
    }

    if (statusData === null) {
      return (
        <Alert severity="warning">
          No application data available.
        </Alert>
      );
    }

    const message = statusMessages[statusData.status];
    const agentResults = statusData.agentResults;
    const showProcessingDetails = agentResults && Object.keys(agentResults).length > 0;

    return (
      <Stack spacing={2}>
        <Alert severity={statusColors[statusData.status]}>{message}</Alert>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: 'center' }}>
          <Chip label={formatStatusLabel(statusData.status)} color={statusColors[statusData.status]} />
          <Typography variant="caption" color="text.secondary">
            Submitted: {new Date(statusData.createdAt).toLocaleString()}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Last Updated: {new Date(statusData.updatedAt).toLocaleString()}
          </Typography>
        </Stack>

        {showProcessingDetails && (
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
              Processing Details
            </Typography>
            {agentResults?.documentExtraction && (
              <Typography variant="body2">
                Document Extraction: {agentResults.documentExtraction.status ?? 'pending'}
              </Typography>
            )}
            {agentResults?.identityVerification && (
              <Typography variant="body2">
                Identity Verification:{' '}
                {agentResults.identityVerification.verified ? 'Verified' : 'Pending'}
                {typeof agentResults.identityVerification.confidence === 'number' && (
                  <> · {Math.round(agentResults.identityVerification.confidence * 100)}% confidence</>
                )}
              </Typography>
            )}
            {agentResults?.complianceCheck && (
              <Typography variant="body2">
                Compliance Check: {agentResults.complianceCheck.kycStatus ?? 'pending'}
                {agentResults.complianceCheck.riskTier && (
                  <> · Risk: {agentResults.complianceCheck.riskTier}</>
                )}
              </Typography>
            )}
          </Box>
        )}

        {(statusData.userId || statusData.accountId) && (
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
              Account Information
            </Typography>
            {statusData.userId && <Typography>User ID: {statusData.userId}</Typography>}
            {statusData.accountId && <Typography>Account ID: {statusData.accountId}</Typography>}
          </Box>
        )}
      </Stack>
    );
  };

  return (
    <Card elevation={2}>
      <CardContent>
        <Box sx={{ mb: 2 }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ justifyContent: 'space-between' }}>
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                Application Status
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Application ID: {applicationId}
              </Typography>
            </Box>
            {onRefresh && (
              <Button variant="outlined" size="small" onClick={onRefresh}>
                Refresh
              </Button>
            )}
          </Stack>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {isControlled ? (
          renderControlledStatus()
        ) : loading && !application ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress />
          </Box>
        ) : application ? (
          <Box>
            {banner && (
              <Alert severity={banner.severity} sx={{ mb: 2 }}>
                {banner.text}
              </Alert>
            )}
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 2 }}>
              <Chip
                label={formatStatusLabel(application.status)}
                color={statusColors[application.status]}
              />
              {application.updatedAt && (
                <Typography variant="caption" color="text.secondary">
                  Updated {new Date(application.updatedAt).toLocaleString()}
                </Typography>
              )}
            </Stack>
            <AgentPipeline stages={stages} />
          </Box>
        ) : (
          <Alert severity="warning">No application data available.</Alert>
        )}
      </CardContent>
    </Card>
  );
};

export default ApplicationStatus;
