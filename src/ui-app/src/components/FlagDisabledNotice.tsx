/**
 * Shown when a surface flag is off and its route is requested directly.
 *
 * Tone is deliberate. This is NOT an authorisation failure and must not look
 * like one — it names the flag, explains that the surface is hidden by a
 * presentation setting, and offers a button that turns it back on. An
 * authorisation failure would never offer you a button that fixes it, and that
 * difference is the whole point: nobody should come away from this screen
 * believing the flag protected anything.
 *
 * See src/config/featureFlags.ts for the full "not a security control"
 * statement and the route guarantee this implements.
 */
import React from 'react';
import { Box, Button, Card, CardContent, Chip, Stack, Typography } from '@mui/material';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import { useNavigate } from 'react-router-dom';
import { FLAG_DEFINITIONS, FeatureFlagName } from '../config/featureFlags';
import { useFeatureFlags } from '../contexts/FeatureFlagContext';

interface FlagDisabledNoticeProps {
  flag: FeatureFlagName;
}

const FlagDisabledNotice: React.FC<FlagDisabledNoticeProps> = ({ flag }) => {
  const { setFlag } = useFeatureFlags();
  const navigate = useNavigate();
  const definition = FLAG_DEFINITIONS[flag];

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
      <Card variant="outlined" sx={{ maxWidth: 620 }}>
        <CardContent>
          <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', mb: 2 }}>
            <VisibilityOffIcon color="disabled" />
            <Typography variant="h6">This surface is currently hidden</Typography>
          </Stack>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {definition.description}
          </Typography>

          <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Hidden by the feature flag
            </Typography>
            <Chip size="small" label={definition.name} sx={{ fontFamily: 'monospace' }} />
          </Stack>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            This is a display setting, not a permission check. It controls which surfaces are
            shown while we compare the Classic Admin console against the Banker Copilot harness.
            Your access is unchanged either way.
          </Typography>

          <Stack direction="row" spacing={1}>
            <Button variant="contained" onClick={() => setFlag(flag, true)}>
              Show {definition.label}
            </Button>
            <Button variant="outlined" onClick={() => navigate('/')}>
              Back to Dashboard
            </Button>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
};

export default FlagDisabledNotice;
