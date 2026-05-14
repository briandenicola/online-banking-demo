import React from 'react';
import {
  Card,
  CardContent,
  Typography,
} from '@mui/material';
import ApplicationStages, { Stage } from './ApplicationStages';

export type StageStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export interface AgentStage {
  name: string;
  status: StageStatus;
  confidence?: number;
  reasoning?: string;
  details?: string;
  timestamp?: string;
}

interface AgentPipelineProps {
  stages: AgentStage[];
  currentStageIndex?: number;
}

const AgentPipeline: React.FC<AgentPipelineProps> = ({ stages, currentStageIndex }) => {
  const stagesData: Stage[] = stages.map((stage) => ({
    name: stage.name,
    status: stage.status,
    confidence: stage.confidence,
    reasoning: stage.reasoning,
    details: stage.details,
    timestamp: stage.timestamp,
  }));

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
          Application Processing Pipeline
        </Typography>
        <ApplicationStages stages={stagesData} currentStageIndex={currentStageIndex} showDetails />
      </CardContent>
    </Card>
  );
};

export default AgentPipeline;
