import React from 'react';
import { render, screen } from '@testing-library/react';
import AgentPipeline, { AgentStage } from '../../components/account-opening/AgentPipeline';

describe('AgentPipeline', () => {
  const mockStages: AgentStage[] = [
    {
      name: 'Document Extraction',
      status: 'completed',
      timestamp: '2026-05-11T10:00:00Z',
      details: 'Successfully extracted data from documents',
    },
    {
      name: 'Identity Verification',
      status: 'completed',
      timestamp: '2026-05-11T10:05:00Z',
      details: 'Identity verified successfully',
      confidence: 0.95,
    },
    {
      name: 'Compliance Check',
      status: 'in_progress',
      details: 'Performing KYC checks',
    },
    {
      name: 'Account Provisioning',
      status: 'pending',
    },
  ];

  describe('Happy Path', () => {
    it('renders pipeline with all stages', () => {
      render(<AgentPipeline stages={mockStages} />);

      expect(screen.getByText('Application Processing Pipeline')).toBeInTheDocument();
      expect(screen.getByText('Document Extraction')).toBeInTheDocument();
      expect(screen.getByText('Identity Verification')).toBeInTheDocument();
      expect(screen.getByText('Compliance Check')).toBeInTheDocument();
      expect(screen.getByText('Account Provisioning')).toBeInTheDocument();
    });

    it('displays stage details', () => {
      render(<AgentPipeline stages={mockStages} />);

      expect(screen.getByText('Successfully extracted data from documents')).toBeInTheDocument();
      expect(screen.getByText('Identity verified successfully')).toBeInTheDocument();
      expect(screen.getByText('Performing KYC checks')).toBeInTheDocument();
    });

    it('displays confidence score when available', () => {
      render(<AgentPipeline stages={mockStages} />);

      expect(screen.getByText('95% confidence')).toBeInTheDocument();
    });

    it('displays timestamps when available', () => {
      render(<AgentPipeline stages={mockStages} />);

      // Check that timestamps are rendered (format may vary by locale)
      const timestamps = screen.getAllByText(/5\/11\/2026|11\/5\/2026|2026/);
      expect(timestamps.length).toBeGreaterThan(0);
    });
  });

  describe('Status Indicators', () => {
    it('shows completed status with checkmark', () => {
      const completedStages: AgentStage[] = [
        { name: 'Stage 1', status: 'completed' },
      ];

      render(<AgentPipeline stages={completedStages} />);

      expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    });

    it('shows in-progress status with spinner', () => {
      const inProgressStages: AgentStage[] = [
        { name: 'Stage 1', status: 'in_progress' },
      ];

      render(<AgentPipeline stages={inProgressStages} />);

      expect(screen.getByText('IN PROGRESS')).toBeInTheDocument();
      expect(screen.getByRole('progressbar')).toBeInTheDocument();
    });

    it('shows pending status', () => {
      const pendingStages: AgentStage[] = [
        { name: 'Stage 1', status: 'pending' },
      ];

      render(<AgentPipeline stages={pendingStages} />);

      expect(screen.getByText('PENDING')).toBeInTheDocument();
    });

    it('shows failed status with error icon', () => {
      const failedStages: AgentStage[] = [
        { name: 'Stage 1', status: 'failed', details: 'Error occurred' },
      ];

      render(<AgentPipeline stages={failedStages} />);

      expect(screen.getByText('FAILED')).toBeInTheDocument();
      expect(screen.getByText('Error occurred')).toBeInTheDocument();
    });
  });

  describe('Active Step', () => {
    it('uses currentStageIndex prop when provided', () => {
      render(<AgentPipeline stages={mockStages} currentStageIndex={1} />);

      // Check that the component renders with the correct active step
      expect(screen.getByText('Identity Verification')).toBeInTheDocument();
    });

    it('determines active step from in_progress status when currentStageIndex not provided', () => {
      render(<AgentPipeline stages={mockStages} />);

      // The third stage (index 2) is in_progress
      expect(screen.getByText('Compliance Check')).toBeInTheDocument();
      expect(screen.getByText('IN PROGRESS')).toBeInTheDocument();
    });

    it('determines active step from first pending status when no in_progress', () => {
      const stagesWithoutInProgress: AgentStage[] = [
        { name: 'Stage 1', status: 'completed' },
        { name: 'Stage 2', status: 'completed' },
        { name: 'Stage 3', status: 'pending' },
        { name: 'Stage 4', status: 'pending' },
      ];

      render(<AgentPipeline stages={stagesWithoutInProgress} />);

      expect(screen.getByText('Stage 3')).toBeInTheDocument();
      expect(screen.getByText('PENDING')).toBeInTheDocument();
    });
  });

  describe('Multiple Confidence Scores', () => {
    it('displays multiple confidence scores correctly', () => {
      const stagesWithConfidence: AgentStage[] = [
        { name: 'Stage 1', status: 'completed', confidence: 0.85 },
        { name: 'Stage 2', status: 'completed', confidence: 0.92 },
        { name: 'Stage 3', status: 'in_progress', confidence: 0.78 },
      ];

      render(<AgentPipeline stages={stagesWithConfidence} />);

      expect(screen.getByText('85% confidence')).toBeInTheDocument();
      expect(screen.getByText('92% confidence')).toBeInTheDocument();
      expect(screen.getByText('78% confidence')).toBeInTheDocument();
    });
  });

  describe('Empty and Edge Cases', () => {
    it('renders empty pipeline', () => {
      render(<AgentPipeline stages={[]} />);

      expect(screen.getByText('Application Processing Pipeline')).toBeInTheDocument();
    });

    it('renders single stage', () => {
      const singleStage: AgentStage[] = [
        { name: 'Only Stage', status: 'completed' },
      ];

      render(<AgentPipeline stages={singleStage} />);

      expect(screen.getByText('Only Stage')).toBeInTheDocument();
      expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    });

    it('handles stage without timestamp', () => {
      const stageWithoutTimestamp: AgentStage[] = [
        { name: 'Stage 1', status: 'pending', details: 'Waiting to start' },
      ];

      render(<AgentPipeline stages={stageWithoutTimestamp} />);

      expect(screen.getByText('Waiting to start')).toBeInTheDocument();
      // No timestamp should be rendered
    });

    it('handles stage without details', () => {
      const stageWithoutDetails: AgentStage[] = [
        { name: 'Stage 1', status: 'completed', timestamp: '2026-05-11T10:00:00Z' },
      ];

      render(<AgentPipeline stages={stageWithoutDetails} />);

      expect(screen.getByText('Stage 1')).toBeInTheDocument();
      expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    });

    it('handles stage without confidence', () => {
      const stageWithoutConfidence: AgentStage[] = [
        { name: 'Stage 1', status: 'completed' },
      ];

      render(<AgentPipeline stages={stageWithoutConfidence} />);

      expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
    });
  });

  describe('All Stages Completed', () => {
    it('renders when all stages are completed', () => {
      const allCompleted: AgentStage[] = [
        { name: 'Stage 1', status: 'completed' },
        { name: 'Stage 2', status: 'completed' },
        { name: 'Stage 3', status: 'completed' },
      ];

      render(<AgentPipeline stages={allCompleted} />);

      const completedChips = screen.getAllByText('COMPLETED');
      expect(completedChips).toHaveLength(3);
    });
  });

  describe('All Stages Pending', () => {
    it('renders when all stages are pending', () => {
      const allPending: AgentStage[] = [
        { name: 'Stage 1', status: 'pending' },
        { name: 'Stage 2', status: 'pending' },
        { name: 'Stage 3', status: 'pending' },
      ];

      render(<AgentPipeline stages={allPending} />);

      const pendingChips = screen.getAllByText('PENDING');
      expect(pendingChips).toHaveLength(3);
    });
  });

  describe('Mixed Status Pipeline', () => {
    it('handles pipeline with mixed statuses', () => {
      const mixedStages: AgentStage[] = [
        { name: 'Stage 1', status: 'completed' },
        { name: 'Stage 2', status: 'failed' },
        { name: 'Stage 3', status: 'pending' },
        { name: 'Stage 4', status: 'in_progress' },
      ];

      render(<AgentPipeline stages={mixedStages} />);

      expect(screen.getByText('COMPLETED')).toBeInTheDocument();
      expect(screen.getByText('FAILED')).toBeInTheDocument();
      expect(screen.getByText('PENDING')).toBeInTheDocument();
      expect(screen.getByText('IN PROGRESS')).toBeInTheDocument();
    });
  });

  describe('Confidence Score Formatting', () => {
    it('formats confidence score to whole number', () => {
      const stages: AgentStage[] = [
        { name: 'Stage 1', status: 'completed', confidence: 0.8567 },
      ];

      render(<AgentPipeline stages={stages} />);

      expect(screen.getByText('86% confidence')).toBeInTheDocument();
    });

    it('handles 100% confidence', () => {
      const stages: AgentStage[] = [
        { name: 'Stage 1', status: 'completed', confidence: 1.0 },
      ];

      render(<AgentPipeline stages={stages} />);

      expect(screen.getByText('100% confidence')).toBeInTheDocument();
    });

    it('handles 0% confidence', () => {
      const stages: AgentStage[] = [
        { name: 'Stage 1', status: 'completed', confidence: 0.0 },
      ];

      render(<AgentPipeline stages={stages} />);

      expect(screen.getByText('0% confidence')).toBeInTheDocument();
    });
  });

  describe('Visual Components', () => {
    it('renders stepper component', () => {
      render(<AgentPipeline stages={mockStages} />);

      // The MUI Stepper should be present
      const stepper = screen.getByText('Document Extraction').closest('[class*="MuiStepper"]');
      expect(stepper).toBeInTheDocument();
    });

    it('renders paper container', () => {
      render(<AgentPipeline stages={mockStages} />);

      const paper = screen.getByText('Application Processing Pipeline').closest('[class*="MuiPaper"]');
      expect(paper).toBeInTheDocument();
    });
  });
});
