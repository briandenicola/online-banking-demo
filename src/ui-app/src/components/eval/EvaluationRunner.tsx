import React, { useState } from 'react';
import {
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  Button,
  CircularProgress,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Checkbox,
  LinearProgress,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import apiClient from '../../api/client';
import { EvalScoredTransaction } from './types';

interface EvaluationRunnerProps {
  open: boolean;
  templateId: string;
  transactions: EvalScoredTransaction[];
  onClose: () => void;
  onStarted: () => Promise<void> | void;
  onError: (message: string) => void;
}

const ScoreChip: React.FC<{ score: number; max?: number }> = ({ score, max = 5 }) => {
  const ratio = score / max;
  const color = ratio >= 0.6 ? 'success' : ratio >= 0.4 ? 'warning' : 'error';
  return <Chip label={score.toFixed(1)} color={color} size="small" />;
};

const EvaluationRunner: React.FC<EvaluationRunnerProps> = ({
  open,
  templateId,
  transactions,
  onClose,
  onStarted,
  onError,
}) => {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [running, setRunning] = useState(false);

  const handleClose = () => {
    setSelectedIds([]);
    onClose();
  };

  const toggle = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]
    );
  };

  const handleRun = async () => {
    if (!templateId || selectedIds.length === 0) return;
    setRunning(true);
    try {
      await apiClient.post('/evaluations/run', {
        templateId,
        transactionIds: selectedIds,
      });
      setSelectedIds([]);
      onClose();
      await onStarted();
    } catch {
      onError('Failed to start evaluation.');
    } finally {
      setRunning(false);
    }
  };

  const allSelected = selectedIds.length === transactions.length && transactions.length > 0;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>Run Evaluation</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Select transactions to evaluate against the selected prompt template.
        </Typography>
        {running && <LinearProgress sx={{ mb: 2 }} />}
        <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 400 }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox">
                  <Checkbox
                    checked={allSelected}
                    indeterminate={selectedIds.length > 0 && selectedIds.length < transactions.length}
                    onChange={() =>
                      setSelectedIds(allSelected ? [] : transactions.map((t) => t.id))
                    }
                  />
                </TableCell>
                <TableCell>Description</TableCell>
                <TableCell>Amount</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Risk Score</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {transactions.map((tx) => (
                <TableRow
                  key={tx.id}
                  hover
                  onClick={() => toggle(tx.id)}
                  sx={{ cursor: 'pointer' }}
                >
                  <TableCell padding="checkbox">
                    <Checkbox
                      checked={selectedIds.includes(tx.id)}
                      onChange={(e) => {
                        e.stopPropagation();
                        toggle(tx.id);
                      }}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </TableCell>
                  <TableCell>{tx.description || tx.type}</TableCell>
                  <TableCell>${tx.amount.toFixed(2)}</TableCell>
                  <TableCell>{tx.type}</TableCell>
                  <TableCell>
                    <ScoreChip score={tx.riskScore} max={1} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          {selectedIds.length} transaction(s) selected
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleRun}
          disabled={selectedIds.length === 0 || running}
          startIcon={running ? <CircularProgress size={16} /> : <PlayArrowIcon />}
        >
          Run Evaluation
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default EvaluationRunner;
