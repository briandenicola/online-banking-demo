import apiClient from './client';

export const ACCOUNT_OPENING_STORAGE_KEY = 'account_opening_application_id';

export type AccountType = 'checking' | 'savings' | 'both';
export type DocumentType = 'photo_id' | 'proof_of_address' | 'proof_of_income';
export type ApplicationStatus =
  | 'submitted'
  | 'document_extraction'
  | 'identity_verification'
  | 'compliance_check'
  | 'pending_review'
  | 'approved'
  | 'rejected';

export interface ApplicationFormData {
  firstName: string;
  lastName: string;
  dateOfBirth: string;
  email: string;
  phone?: string;
  address?: string;
  street?: string;
  city?: string;
  state?: string;
  zip?: string;
  zipCode?: string;
  employment?: string;
  employer?: string;
  title?: string;
  employmentStatus?: string;
  annualIncome?: number;
  accountType: AccountType;
  ssnLastFour?: string;
  initialDeposit?: number;
}

/**
 * Wire-shape payload for POST /account-opening/applications.
 * Mirrors the FastAPI `ApplicationCreate` model in
 * `src/account-opening-service/app/models/__init__.py` — keep these in sync.
 */
export interface AddressPayload {
  street: string;
  city: string;
  state: string;
  zip: string;
  country: string;
}

export interface EmploymentPayload {
  employer: string;
  title: string;
  annualIncome: number;
}

export interface ApplicationCreateRequest {
  firstName: string;
  lastName: string;
  dateOfBirth: string;
  email: string;
  phone: string;
  ssn: string;
  address: AddressPayload;
  employment?: EmploymentPayload;
  accountType: AccountType;
}

export interface AgentStage {
  name: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  confidence?: number;
  reasoning?: string;
}

export interface AuditEntry {
  timestamp: string;
  agent: string;
  action: string;
  reasoning?: string;
}

export interface ApplicationResponse {
  id: string;
  status: ApplicationStatus;
  createdAt: string;
  updatedAt?: string;
  formData?: ApplicationFormData;
  firstName?: string;
  lastName?: string;
  email?: string;
  userId?: string;
  accountId?: string;
  agentResults?: Record<string, unknown>;
  stages?: AgentStage[];
  documents?: DocumentUploadResponse[];
  auditTrail?: AuditEntry[];
  riskTier?: string;
}

export interface DocumentUploadResponse {
  id?: string;
  documentIds?: string[];
  type?: DocumentType;
  blobUrl?: string;
  uploadedAt?: string;
}

export interface ReviewDecisionRequest {
  decision: 'approved' | 'rejected' | 'pending_review';
  notes?: string;
}

export const createApplication = async (applicationData: ApplicationCreateRequest): Promise<ApplicationResponse> => {
  const response = await apiClient.post('/account-opening/applications', applicationData);
  return response.data;
};

export const uploadDocuments = async (
  applicationId: string,
  file: File,
  documentType: DocumentType
): Promise<DocumentUploadResponse> => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('documentType', documentType);
  const response = await apiClient.post(`/account-opening/applications/${applicationId}/documents`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const uploadDocument = async (
  applicationId: string,
  file: File,
  documentType: DocumentType
): Promise<DocumentUploadResponse> => {
  return uploadDocuments(applicationId, file, documentType);
};

export const getApplication = async (applicationId: string): Promise<ApplicationResponse> => {
  const response = await apiClient.get(`/account-opening/applications/${applicationId}`);
  return response.data;
};

export const getAuditTrail = async (applicationId: string) => {
  const response = await apiClient.get(`/account-opening/applications/${applicationId}/audit`);
  return response.data;
};

export const listApplications = async (
  params?: Record<string, unknown> | ApplicationStatus
): Promise<ApplicationResponse[] | { items: ApplicationResponse[]; total: number }> => {
  const query = typeof params === 'string' ? { status: params } : params;
  const response = await apiClient.get('/account-opening/applications', {
    params: query ?? undefined,
  });
  return response.data;
};

export const reviewApplication = async (
  applicationId: string,
  review: ReviewDecisionRequest
): Promise<ApplicationResponse> => {
  const response = await apiClient.patch(`/account-opening/applications/${applicationId}/review`, review);
  return response.data;
};
