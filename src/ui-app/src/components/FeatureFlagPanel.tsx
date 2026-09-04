/**
 * The mid-demo flag switcher.
 *
 * Opens from the user menu. Flipping a switch here writes a per-browser
 * localStorage override and re-renders immediately — no rebuild, no redeploy,
 * no page reload. That is the requirement that drove the whole layered config
 * design: being able to switch surfaces live, in front of an audience, is most
 * of the value of having the flag at all.
 *
 * The panel shows each flag's PROVENANCE (which layer supplied the value)
 * because "why is this on?" is otherwise unanswerable across five layers, and
 * an unanswerable config question during a live demo is a bad minute.
 *
 * It also renders each flag's scheduled default change, so the decision that is
 * most likely to be forgotten stays in front of whoever opens this panel.
 */
import React from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  Stack,
  Switch,
  Tooltip,
  Typography,
} from '@mui/material';
import { FLAG_DEFINITIONS, FLAG_NAMES, FlagSource } from '../config/featureFlags';
import { useFeatureFlags } from '../contexts/FeatureFlagContext';

interface FeatureFlagPanelProps {
  open: boolean;
  onClose: () => void;
}

const SOURCE_LABEL: Record<FlagSource, string> = {
  url: 'from URL (this tab only)',
  localStorage: 'overridden in this browser',
  runtimeConfig: 'deployment default',
  buildEnv: 'build-time default',
  default: 'built-in default',
};

const FeatureFlagPanel: React.FC<FeatureFlagPanelProps> = ({ open, onClose }) => {
  const { flags, resolved, setFlag, resetFlags } = useFeatureFlags();

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Surfaces &amp; feature flags</DialogTitle>
      <DialogContent dividers>
        <Alert severity="info" sx={{ mb: 2 }}>
          These are display settings, not permissions. Hiding a surface changes what this browser
          shows you — it does not change what you are allowed to do, and it does not secure
          anything.
        </Alert>

        <Stack spacing={2}>
          {FLAG_NAMES.map((name) => {
            const definition = FLAG_DEFINITIONS[name];
            const source = resolved[name].source;
            return (
              <Box key={name}>
                <FormControlLabel
                  control={
                    <Switch
                      checked={flags[name]}
                      onChange={(e) => setFlag(name, e.target.checked)}
                      slotProps={{ input: { 'aria-label': definition.label } }}
                    />
                  }
                  label={
                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                      <Typography variant="subtitle2">{definition.label}</Typography>
                      <Tooltip title={`Resolved ${SOURCE_LABEL[source]}`}>
                        <Chip size="small" variant="outlined" label={SOURCE_LABEL[source]} />
                      </Tooltip>
                    </Stack>
                  }
                />
                <Typography variant="body2" color="text.secondary" sx={{ ml: 6 }}>
                  {definition.description}
                </Typography>
                {definition.plannedDefaultChange && (
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ ml: 6, display: 'block', mt: 0.5, fontStyle: 'italic' }}
                  >
                    Planned default: {String(definition.plannedDefaultChange.to)} —{' '}
                    {definition.plannedDefaultChange.when}
                  </Typography>
                )}
                <Divider sx={{ mt: 1.5 }} />
              </Box>
            );
          })}
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
          Tip: append <code>?ff=bankerCopilot:on,classicAdminTabs:off</code> to any URL to preset
          surfaces for one tab without changing this browser&apos;s saved settings.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={resetFlags}>Reset to deployment defaults</Button>
        <Button variant="contained" onClick={onClose}>
          Done
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default FeatureFlagPanel;
