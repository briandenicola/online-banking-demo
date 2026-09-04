/**
 * Placeholder for the Banker Copilot harness (Phase 2, not yet built).
 *
 * This exists so the `bankerCopilot` feature flag has a real route to gate and
 * the flag plumbing can be exercised end to end today. It deliberately does NOT
 * pre-empt the Phase 2 design — the harness layout, trace pane, and approval
 * surface are specified in docs/design/banker-copilot-ui.md and will replace
 * this file wholesale.
 *
 * Being visibly unfinished is the point: a placeholder that looked plausible
 * would be mistaken for progress.
 */
import React from 'react';
import { Alert, AlertTitle, Box, Link, Typography } from '@mui/material';

const BankerCopilotPage: React.FC = () => (
  <Box>
    <Typography variant="h4" gutterBottom>
      Banker Copilot
    </Typography>
    <Typography variant="subtitle1" color="text.secondary" sx={{ mb: 3 }}>
      Agentic harness — task queue, live plan/trace, artifact canvas
    </Typography>

    <Alert severity="info">
      <AlertTitle>Not built yet — Phase 2</AlertTitle>
      The harness surface is designed but not implemented. This route exists so the{' '}
      <code>bankerCopilot</code> feature flag can be exercised now, before the UI lands.
      <br />
      <br />
      Design:{' '}
      <Link
        href="https://github.com/briandenicola/online-banking-demo/blob/main/docs/design/banker-copilot-ui.md"
        target="_blank"
        rel="noopener noreferrer"
      >
        docs/design/banker-copilot-ui.md
      </Link>
      <br />
      Meanwhile, the Classic Admin console remains available at <code>/admin</code>. Both surfaces
      are kept deliberately so the same task can be run on each and compared.
    </Alert>
  </Box>
);

export default BankerCopilotPage;
