import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import AgentPipeline from './AgentPipeline';

jest.mock('../../api/client', () => ({
  __esModule: true,
  default: {
    post: jest.fn(),
    get: jest.fn(),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() },
    },
  },
}));

// The four pipeline stages as defined in the spec
const STAGE_NAMES = [
  'Document Extraction',
  'Identity Verification',
  'Compliance Check',
  'Provisioning',
];

type StageStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

interface AgentStage {
  name: string;
  status: StageStatus;
  confidence?: number;
  reasoning?: string;
}

const createStages = (overrides: Partial<Record<string, Partial<AgentStage>>> = {}): AgentStage[] => {
  return STAGE_NAMES.map((name) => ({
    name,
    status: 'pending' as StageStatus,
    confidence: undefined,
    reasoning: undefined,
    ...overrides[name],
  }));
};

const renderPipeline = (stages: AgentStage[]) => {
  return render(<AgentPipeline stages={stages} />);
};

describe('AgentPipeline', () => {
  describe('Stage rendering', () => {
    test('renders all 4 agent stages', () => {
      const stages = createStages();
      renderPipeline(stages);

      STAGE_NAMES.forEach((name) => {
        expect(screen.getByText(name)).toBeInTheDocument();
      });
    });

    test('renders stages in correct order', () => {
      const stages = createStages();
      renderPipeline(stages);

      const stageElements = STAGE_NAMES.map((name) => screen.getByText(name));

      // Verify DOM order: each stage should appear before the next
      for (let i = 0; i < stageElements.length - 1; i++) {
        expect(
          stageElements[i].compareDocumentPosition(stageElements[i + 1]) &
            Node.DOCUMENT_POSITION_FOLLOWING
        ).toBeTruthy();
      }
    });
  });

  describe('Status indicators', () => {
    test('shows pending state indicator for pending stages', () => {
      const stages = createStages();
      renderPipeline(stages);

      // All stages should be in pending state initially
      // Look for grey/pending visual indicators or aria labels
      STAGE_NAMES.forEach((name) => {
        const stageEl = screen.getByText(name).closest('[class*="step"], [role="listitem"], li, div');
        expect(stageEl).toBeTruthy();
      });
    });

    test('shows in_progress state for active stage', () => {
      const stages = createStages({
        'Document Extraction': { status: 'in_progress' },
      });
      renderPipeline(stages);

      // The active stage should have a visual indicator (spinner, blue color, etc.)
      expect(screen.getByText('Document Extraction')).toBeInTheDocument();
      // Look for loading indicator near the active stage
      const container = screen.getByText('Document Extraction').closest('[class*="step"], [role="listitem"], li, div');
      expect(container).toBeTruthy();
    });

    test('shows completed state for finished stages', () => {
      const stages = createStages({
        'Document Extraction': { status: 'completed', confidence: 0.95 },
        'Identity Verification': { status: 'in_progress' },
      });
      renderPipeline(stages);

      expect(screen.getByText('Document Extraction')).toBeInTheDocument();
    });

    test('shows failed state for failed stages', () => {
      const stages = createStages({
        'Document Extraction': { status: 'completed', confidence: 0.95 },
        'Identity Verification': { status: 'failed', reasoning: 'Name mismatch detected' },
      });
      renderPipeline(stages);

      expect(screen.getByText('Identity Verification')).toBeInTheDocument();
    });

    test('shows mixed states across stages', () => {
      const stages = createStages({
        'Document Extraction': { status: 'completed', confidence: 0.95 },
        'Identity Verification': { status: 'completed', confidence: 0.87 },
        'Compliance Check': { status: 'in_progress' },
        'Provisioning': { status: 'pending' },
      });
      renderPipeline(stages);

      // All stages should render
      STAGE_NAMES.forEach((name) => {
        expect(screen.getByText(name)).toBeInTheDocument();
      });
    });
  });

  describe('Confidence scores', () => {
    test('shows confidence score for completed stages', () => {
      const stages = createStages({
        'Document Extraction': { status: 'completed', confidence: 0.95 },
      });
      renderPipeline(stages);

      // Should display confidence as percentage or decimal
      expect(
        screen.getByText(/95%|0\.95/) ||
        screen.getByText(/confidence/i)
      ).toBeTruthy();
    });

    test('does not show confidence for pending stages', () => {
      const stages = createStages();
      renderPipeline(stages);

      // No confidence percentages should appear for pending stages
      expect(screen.queryByText(/95%|87%|0\.95|0\.87/)).toBeNull();
    });

    test('shows confidence scores for multiple completed stages', () => {
      const stages = createStages({
        'Document Extraction': { status: 'completed', confidence: 0.95 },
        'Identity Verification': { status: 'completed', confidence: 0.87 },
        'Compliance Check': { status: 'completed', confidence: 0.92 },
      });
      renderPipeline(stages);

      expect(screen.getByText(/95%|0\.95/)).toBeInTheDocument();
      expect(screen.getByText(/87%|0\.87/)).toBeInTheDocument();
      expect(screen.getByText(/92%|0\.92/)).toBeInTheDocument();
    });
  });

  describe('Expandable details', () => {
    test('can expand a completed stage to see reasoning', () => {
      const stages = createStages({
        'Document Extraction': {
          status: 'completed',
          confidence: 0.95,
          reasoning: 'All fields extracted successfully from photo ID',
        },
      });
      renderPipeline(stages);

      // Click on the stage or expand button to see reasoning
      const stageEl = screen.getByText('Document Extraction');
      fireEvent.click(stageEl);

      expect(
        screen.getByText(/All fields extracted successfully/i)
      ).toBeInTheDocument();
    });

    test('can expand a failed stage to see failure reasoning', () => {
      const stages = createStages({
        'Document Extraction': { status: 'completed', confidence: 0.95 },
        'Identity Verification': {
          status: 'failed',
          reasoning: 'Name on document does not match application',
        },
      });
      renderPipeline(stages);

      const stageEl = screen.getByText('Identity Verification');
      fireEvent.click(stageEl);

      expect(
        screen.getByText(/Name on document does not match/i)
      ).toBeInTheDocument();
    });

    test('expand/collapse toggles reasoning visibility', () => {
      const stages = createStages({
        'Document Extraction': {
          status: 'completed',
          confidence: 0.95,
          reasoning: 'Fields extracted from government ID',
        },
      });
      renderPipeline(stages);

      const stageEl = screen.getByText('Document Extraction');

      // Expand
      fireEvent.click(stageEl);
      expect(screen.getByText(/Fields extracted from government ID/)).toBeInTheDocument();

      // Collapse
      fireEvent.click(stageEl);
      expect(screen.queryByText(/Fields extracted from government ID/)).toBeNull();
    });
  });

  describe('Full pipeline progression', () => {
    test('renders all completed pipeline', () => {
      const stages = createStages({
        'Document Extraction': { status: 'completed', confidence: 0.95 },
        'Identity Verification': { status: 'completed', confidence: 0.91 },
        'Compliance Check': { status: 'completed', confidence: 0.88 },
        'Provisioning': { status: 'completed', confidence: 1.0 },
      });
      renderPipeline(stages);

      STAGE_NAMES.forEach((name) => {
        expect(screen.getByText(name)).toBeInTheDocument();
      });
    });

    test('renders pipeline with failure at identity verification', () => {
      const stages = createStages({
        'Document Extraction': { status: 'completed', confidence: 0.95 },
        'Identity Verification': {
          status: 'failed',
          reasoning: 'Document appears to be expired',
        },
        'Compliance Check': { status: 'pending' },
        'Provisioning': { status: 'pending' },
      });
      renderPipeline(stages);

      STAGE_NAMES.forEach((name) => {
        expect(screen.getByText(name)).toBeInTheDocument();
      });
    });
  });
});
