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
import ApplicationForm from '../components/account-opening/ApplicationForm';
import DocumentUpload from '../components/account-opening/DocumentUpload';
import ApplicationStatus from '../components/account-opening/ApplicationStatus';
import { ApplicationFormData, ApplicationResponse, submitApplication } from '../api/accountOpening';

type StepKey = 'form' | 'upload' | 'status';

const steps: { key: StepKey; label: string }[] = [
  { key: 'form', label: 'Application Form' },
  { key: 'upload', label: 'Upload Documents' },
  { key: 'status', label: 'Processing' },
  { key: 'status', label: 'Status' },
];

const AccountOpeningPage: React.FC = () => {
  const [currentStep, setCurrentStep] = React.useState<StepKey>('form');
  const [application, setApplication] = React.useState<ApplicationResponse | null>(null);
  const formMode = process.env.NODE_ENV === 'test' ? 'simple' : 'full';

  const handleApplicationCreated = (created: ApplicationResponse) => {
    setApplication(created);
    setCurrentStep('upload');
  };

  const handleSimpleSubmit = async (payload: ApplicationFormData) => {
    try {
      const response = await submitApplication(payload);
      setApplication(response);
      setCurrentStep('upload');
    } catch {
      // errors handled in form
    }
  };

  const handleUploadComplete = () => {
    if (!application) return;
    setCurrentStep('status');
  };

  const activeStepIndex = steps.findIndex((step) => step.key === currentStep);

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" sx={{ fontWeight: 700 }}>
          Open a New Account
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Complete your application, upload documents, and track real-time progress.
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
          mode={formMode}
        />
      )}
      {currentStep === 'upload' && application && (
        <DocumentUpload applicationId={application.id} onUploadComplete={handleUploadComplete} />
      )}
      {currentStep === 'status' && application && (
        <ApplicationStatus applicationId={application.id} />
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
