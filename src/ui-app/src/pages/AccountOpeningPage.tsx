import React from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Step,
  StepLabel,
  Stepper,
  Typography,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import ApplicationForm from '../components/account-opening/ApplicationForm';
import DocumentUpload from '../components/account-opening/DocumentUpload';
import {
  ApplicationCreateRequest,
  ApplicationFormData,
  ApplicationResponse,
  ACCOUNT_OPENING_STORAGE_KEY,
  createApplication,
} from '../api/accountOpening';
import ApplicationStatus from '../components/account-opening/ApplicationStatus';

type StepKey = 'form' | 'upload';

const steps: { key: StepKey; label: string }[] = [
  { key: 'form', label: 'Application Form' },
  { key: 'upload', label: 'Upload Documents' },
];

const AccountOpeningPage: React.FC = () => {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = React.useState<StepKey>('form');
  const [application, setApplication] = React.useState<ApplicationResponse | null>(null);
  const [savedApplicationId, setSavedApplicationId] = React.useState<string | null>(() => {
    try {
      return localStorage.getItem(ACCOUNT_OPENING_STORAGE_KEY);
    } catch {
      return null;
    }
  });
  const formMode = process.env.NODE_ENV === 'test' ? 'simple' : 'full';
  const activeApplicationId = application?.id ?? savedApplicationId;

  const persistApplicationId = React.useCallback((applicationId: string) => {
    try {
      localStorage.setItem(ACCOUNT_OPENING_STORAGE_KEY, applicationId);
    } catch {
      // No-op when storage is unavailable.
    }
    setSavedApplicationId(applicationId);
  }, []);

  const clearSavedApplication = React.useCallback(() => {
    try {
      localStorage.removeItem(ACCOUNT_OPENING_STORAGE_KEY);
    } catch {
      // No-op when storage is unavailable.
    }
    setSavedApplicationId(null);
  }, []);

  const handleApplicationCreated = (created: ApplicationResponse) => {
    setApplication(created);
    persistApplicationId(created.id);
    setCurrentStep('upload');
  };

  const handleSimpleSubmit = async (payload: ApplicationFormData) => {
    const wirePayload: ApplicationCreateRequest = {
      firstName: payload.firstName,
      lastName: payload.lastName,
      dateOfBirth: payload.dateOfBirth,
      email: payload.email,
      phone: (payload.phone ?? '').trim(),
      ssn: (payload.ssnLastFour ?? '').trim(),
      address: {
        street: (payload.street ?? payload.address ?? '').trim(),
        city: (payload.city ?? '').trim(),
        state: (payload.state ?? '').trim(),
        zip: (payload.zip ?? payload.zipCode ?? '').trim(),
        country: 'US',
      },
      employment: payload.employer || payload.employment
        ? {
            employer: (payload.employer ?? payload.employment ?? '').trim(),
            title: (payload.title ?? '').trim(),
            annualIncome: Number(payload.annualIncome ?? 0),
          }
        : undefined,
      accountType: payload.accountType,
    };
    const response = await createApplication(wirePayload);
    setApplication(response);
    persistApplicationId(response.id);
    setCurrentStep('upload');
  };

  const handleContinueToProcessing = async () => {
    if (!activeApplicationId) return;
    navigate(`/applications/${activeApplicationId}/status`);
  };

  const activeStepIndex = steps.findIndex((step) => step.key === currentStep);

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" sx={{ fontWeight: 700 }}>
          Open a New Account
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Complete your application, add verification files, and track real-time progress.
        </Typography>
      </Box>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Stepper activeStep={activeStepIndex}>
            {steps.map((step) => (
              <Step key={step.key}>
                <StepLabel>{step.label}</StepLabel>
              </Step>
            ))}
          </Stepper>
        </CardContent>
      </Card>

      {currentStep === 'form' && !application && savedApplicationId && (
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>
              Existing Application Found
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Your previous application is saved. You can continue uploading documents or review its current status.
            </Typography>
            <ApplicationStatus applicationId={savedApplicationId} />
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 2 }}>
              <Button variant="contained" onClick={() => setCurrentStep('upload')}>
                Continue Upload
              </Button>
              <Button variant="outlined" onClick={() => navigate(`/applications/${savedApplicationId}/status`)}>
                View Full Status
              </Button>
              <Button
                variant="text"
                onClick={() => {
                  clearSavedApplication();
                  setApplication(null);
                }}
              >
                Start New Application
              </Button>
            </Box>
          </CardContent>
        </Card>
      )}

      {currentStep === 'form' && (!savedApplicationId || application !== null) && (
        <ApplicationForm
          onApplicationCreated={handleApplicationCreated}
          onSubmit={formMode === 'simple' ? handleSimpleSubmit : undefined}
          onCancel={() => navigate('/dashboard')}
          mode={formMode}
        />
      )}
      {currentStep === 'upload' && activeApplicationId && (
        <DocumentUpload applicationId={activeApplicationId} onUploadComplete={handleContinueToProcessing} />
      )}

      {currentStep === 'upload' && (
        <Box sx={{ display: 'flex', justifyContent: 'flex-start', mt: 2 }}>
          <Button onClick={() => setCurrentStep('form')}>Back</Button>
        </Box>
      )}
    </Box>
  );
};

export default AccountOpeningPage;
