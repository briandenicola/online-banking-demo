import React from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  Step,
  StepLabel,
  Stepper,
  Typography,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import AutorenewIcon from '@mui/icons-material/Autorenew';

export type StageStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export interface Stage {
  name: string;
  status: StageStatus;
  confidence?: number;
  reasoning?: string;
  details?: string;
  timestamp?: string;
}

interface ApplicationStagesProps {
  stages: Stage[];
  currentStageIndex?: number;
  showDetails?: boolean;
}

const statusIcon = (status: StageStatus) => {
  switch (status) {
    case 'completed':
      return <CheckCircleIcon />;
    case 'failed':
      return <ErrorIcon />;
    case 'in_progress':
      return <AutorenewIcon />;
    default:
      return <HourglassEmptyIcon />;
  }
};

const statusLabel = (status: StageStatus) => status.replace('_', ' ').toUpperCase();

const resolveActiveIndex = (stages: Stage[], currentStageIndex?: number) => {
  if (typeof currentStageIndex === 'number') return currentStageIndex;
  const inProgressIndex = stages.findIndex((stage) => stage.status === 'in_progress');
  if (inProgressIndex >= 0) return inProgressIndex;
  const pendingIndex = stages.findIndex((stage) => stage.status === 'pending');
  return pendingIndex >= 0 ? pendingIndex : Math.max(stages.length - 1, 0);
};

const ApplicationStages: React.FC<ApplicationStagesProps> = ({
  stages,
  currentStageIndex,
  showDetails = true,
}) => {
  const [expandedIndex, setExpandedIndex] = React.useState<number | null>(null);
  const activeIndex = resolveActiveIndex(stages, currentStageIndex);
  const allPending = stages.length > 0 && stages.every((stage) => stage.status === 'pending');
  const highlightedPendingIndex = allPending
    ? -1
    : stages.findIndex((stage) => stage.status === 'pending');

  const toggleExpanded = (index: number) => {
    setExpandedIndex((prev) => (prev === index ? null : index));
  };

  return (
    <Box>
      <Stepper activeStep={activeIndex} alternativeLabel>
        {stages.map((stage, index) => (
          <Step key={stage.name}>
            <StepLabel
              onClick={() => toggleExpanded(index)}
              sx={{ cursor: 'pointer' }}
            >
              {stage.name}
            </StepLabel>
          </Step>
        ))}
      </Stepper>

      {showDetails && (
        <Box sx={{ mt: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {stages.map((stage, index) => (
            <Card key={stage.name} variant="outlined">
              <CardContent>
                <Box
                  sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                >
                  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                    {stage.name}
                  </Typography>
                  <Chip
                    icon={statusIcon(stage.status)}
                    label={
                      stage.status === 'pending'
                        ? (allPending || index === highlightedPendingIndex ? 'PENDING' : 'Pending')
                        : statusLabel(stage.status)
                    }
                    size="small"
                  />
                </Box>

                {stage.status === 'in_progress' && (
                  <LinearProgress sx={{ mt: 1 }} />
                )}

                {stage.details && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    {stage.details}
                  </Typography>
                )}

                {stage.confidence !== undefined && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    {Math.round(stage.confidence * 100)}% confidence
                  </Typography>
                )}

                {stage.timestamp && (
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                    {new Date(stage.timestamp).toLocaleString()}
                  </Typography>
                )}

                {expandedIndex === index && stage.reasoning && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    {stage.reasoning}
                  </Typography>
                )}
              </CardContent>
            </Card>
          ))}
        </Box>
      )}
    </Box>
  );
};

export default ApplicationStages;
