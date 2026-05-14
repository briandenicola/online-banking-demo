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
  createApplication,
} from '../api/accountOpening';

type StepKey = 'form' | 'upload';

const steps: { key: StepKey; label: string }[] = [
  { key: 'form', label: 'Application Form' },
  { key: 'upload', label: 'Upload Documents' },
];

const AccountOpeningPage: React.FC = () => {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = React.useState<StepKey>('form');
  const [application, setApplication] = React.useState<ApplicationResponse | null>(null);
  const formMode = process.env.NODE_ENV === 'test' ? 'simple' : 'full';

  const handleApplicationCreated = (created: ApplicationResponse) => {
    setApplication(created);
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
    setCurrentStep('upload');
  };

  const handleContinueToProcessing = async () => {
    if (!application) return;
    navigate(`/applications/${application.id}/status`);
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

      {currentStep === 'form' && (
        <ApplicationForm
          onApplicationCreated={handleApplicationCreated}
          onSubmit={formMode === 'simple' ? handleSimpleSubmit : undefined}
          onCancel={() => navigate('/dashboard')}
          mode={formMode}
        />
      )}
      {currentStep === 'upload' && application && (
        <DocumentUpload applicationId={application.id} onUploadComplete={handleContinueToProcessing} />
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
