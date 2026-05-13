import React from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Grid,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
} from '@mui/material';
import {
  ApplicationFormData as ApiApplicationFormData,
  ApplicationCreateRequest,
  ApplicationResponse,
  createApplication,
} from '../../api/accountOpening';
import { resolveApiError } from '../../api/errors';

export type ApplicationFormData = ApiApplicationFormData;

type FormMode = 'full' | 'simple';

interface ApplicationFormProps {
  onSubmit?: (payload: ApplicationFormData) => void;
  onApplicationCreated?: (application: ApplicationResponse) => void;
  onCancel?: () => void;
  mode?: FormMode;
  initialData?: ApplicationFormData;
}

interface FormState {
  firstName: string;
  lastName: string;
  dateOfBirth: string;
  email: string;
  phone: string;
  ssnLastFour: string;
  address: string;
  street: string;
  city: string;
  state: string;
  zip: string;
  zipCode: string;
  employment: string;
  employer: string;
  title: string;
  employmentStatus: string;
  annualIncome: string;
  accountType: ApplicationFormData['accountType'];
  initialDeposit: string;
}

const fullSteps = [
  'Personal Info',
  'Address',
  'Employment & Income',
  'Account Preferences',
  'Review',
];

const simpleSteps = ['Personal Information', 'Contact Details', 'Financial Information'];

const resolveInitialState = (initialData?: ApplicationFormData): FormState => ({
  firstName: initialData?.firstName ?? '',
  lastName: initialData?.lastName ?? '',
  dateOfBirth: initialData?.dateOfBirth ?? '',
  email: initialData?.email ?? '',
  phone: initialData?.phone ?? '',
  ssnLastFour: initialData?.ssnLastFour ?? '',
  address: initialData?.address ?? '',
  street: initialData?.street ?? '',
  city: initialData?.city ?? '',
  state: initialData?.state ?? '',
  zip: initialData?.zip ?? '',
  zipCode: initialData?.zipCode ?? '',
  employment: initialData?.employment ?? '',
  employer: initialData?.employer ?? '',
  title: initialData?.title ?? '',
  employmentStatus: initialData?.employmentStatus ?? '',
  annualIncome:
    typeof initialData?.annualIncome === 'number'
      ? String(initialData.annualIncome)
      : '',
  accountType: initialData?.accountType ?? 'checking',
  initialDeposit:
    typeof initialData?.initialDeposit === 'number'
      ? String(initialData.initialDeposit)
      : '',
});

const isAdult = (dateString: string) => {
  if (!dateString) return false;
  const dob = new Date(dateString);
  if (Number.isNaN(dob.getTime())) return false;
  const now = new Date();
  const adultDate = new Date(
    now.getFullYear() - 18,
    now.getMonth(),
    now.getDate()
  );
  return dob <= adultDate;
};

