/**
 * The artifact canvas and the approval dock.
 *
 * The canvas is what the work PRODUCED — a memo, a case summary, a table of
 * flagged transactions. The whole premise of "work surface, not chatbot" is that
 * the output is a durable object you can read, not a paragraph that scrolls away.
 *
 * The approval dock is pinned to the bottom of this pane and is NEVER a modal.
 * A modal severs the approval from its evidence at the exact moment the evidence
 * matters most, and modal fatigue is a solved-and-known failure: people learn the
 * position of the confirm button and stop reading. Docked, the trace stays on
 * screen while you decide.
 */

import React, { useState } from 'react';
import { Box, Chip, Paper, Stack, Tab, Tabs, Typography } from '@mui/material';
import ApprovalCard from './ApprovalCard';
import { Approval, Artifact, RunState, StreamStatus } from './types';

const ArtifactBody: React.FC<{ artifact: Artifact }> = ({ artifact }) => {
  // Rendered by the SHAPE of the content, not by a kind whitelist. A
  // `comparison` and an `evidence_bundle` are both row sets; keying the
  // renderer off the kind means a new kind renders as raw JSON in front of
  // someone who is about to sign against it.
  if (Array.isArray(artifact.content) && artifact.content.length > 0) {
    const rows = artifact.content as Record<string, unknown>[];
    const columns = rows.length > 0 ? Object.keys(rows[0]) : [];
    return (
      <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            {columns.map((column) => (
              <Box
                component="th"
                key={column}
                sx={{ textAlign: 'left', borderBottom: 1, borderColor: 'divider', p: 0.5 }}
              >
                {column}
              </Box>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            // eslint-disable-next-line react/no-array-index-key
            <tr key={index}>
              {columns.map((column) => (
                <Box component="td" key={column} sx={{ borderBottom: 1, borderColor: 'divider', p: 0.5 }}>
                  {String(row[column] ?? '')}
                </Box>
              ))}
            </tr>
          ))}
        </tbody>
      </Box>
    );
  }

  if (typeof artifact.content === 'string') {
    return (
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
        {artifact.content}
      </Typography>
    );
  }

  return (
    <Box component="pre" sx={{ fontSize: 12, overflowX: 'auto', m: 0 }}>
      {JSON.stringify(artifact.content, null, 2)}
    </Box>
  );
};

export interface ArtifactCanvasProps {
  run?: RunState;
  approval?: Approval;
  streamStatus: StreamStatus;
  onSigned?: (dwellMs: number, evidenceOpened: boolean) => void;
  onDenied?: (dwellMs: number, evidenceOpened: boolean) => void;
}

const ArtifactCanvas: React.FC<ArtifactCanvasProps> = ({
  run,
  approval,
  streamStatus,
  onSigned,
  onDenied,
}) => {
  const [tab, setTab] = useState(0);
  const artifacts = run ? run.artifactIds.map((id) => run.artifacts[id]).filter(Boolean) : [];
  const active = artifacts[Math.min(tab, artifacts.length - 1)];

  return (
    <Paper
      variant="outlined"
      component="section"
      aria-label="Artifacts and approvals"
      sx={{ display: 'flex', flexDirection: 'column', height: '100%', minWidth: 0 }}
    >
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        {artifacts.length > 0 ? (
          <Tabs
            value={Math.min(tab, artifacts.length - 1)}
            onChange={(_, value) => setTab(value as number)}
            variant="scrollable"
            scrollButtons="auto"
            aria-label="artifacts"
          >
            {artifacts.map((artifact) => (
              <Tab
                key={artifact.id}
                label={
                  <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                    <span>{artifact.title}</span>
                    {artifact.revision > 1 && (
                      <Chip size="small" variant="outlined" label={`v${artifact.revision}`} />
                    )}
                  </Stack>
                }
              />
            ))}
          </Tabs>
        ) : (
          <Box sx={{ p: 1 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
              Artifacts
            </Typography>
          </Box>
        )}
      </Box>

      <Box sx={{ flexGrow: 1, overflowY: 'auto', p: 1.5 }}>
        {active ? (
          <ArtifactBody artifact={active} />
        ) : (
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            Output from the run will appear here — a memo, a case summary, a table you can read and
            keep. Nothing is executed without your signature.
          </Typography>
        )}
      </Box>

      {approval && (
        <Box
          data-testid="approval-dock"
          sx={{
            borderTop: 2,
            borderColor: 'warning.main',
            maxHeight: '60%',
            overflowY: 'auto',
            p: 1,
            bgcolor: 'background.default',
          }}
        >
          <ApprovalCard
            approval={approval}
            streamStatus={streamStatus}
            onSigned={onSigned}
            onDenied={onDenied}
          />
        </Box>
      )}
    </Paper>
  );
};

export default ArtifactCanvas;
