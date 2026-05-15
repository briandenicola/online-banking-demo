export interface PromptTemplate {
  id: string;
  name: string;
  description?: string;
  target: string;
  systemPrompt: string;
  version: number;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface QualityScores {
  coherence: number;
  fluency: number;
  relevance: number;
  passRate: number;
}

export interface SafetyResult {
  passed: boolean;
  averageScore: number;
  failedCount: number;
}

export interface SafetyScores {
  violence: SafetyResult;
  hateUnfairness: SafetyResult;
  selfHarm: SafetyResult;
  sexual: SafetyResult;
}

export interface EvaluationRunSummary {
  id: string;
  templateId: string;
  templateName: string;
  templateVersion: number;
  status: string;
  transactionCount: number;
  qualityScores?: QualityScores;
  safetyScores?: SafetyScores;
  createdAt: string;
  completedAt?: string;
}

export interface EvaluationOutputItem {
  transactionId: string;
  query: string;
  response: string;
  queryMessages?: unknown[];
  responseMessages?: unknown[];
  scores?: Record<string, { score: number; passed: boolean }>;
  status?: string;
  coherenceScore: number;
  fluencyScore: number;
  relevanceScore: number;
  safetyPassed: boolean;
  safetyDetails: Record<string, number>;
  adminDecision?: string;
  adminNotes?: string;
  reviewedBy?: string;
  reviewedAt?: string;
}

export interface EvaluationRunDetail extends EvaluationRunSummary {
  outputItems?: EvaluationOutputItem[];
  error?: string;
}

export interface EvalScoredTransaction {
  id: string;
  transactionId: string;
  amount: number;
  type: string;
  description: string;
  riskScore: number;
}

export interface ActivePrompt {
  name: string;
  type: string;
  enabled: boolean;
  systemPrompt?: string;
}