const ApplicationForm: React.FC<ApplicationFormProps> = ({
  onSubmit,
  onApplicationCreated,
  onCancel,
  mode,
  initialData,
}) => {
  const resolvedMode: FormMode = mode ?? (onApplicationCreated ? 'full' : 'simple');
  const steps = resolvedMode === 'full' ? fullSteps : simpleSteps;
  const [activeStep, setActiveStep] = React.useState(0);
  const [values, setValues] = React.useState<FormState>(() => resolveInitialState(initialData));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (initialData) {
      setValues(resolveInitialState(initialData));
    }
  }, [initialData]);

  const handleChange = (field: keyof FormState) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
      const nextValue = event.target.value;
      setValues((prev) => ({ ...prev, [field]: nextValue }));
      if (errors[field]) {
        setErrors((prev) => {
          const next = { ...prev };
          delete next[field];
          return next;
        });
      }
    };

  const validateSimpleStep = (step: number) => {
    const nextErrors: Record<string, string> = {};

    if (step === 0) {
      if (!values.firstName.trim()) nextErrors.firstName = 'First name is required';
      if (!values.lastName.trim()) nextErrors.lastName = 'Last name is required';
      if (!values.dateOfBirth) {
        nextErrors.dateOfBirth = 'Date of birth is required';
      } else if (!isAdult(values.dateOfBirth)) {
        nextErrors.dateOfBirth = 'Must be at least 18 years old';
      }
    }

    if (step === 1) {
      if (!values.email.trim()) {
        nextErrors.email = 'Email is required';
      } else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email)) {
        nextErrors.email = 'Invalid email format';
      }

      if (!values.phone.trim()) {
        nextErrors.phone = 'Phone number is required';
      } else {
        const digits = values.phone.replace(/\D/g, '');
        if (digits.length < 10) {
          nextErrors.phone = 'Invalid phone format';
        }
      }

      if (!values.address.trim()) nextErrors.address = 'Address is required';
      if (!values.city.trim()) nextErrors.city = 'City is required';
      if (!values.state.trim()) nextErrors.state = 'State is required';
      if (!values.zipCode.trim()) {
        nextErrors.zipCode = 'ZIP code is required';
      } else if (!/^\d{5}(-\d{4})?$/.test(values.zipCode.trim())) {
        nextErrors.zipCode = 'Invalid ZIP code format';
      }
    }

    if (step === 2) {
      if (!values.employment.trim()) nextErrors.employment = 'Employment is required';
      if (!values.annualIncome.trim()) {
        nextErrors.annualIncome = 'Annual income is required';
      } else if (Number(values.annualIncome) <= 0) {
        nextErrors.annualIncome = 'Annual income must be greater than 0';
      }
      if (!values.accountType) nextErrors.accountType = 'Account type is required';
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const validateFullStep = (step: number) => {
    const nextErrors: Record<string, string> = {};

    if (step === 0) {
      if (!values.firstName.trim()) nextErrors.firstName = 'First name is required';
      if (!values.lastName.trim()) nextErrors.lastName = 'Last name is required';
      if (!values.dateOfBirth) {
        nextErrors.dateOfBirth = 'Date of birth is required';
      } else if (!isAdult(values.dateOfBirth)) {
        nextErrors.dateOfBirth = 'Must be at least 18 years old';
      }
      if (!values.email.trim()) {
        nextErrors.email = 'Email is required';
      } else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email)) {
        nextErrors.email = 'Enter a valid email';
      }
      if (!values.phone.trim()) nextErrors.phone = 'Phone number is required';
      if (!values.ssnLastFour.trim()) {
        nextErrors.ssnLastFour = 'SSN last 4 is required';
      } else if (!/^\d{4}$/.test(values.ssnLastFour.trim())) {
        nextErrors.ssnLastFour = 'Enter exactly 4 digits';
      }
    }

    if (step === 1) {
      if (!values.street.trim()) nextErrors.street = 'Street is required';
      if (!values.city.trim()) nextErrors.city = 'City is required';
      if (!values.state.trim()) nextErrors.state = 'State is required';
      if (!values.zip.trim()) nextErrors.zip = 'ZIP is required';
    }

    if (step === 2) {
      if (!values.employer.trim()) nextErrors.employer = 'Employer is required';
      if (!values.title.trim()) nextErrors.title = 'Title is required';
      if (!values.annualIncome.trim()) {
        nextErrors.annualIncome = 'Annual income is required';
      } else if (Number.isNaN(Number(values.annualIncome))) {
        nextErrors.annualIncome = 'Enter a valid income';
      }
      if (!values.employmentStatus.trim()) {
        nextErrors.employmentStatus = 'Employment status is required';
      }
    }

    if (step === 3) {
      if (!values.accountType) nextErrors.accountType = 'Account type is required';
      if (!values.initialDeposit.trim()) {
        nextErrors.initialDeposit = 'Initial deposit is required';
      } else if (Number.isNaN(Number(values.initialDeposit))) {
        nextErrors.initialDeposit = 'Enter a valid deposit';
      }
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const validateStep = (step: number) =>
    resolvedMode === 'full' ? validateFullStep(step) : validateSimpleStep(step);

  const buildPayload = (): ApplicationFormData => {
    if (resolvedMode === 'simple') {
      return {
        firstName: values.firstName.trim(),
        lastName: values.lastName.trim(),
        dateOfBirth: values.dateOfBirth,
        email: values.email.trim(),
        phone: values.phone.trim(),
        address: values.address.trim(),
        city: values.city.trim(),
        state: values.state.trim(),
        zipCode: values.zipCode.trim(),
        employment: values.employment.trim(),
        annualIncome: Number(values.annualIncome),
        accountType: values.accountType,
      };
    }

    return {
      firstName: values.firstName.trim(),
      lastName: values.lastName.trim(),
      dateOfBirth: values.dateOfBirth,
      email: values.email.trim(),
      phone: values.phone.trim(),
      ssnLastFour: values.ssnLastFour.trim(),
      street: values.street.trim(),
      city: values.city.trim(),
      state: values.state.trim(),
      zip: values.zip.trim(),
      employer: values.employer.trim(),
      title: values.title.trim(),
      annualIncome: Number(values.annualIncome),
      employmentStatus: values.employmentStatus,
      accountType: values.accountType,
      initialDeposit: Number(values.initialDeposit),
    };
  };

  // Wire-shape payload for the backend. Backend `ApplicationCreate` requires
  // nested `address` (with country) and `employment`, and field name `ssn`.
  // Country is hard-coded to 'US' until a country picker is added (see #127).
  const buildCreateRequest = (formData: ApplicationFormData): ApplicationCreateRequest => ({
    firstName: formData.firstName,
    lastName: formData.lastName,
    dateOfBirth: formData.dateOfBirth,
    email: formData.email,
    phone: (formData.phone ?? '').trim(),
    ssn: (formData.ssnLastFour ?? '').trim(),
    address: {
      street: (formData.street ?? '').trim(),
      city: (formData.city ?? '').trim(),
      state: (formData.state ?? '').trim(),
      zip: (formData.zip ?? '').trim(),
      country: 'US',
    },
    employment: {
      employer: (formData.employer ?? '').trim(),
      title: (formData.title ?? '').trim(),
      annualIncome: Number(formData.annualIncome ?? 0),
    },
    accountType: formData.accountType,
  });

  const handleNext = () => {
    if (validateStep(activeStep)) {
      setActiveStep((prev) => prev + 1);
    }
  };

  const handleBack = () => {
    setActiveStep((prev) => prev - 1);
  };

  const handleSubmit = async () => {
    if (!validateStep(activeStep)) return;
    const payload = buildPayload();
    setSubmitting(true);
    setSubmitError(null);
    try {
      await Promise.resolve(onSubmit?.(payload));
      if (resolvedMode === 'simple') return;
      const application = await createApplication(buildCreateRequest(payload));
      onApplicationCreated?.(application);
    } catch (error: unknown) {
      setSubmitError(resolveApiError(error, 'Failed to submit application. Please try again.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>
        Account Opening Application
      </Typography>
      <Stepper activeStep={activeStep} alternativeLabel>
        {steps.map((label) => (
          <Step key={label}>
            <StepLabel>{label}</StepLabel>
          </Step>
        ))}
      </Stepper>

      {submitError && (
        <Alert severity="error" sx={{ mt: 3 }} onClose={() => setSubmitError(null)}>
          {submitError}
        </Alert>
      )}

      <Card sx={{ mt: 3 }}>
        <CardContent>
          {resolvedMode === 'full' && activeStep === 0 && (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="First Name"
                  value={values.firstName}
                  onChange={handleChange('firstName')}
                  error={Boolean(errors.firstName)}
                  helperText={errors.firstName}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Last Name"
                  value={values.lastName}
                  onChange={handleChange('lastName')}
                  error={Boolean(errors.lastName)}
                  helperText={errors.lastName}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Date of Birth"
                  type="date"
                  slotProps={{ inputLabel: { shrink: true } }}
                  value={values.dateOfBirth}
                  onChange={handleChange('dateOfBirth')}
                  error={Boolean(errors.dateOfBirth)}
                  helperText={errors.dateOfBirth}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Email"
                  value={values.email}
                  onChange={handleChange('email')}
                  error={Boolean(errors.email)}
                  helperText={errors.email}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Phone"
                  value={values.phone}
                  onChange={handleChange('phone')}
                  error={Boolean(errors.phone)}
                  helperText={errors.phone}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="SSN (Last 4)"
                  value={values.ssnLastFour}
                  onChange={handleChange('ssnLastFour')}
                  error={Boolean(errors.ssnLastFour)}
                  helperText={errors.ssnLastFour}
                />
              </Grid>
            </Grid>
          )}

          {resolvedMode === 'simple' && activeStep === 0 && (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="First Name"
                  value={values.firstName}
                  onChange={handleChange('firstName')}
                  error={Boolean(errors.firstName)}
                  helperText={errors.firstName}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Last Name"
                  value={values.lastName}
                  onChange={handleChange('lastName')}
                  error={Boolean(errors.lastName)}
                  helperText={errors.lastName}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Date of Birth"
                  type="date"
                  slotProps={{ inputLabel: { shrink: true } }}
                  value={values.dateOfBirth}
                  onChange={handleChange('dateOfBirth')}
                  error={Boolean(errors.dateOfBirth)}
                  helperText={errors.dateOfBirth}
                />
              </Grid>
            </Grid>
          )}

          {resolvedMode === 'full' && activeStep === 1 && (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12 }}>
                <TextField
                  fullWidth
                  label="Street"
                  value={values.street}
                  onChange={handleChange('street')}
                  error={Boolean(errors.street)}
                  helperText={errors.street}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="City"
                  value={values.city}
                  onChange={handleChange('city')}
                  error={Boolean(errors.city)}
                  helperText={errors.city}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 3 }}>
                <TextField
                  fullWidth
                  label="State"
                  value={values.state}
                  onChange={handleChange('state')}
                  error={Boolean(errors.state)}
                  helperText={errors.state}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 3 }}>
                <TextField
                  fullWidth
                  label="Zip"
                  value={values.zip}
                  onChange={handleChange('zip')}
                  error={Boolean(errors.zip)}
                  helperText={errors.zip}
                />
              </Grid>
            </Grid>
          )}

          {resolvedMode === 'simple' && activeStep === 1 && (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Email"
                  value={values.email}
                  onChange={handleChange('email')}
                  error={Boolean(errors.email)}
                  helperText={errors.email}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Phone"
                  value={values.phone}
                  onChange={handleChange('phone')}
                  error={Boolean(errors.phone)}
                  helperText={errors.phone}
                />
              </Grid>
              <Grid size={{ xs: 12 }}>
                <TextField
                  fullWidth
                  label="Address"
                  value={values.address}
                  onChange={handleChange('address')}
                  error={Boolean(errors.address)}
                  helperText={errors.address}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="City"
                  value={values.city}
                  onChange={handleChange('city')}
                  error={Boolean(errors.city)}
                  helperText={errors.city}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 3 }}>
                <TextField
                  fullWidth
                  label="State"
                  value={values.state}
                  onChange={handleChange('state')}
                  error={Boolean(errors.state)}
                  helperText={errors.state}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 3 }}>
                <TextField
                  fullWidth
                  label="Zip Code"
                  value={values.zipCode}
                  onChange={handleChange('zipCode')}
                  error={Boolean(errors.zipCode)}
                  helperText={errors.zipCode}
                />
              </Grid>
            </Grid>
          )}

          {resolvedMode === 'full' && activeStep === 2 && (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Employer"
                  value={values.employer}
                  onChange={handleChange('employer')}
                  error={Boolean(errors.employer)}
                  helperText={errors.employer}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Title"
                  value={values.title}
                  onChange={handleChange('title')}
                  error={Boolean(errors.title)}
                  helperText={errors.title}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Annual Income"
                  value={values.annualIncome}
                  onChange={handleChange('annualIncome')}
                  error={Boolean(errors.annualIncome)}
                  helperText={errors.annualIncome}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                  <TextField
                    fullWidth
                    select
                    label="Employment Status"
                  value={values.employmentStatus}
                  onChange={handleChange('employmentStatus')}
                  error={Boolean(errors.employmentStatus)}
                  helperText={errors.employmentStatus}
                  slotProps={{ select: { native: true } }}
                >
                    <option value="" />
                    <option value="employed">Employed</option>
                    <option value="self-employed">Self-Employed</option>
                    <option value="unemployed">Unemployed</option>
                    <option value="retired">Retired</option>
                  </TextField>
                </Grid>
              </Grid>
            )}

          {resolvedMode === 'simple' && activeStep === 2 && (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Employment"
                  value={values.employment}
                  onChange={handleChange('employment')}
                  error={Boolean(errors.employment)}
                  helperText={errors.employment}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Annual Income"
                  value={values.annualIncome}
                  onChange={handleChange('annualIncome')}
                  error={Boolean(errors.annualIncome)}
                  helperText={errors.annualIncome}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  select
                  label="Account Type"
                  value={values.accountType}
                  onChange={handleChange('accountType')}
                  error={Boolean(errors.accountType)}
                  helperText={errors.accountType}
                  slotProps={{ select: { native: true } }}
                >
                  <option value="checking">Checking</option>
                  <option value="savings">Savings</option>
                  <option value="both">Checking + Savings</option>
                </TextField>
              </Grid>
            </Grid>
          )}

          {resolvedMode === 'full' && activeStep === 3 && (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  select
                  label="Account Type"
                  value={values.accountType}
                  onChange={handleChange('accountType')}
                  error={Boolean(errors.accountType)}
                  helperText={errors.accountType}
                  slotProps={{ select: { native: true } }}
                >
                  <option value="checking">Checking</option>
                  <option value="savings">Savings</option>
                  <option value="both">Checking + Savings</option>
                </TextField>
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <TextField
                  fullWidth
                  label="Initial Deposit"
                  value={values.initialDeposit}
                  onChange={handleChange('initialDeposit')}
                  error={Boolean(errors.initialDeposit)}
                  helperText={errors.initialDeposit}
                />
              </Grid>
            </Grid>
          )}

          {resolvedMode === 'full' && activeStep === 4 && (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12 }}>
                <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>
                  Review & Submit
                </Typography>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <Typography variant="subtitle2" color="text.secondary">
                  Personal Info
                </Typography>
                <Typography>
                  {values.firstName} {values.lastName}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {values.email}
                </Typography>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <Typography variant="subtitle2" color="text.secondary">
                  Address
                </Typography>
                <Typography>{values.street}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {values.city}, {values.state} {values.zip}
                </Typography>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <Typography variant="subtitle2" color="text.secondary">
                  Employment
                </Typography>
                <Typography>{values.employer}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {values.title} · {values.employmentStatus}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Annual income: ${Number(values.annualIncome || 0).toLocaleString()}
                </Typography>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <Typography variant="subtitle2" color="text.secondary">
                  Account Preferences
                </Typography>
                <Typography>
                  {values.accountType === 'both' ? 'Checking + Savings' : values.accountType}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Initial deposit: ${Number(values.initialDeposit || 0).toLocaleString()}
                </Typography>
              </Grid>
            </Grid>
          )}
        </CardContent>
      </Card>

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3, flexWrap: 'wrap', gap: 1 }}>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button disabled={activeStep === 0} onClick={handleBack}>
            Back
          </Button>
          {onCancel && (
            <Button color="secondary" onClick={onCancel}>
              Cancel
            </Button>
          )}
        </Box>
        {activeStep < steps.length - 1 ? (
          <Button variant="contained" onClick={handleNext}>
            Next
          </Button>
        ) : (
          <Button variant="contained" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Submitting...' : 'Submit'}
          </Button>
        )}
      </Box>
    </Box>
  );
};

export default ApplicationForm;
