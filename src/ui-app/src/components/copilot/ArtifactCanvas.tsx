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
import { answerContent } from './runOutcome';

/**
 * The read-only answer.
 *
 * A read-only objective — the first three prompts of Brian's demo script — now
 * produces an evidence-backed answer and NO approval. Nothing rendered this: the
 * content is an object, so it fell to `ArtifactBody`'s last branch and appeared
 * as a JSON dump on the surface the banker is meant to read.
 *
 * `unverified` is the field that matters most and it renders last on purpose. It
 * is the same move the approval card makes with "Could not be established from
 * the evidence": an answer that states its own limits is worth more than one
 * that reads as complete. An EMPTY `unverified` renders nothing at all — an
 * empty heading would imply the agent checked and found no gaps, which is a
 * different and stronger claim than staying silent.
 */
const AnswerBody: React.FC<{ answer: ReturnType<typeof answerContent> }> = ({ answer }) => {
  if (!answer) return null;
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
        {answer.answer}
      </Typography>

      {answer.keyPoints.length > 0 && (
        <Box>
          <Typography variant="overline" sx={{ color: 'text.secondary' }}>
            Key points
          </Typography>
          <Stack component="ul" spacing={0.5} sx={{ m: 0, pl: 2.5 }}>
            {answer.keyPoints.map((point) => (
              <Typography component="li" variant="body2" key={point}>
                {point}
              </Typography>
            ))}
          </Stack>
        </Box>
      )}

      {answer.unverified.length > 0 && (
        <Box>
          <Typography variant="overline" sx={{ color: 'warning.dark' }}>
            Could not be established from the evidence
          </Typography>
          <Stack component="ul" spacing={0.5} sx={{ m: 0, pl: 2.5 }}>
            {answer.unverified.map((item) => (
              <Typography component="li" variant="body2" key={item}>
                {item}
              </Typography>
            ))}
          </Stack>
        </Box>
      )}

      {answer.citedEvidenceIds.length > 0 && (
        <Box>
          <Typography variant="overline" sx={{ color: 'text.secondary' }}>
            Cited evidence
          </Typography>
          <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
            {answer.citedEvidenceIds.map((id) => (
              <Chip key={id} size="small" variant="outlined" label={id} />
            ))}
          </Stack>
        </Box>
      )}

      {/*
        Said plainly rather than left to be inferred from an absent approval
        dock. A banker who has watched every previous run end in a signature
        needs to know this one is not waiting on them.
      */}
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        This was a read-only question. Nothing was proposed and there is nothing to sign.
      </Typography>
    </Stack>
  );
};

const ArtifactBody: React.FC<{ artifact: Artifact }> = ({ artifact }) => {
  // Shape first, as below: an answer is recognised by carrying a non-empty
  // `answer` string, not by its `kind`.
  const answer = answerContent(artifact);
  if (answer) return <AnswerBody answer={answer} />;

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
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minWidth: 0,
        // Each pane is the only child of a `display: flex` Region, so without
        // `flexGrow` its width is CONTENT-based: it fills the column only while
        // the text inside happens to be wide. The trace pane looked correct for
        // months because its empty-state paragraph is long, then collapsed to 426px
        // inside a 750px region the moment a real run put short step labels in it.
        flexGrow: 1,
      }}
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
          <Typography
            variant="caption"
            sx={{ fontWeight: 700, display: 'block', mb: 0.5, color: 'warning.dark' }}
          >
            Selected approval
          </Typography>
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
