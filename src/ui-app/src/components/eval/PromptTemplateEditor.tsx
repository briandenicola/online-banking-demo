import React, { useState } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Grid,
  Chip,
  Button,
  TextField,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  IconButton,
  Tooltip,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import apiClient from '../../api/client';
import { PromptTemplate, ActivePrompt } from './types';

interface PromptTemplateEditorProps {
  templates: PromptTemplate[];
  activePrompts: ActivePrompt[];
  onChanged: () => Promise<void> | void;
  onRunRequested: (templateId: string) => void;
  onError: (message: string) => void;
}

const PromptTemplateEditor: React.FC<PromptTemplateEditorProps> = ({
  templates,
  activePrompts,
  onChanged,
  onRunRequested,
  onError,
}) => {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<PromptTemplate | null>(null);
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formTarget, setFormTarget] = useState('risk-scoring');
  const [formPrompt, setFormPrompt] = useState('');

  const resetForm = () => {
    setFormName('');
    setFormDescription('');
    setFormTarget('risk-scoring');
    setFormPrompt('');
  };

  const openEdit = (t: PromptTemplate) => {
    setEditing(t);
    setFormName(t.name);
    setFormDescription(t.description || '');
    setFormTarget(t.target);
    setFormPrompt(t.systemPrompt);
    setDialogOpen(true);
  };

  const openNew = () => {
    resetForm();
    setEditing(null);
    setDialogOpen(true);
  };

  const handleSave = async () => {
    try {
      if (editing) {
        await apiClient.put(`/evaluations/prompts/${editing.id}`, {
          name: formName,
          description: formDescription,
          systemPrompt: formPrompt,
        });
      } else {
        await apiClient.post('/evaluations/prompts', {
          name: formName,
          description: formDescription,
          target: formTarget,
          systemPrompt: formPrompt,
        });
      }
      setDialogOpen(false);
      resetForm();
      await onChanged();
    } catch {
      onError('Failed to save template.');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await apiClient.delete(`/evaluations/prompts/${id}`);
      await onChanged();
    } catch {
      onError('Failed to delete template.');
    }
  };

  return (
    <>
      {/* Active Prompts Section */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Active AI Prompts
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          These are the system prompts currently used by the AI service for risk scoring and
          categorization.
        </Typography>
        <Grid container spacing={2}>
          {activePrompts.map((prompt, idx) => (
            <Grid size={{ xs: 12, md: 6 }} key={idx}>
              <Card variant="outlined">
                <CardContent>
                  <Box
                    sx={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      mb: 1,
                    }}
                  >
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                      {prompt.name}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Chip label={prompt.type} size="small" variant="outlined" />
                      <Chip
                        label={prompt.enabled ? 'Active' : 'Disabled'}
                        color={prompt.enabled ? 'success' : 'default'}
                        size="small"
                      />
                    </Box>
                  </Box>
                  <Box
                    sx={{
                      p: 1.5,
                      bgcolor: 'grey.50',
                      borderRadius: 1,
                      fontFamily: 'monospace',
                      fontSize: '0.75rem',
                      maxHeight: 200,
                      overflow: 'auto',
                      whiteSpace: 'pre-wrap',
                      lineHeight: 1.5,
                      color: prompt.systemPrompt ? 'text.primary' : 'text.secondary',
                      fontStyle: prompt.systemPrompt ? 'normal' : 'italic',
                    }}
                  >
                    {prompt.systemPrompt ||
                      'Prompt body not returned by API. The /api/admin/prompts endpoint currently exposes only name/type/enabled — body field is missing on the backend (see issue #120).'}
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
          {activePrompts.length === 0 && (
            <Grid size={12}>
              <Alert severity="info">
                No active prompts found. The AI service may not be running.
              </Alert>
            </Grid>
          )}
        </Grid>
      </Box>

      {/* Templates Section */}
      <Box
        sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}
      >
        <Typography variant="h6">Prompt Templates</Typography>
        <Button startIcon={<AddIcon />} variant="contained" size="small" onClick={openNew}>
          New Template
        </Button>
      </Box>

      <Grid container spacing={2} sx={{ mb: 4 }}>
        {templates.length === 0 ? (
          <Grid size={12}>
            <Alert severity="info">
              No prompt templates yet. Create one to get started with evaluations.
            </Alert>
          </Grid>
        ) : (
          templates.map((t) => (
            <Grid size={{ xs: 12, md: 6 }} key={t.id}>
              <Card variant="outlined">
                <CardContent>
                  <Box
                    sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}
                  >
                    <Box>
                      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                        {t.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {t.target} · v{t.version} · Updated{' '}
                        {new Date(t.updatedAt).toLocaleDateString()}
                      </Typography>
                      {t.description && (
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                          {t.description}
                        </Typography>
                      )}
                    </Box>
                    <Box>
                      <Tooltip title="Edit">
                        <IconButton size="small" onClick={() => openEdit(t)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton size="small" onClick={() => handleDelete(t.id)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Run Evaluation">
                        <IconButton
                          size="small"
                          color="primary"
                          onClick={() => onRunRequested(t.id)}
                        >
                          <PlayArrowIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </Box>
                  <Typography
                    variant="body2"
                    sx={{
                      mt: 1,
                      p: 1,
                      bgcolor: 'grey.50',
                      borderRadius: 1,
                      fontFamily: 'monospace',
                      fontSize: '0.75rem',
                      maxHeight: 80,
                      overflow: 'hidden',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {t.systemPrompt.substring(0, 200)}
                    {t.systemPrompt.length > 200 ? '...' : ''}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          ))
        )}
      </Grid>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{editing ? 'Edit Template' : 'New Prompt Template'}</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="Name"
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            sx={{ mt: 1, mb: 2 }}
          />
          <TextField
            fullWidth
            label="Description"
            value={formDescription}
            onChange={(e) => setFormDescription(e.target.value)}
            sx={{ mb: 2 }}
          />
          {!editing && (
            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>Target</InputLabel>
              <Select
                value={formTarget}
                label="Target"
                onChange={(e) => setFormTarget(e.target.value)}
              >
                <MenuItem value="risk-scoring">Risk Scoring</MenuItem>
                <MenuItem value="categorization">Categorization</MenuItem>
              </Select>
            </FormControl>
          )}
          <TextField
            fullWidth
            multiline
            rows={12}
            label="System Prompt"
            value={formPrompt}
            onChange={(e) => setFormPrompt(e.target.value)}
            slotProps={{ input: { style: { fontFamily: 'monospace', fontSize: '0.85rem' } } }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSave} disabled={!formName || !formPrompt}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default PromptTemplateEditor;
