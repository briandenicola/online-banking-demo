/**
 * The Banker Copilot route.
 *
 * Three things happen here and nowhere else:
 *
 *  1. The provider is mounted, so the store and the SSE connection live for
 *     exactly as long as the route does.
 *  2. The surface is wrapped in the shared measurement bar — the SAME component
 *     that wraps Classic Admin, so the two are counted by identical rules.
 *  3. Demo mode. When the harness service is unreachable, this replays a
 *     recorded envelope array through the real reducer rather than rendering
 *     mock components. A demo that runs on a different code path from the
 *     product is a demo of something that does not exist.
 *
 * The feature flag that gates this route is a PRESENTATION toggle. Every
 * authority decision on this surface is made by authority-service, which has
 * never heard of the flag. Turning the flag on cannot grant anyone the ability
 * to approve anything.
 */

import React, { useEffect, useState } from 'react';
import { Alert, Box, Button, Stack, Typography } from '@mui/material';
import { CopilotProvider, useCopilot } from '../components/copilot/CopilotContext';
import CopilotHarness from '../components/copilot/CopilotHarness';
import TaskMeasurementBar from '../components/comparison/TaskMeasurementBar';
import { demoEvents } from '../components/copilot/demoFixture';
import { getCopilotConfig } from '../config/copilotConfig';
import { useFullBleedSurface } from '../components/AppShell';

const DemoModeBanner: React.FC = () => {
  const { replay, streamStatus } = useCopilot();
  const config = getCopilotConfig();
  const [played, setPlayed] = useState(false);

  useEffect(() => {
    if (config.demoAutoplay && !played) {
      replay(demoEvents);
      setPlayed(true);
    }
  }, [config.demoAutoplay, played, replay]);

  if (!config.demoModeEnabled) return null;

  return (
    <Alert severity="info" sx={{ borderRadius: 0, py: 0 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography variant="caption">
          Demo mode available. The recording replays through the same reducer the live stream uses —
          nothing here is a mock component.
        </Typography>
        <Button
          size="small"
          onClick={() => {
            replay(demoEvents);
            setPlayed(true);
          }}
          disabled={streamStatus === 'live'}
        >
          Replay recorded run
        </Button>
      </Stack>
    </Alert>
  );
};

const BankerCopilotPage: React.FC = () => {
  // The three-pane surface manages its own scrolling and needs the viewport.
  useFullBleedSurface();

  return (
    <CopilotProvider>
      <TaskMeasurementBar surface="copilot">
        <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <DemoModeBanner />
          <CopilotHarness />
        </Box>
      </TaskMeasurementBar>
    </CopilotProvider>
  );
};

export default BankerCopilotPage;
