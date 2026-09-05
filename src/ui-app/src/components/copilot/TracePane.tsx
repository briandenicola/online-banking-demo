/**
 * The live trace pane.
 *
 * The thing people remember about agent mode is watching the plan CHANGE ITS
 * MIND. Most assistant panels render a spinner and then a wall of text, which
 * throws the narrative away. This renders the narrative:
 *
 *  - future steps are GHOSTED, so the plan's shape is visible before it happens
 *    and a mutation is therefore noticeable
 *  - superseded steps are struck through and kept, never removed — vanishing
 *    steps destroy trust
 *  - a plan-revision marker is stamped inline with the agent's stated reason
 *  - subagents render as nested, independently collapsible sub-trees
 *  - the supervisor agent renders as a SIBLING of the root plan, not a child,
 *    with an explicit caption that it cannot see the primary's recommendation.
 *    Its visual separation is the UI's assertion of independence.
 *
 * ACCESSIBILITY, the subtle part. The tree itself is `aria-live="off"` and fully
 * navigable on demand. A separate visually-hidden region receives COALESCED,
 * throttled, plan-level summaries. A naive `aria-live="polite"` on a streaming
 * trace announces every tool call and every tick, the screen-reader user turns
 * it off, and that is strictly worse than never having offered it.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  Chip,
  Collapse,
  Divider,
  IconButton,
  Paper,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import { NodeStatusGlyph, visuallyHidden } from './CopilotPrimitives';
import { useCopilot, useNow } from './CopilotContext';
import { PlanStep, RunState, SubagentRun, ToolCall, TraceDensity } from './types';
import { getCopilotConfig } from '../../config/copilotConfig';

// ---------------------------------------------------------------------------

function durationChip(durationMs?: number): string {
  if (typeof durationMs !== 'number') return '';
  return durationMs >= 1000 ? `${(durationMs / 1000).toFixed(2)}s` : `${durationMs}ms`;
}

const ToolCallNode: React.FC<{ tool: ToolCall; density: TraceDensity; highlighted: boolean; ownerLabel?: string }> = ({
  tool,
  density,
  highlighted,
  ownerLabel,
}) => (
  <Stack
    direction="row"
    spacing={1}
    id={`trace-node-${tool.id}`}
    sx={{
      alignItems: 'baseline',
      pl: 3,
      py: 0.25,
      borderRadius: 1,
      bgcolor: highlighted ? 'warning.light' : 'transparent',
      transition: 'background-color 600ms',
    }}
  >
    <NodeStatusGlyph status={tool.status} />
    <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
      🔧 {tool.name}
    </Typography>
    {ownerLabel && (
      // Attribution for a tool call that belongs to a subagent but is listed at
      // the plan-step level. Without it, a fan-out's calls would read as the root
      // plan's own, which is the interleaving-noise failure this pane must avoid.
      <Chip size="small" variant="outlined" color="secondary" label={`⑂ ${ownerLabel}`} />
    )}
    {tool.attempt > 1 && <Chip size="small" color="warning" variant="outlined" label={`↻ ${tool.attempt}`} />}
    {tool.resultSummary && density !== 'summary' && (
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        {tool.resultSummary}
      </Typography>
    )}
    {tool.error && (
      <Typography variant="caption" sx={{ color: 'error.main' }}>
        {tool.error}
      </Typography>
    )}
    <Box sx={{ flexGrow: 1 }} />
    <Typography variant="caption" aria-hidden="true" sx={{ color: 'text.secondary' }}>
      {durationChip(tool.durationMs)}
    </Typography>
    {density === 'raw' && tool.args && (
      <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
        {/* Redaction is server-side. This masks account/SSN shapes as
            defence-in-depth only — a client-side mask cannot un-write a value
            already persisted to the trace store. */}
        {redact(JSON.stringify(tool.args))}
      </Typography>
    )}
  </Stack>
);

/** Defence-in-depth masking, matching the `····8891` convention in the tx tabs. */
export function redact(text: string): string {
  return text
    .replace(/\b\d{3}-?\d{2}-?\d{4}\b/g, '···-··-····')
    .replace(/\b\d{8,}\b/g, (m) => `····${m.slice(-4)}`);
}

// ---------------------------------------------------------------------------

const SubagentNode: React.FC<{
  subagent: SubagentRun;
  run: RunState;
  density: TraceDensity;
  depth: number;
}> = ({ subagent, run, density, depth }) => {
  const config = getCopilotConfig();
  const [open, setOpen] = useState(true);
  const { highlightedNodeId } = useCopilot();
  const isSupervisor = subagent.role === 'supervisor';

  const children = subagent.childIds.map((id) => run.subagents[id]).filter(Boolean);
  const tools = subagent.toolCallIds.map((id) => run.toolCalls[id]).filter(Boolean);
  const overDepth = depth > config.maxTraceDepth;

  return (
    <Box
      sx={{
        pl: 2,
        borderLeft: 2,
        borderColor: isSupervisor ? 'secondary.main' : 'divider',
        ml: 1,
      }}
    >
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <IconButton size="small" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-label="toggle subagent">
          {open ? <ExpandMoreIcon fontSize="inherit" /> : <ChevronRightIcon fontSize="inherit" />}
        </IconButton>
        <NodeStatusGlyph status={subagent.status} />
        <Typography variant="body2" sx={{ fontWeight: isSupervisor ? 700 : 500 }}>
          {isSupervisor ? '⑂ SUPERVISOR AGENT' : subagent.name}
        </Typography>
        {typeof subagent.confidence === 'number' && (
          <Chip size="small" variant="outlined" label={`conf ${subagent.confidence.toFixed(2)}`} />
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="caption" aria-hidden="true" sx={{ color: 'text.secondary' }}>
          {durationChip(subagent.durationMs)}
        </Typography>
      </Stack>

      {isSupervisor && (
        <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', pl: 5 }}>
          ▸ does NOT see the primary agent&apos;s recommendation
        </Typography>
      )}

      {subagent.verdictSummary && (
        <Typography variant="caption" sx={{ display: 'block', pl: 5, color: 'text.secondary' }}>
          “{subagent.verdictSummary}”
        </Typography>
      )}

      <Collapse in={open}>
        {overDepth ? (
          // Nobody parses a six-deep tree live. Past the cap it flattens behind
          // a disclosure rather than indenting into the margin.
          <Typography variant="caption" sx={{ pl: 5, color: 'text.secondary' }}>
            ↳ depth {depth}+ · {tools.length} tool call(s), {children.length} nested agent(s)
          </Typography>
        ) : (
          <>
            {density !== 'summary' &&
              tools.map((tool) => (
                <ToolCallNode
                  key={tool.id}
                  tool={tool}
                  density={density}
                  highlighted={highlightedNodeId === tool.id}
                />
              ))}
            {children.map((child) => (
              <SubagentNode key={child.id} subagent={child} run={run} density={density} depth={depth + 1} />
            ))}
          </>
        )}
      </Collapse>
    </Box>
  );
};

// ---------------------------------------------------------------------------

const PlanStepNode: React.FC<{ step: PlanStep; run: RunState; density: TraceDensity }> = ({
  step,
  run,
  density,
}) => {
  const [open, setOpen] = useState(true);
  const { highlightedNodeId } = useCopilot();
  const tools = step.toolCallIds.map((id) => run.toolCalls[id]).filter(Boolean);
  const subagents = step.subagentIds.map((id) => run.subagents[id]).filter(Boolean);
  const ghosted = step.status === 'pending';

  return (
    <Box
      role="treeitem"
      aria-expanded={open}
      aria-level={1}
      sx={{
        opacity: ghosted ? 0.4 : 1,
        borderLeft: step.status === 'complete' ? 2 : 0,
        borderColor: 'success.light',
        pl: step.status === 'complete' ? 1 : 0,
        mb: 0.5,
      }}
    >
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        {(tools.length > 0 || subagents.length > 0) && (
          <IconButton size="small" onClick={() => setOpen((v) => !v)} aria-label="toggle step">
            {open ? <ExpandMoreIcon fontSize="inherit" /> : <ChevronRightIcon fontSize="inherit" />}
          </IconButton>
        )}
        <NodeStatusGlyph status={step.status} />
        <Typography
          variant="body2"
          sx={{
            fontWeight: step.status === 'running' ? 700 : 400,
            textDecoration: step.status === 'skipped' ? 'line-through' : 'none',
          }}
        >
          {step.index + 1}. {step.title}
        </Typography>
        {subagents.length > 0 && (
          <Chip size="small" variant="outlined" label={`⑂ ${subagents.length} subagents`} />
        )}
        {density === 'summary' && tools.length > 0 && (
          <Chip size="small" variant="outlined" label={`${tools.length} tools`} />
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="caption" aria-hidden="true" sx={{ color: 'text.secondary' }}>
          {durationChip(step.durationMs)}
        </Typography>
      </Stack>

      {step.supersededReason && (
        <Typography variant="caption" sx={{ pl: 5, color: 'text.secondary' }}>
          ⊘ superseded — {step.supersededReason}
        </Typography>
      )}
      {step.error && (
        <Typography variant="caption" sx={{ pl: 5, color: 'error.main' }}>
          {step.error}
        </Typography>
      )}

      <Collapse in={open}>
        {density !== 'summary' &&
          tools.map((tool) => (
            <ToolCallNode
              key={tool.id}
              tool={tool}
              density={density}
              highlighted={highlightedNodeId === tool.id}
              ownerLabel={tool.subagentId ? run.subagents[tool.subagentId]?.name : undefined}
            />
          ))}
        {subagents.length >= 2 && (
          // A fan-out. The header names it as parallel work and states the
          // reading rule, because the risk of concurrency is interleaved noise
          // where you cannot tell which agent produced which step. Each child
          // renders as its own bordered sub-tree below, so tool calls stay
          // grouped UNDER their owning agent and never intermix.
          <Typography variant="caption" sx={{ pl: 5, color: 'secondary.main', fontWeight: 600, display: 'block' }}>
            ⑂ {subagents.length} agents in parallel — each agent&apos;s steps are grouped under it,
            not interleaved
          </Typography>
        )}
        {subagents.map((subagent) => (
          <SubagentNode key={subagent.id} subagent={subagent} run={run} density={density} depth={1} />
        ))}
      </Collapse>
    </Box>
  );
};

// ---------------------------------------------------------------------------

const PlanRevisionMarker: React.FC<{ version: number; reason: string }> = ({ version, reason }) => (
  <Divider sx={{ my: 1 }}>
    <Typography variant="caption" sx={{ color: 'warning.main', fontWeight: 600 }}>
      plan revised · v{version} · “{reason}”
    </Typography>
  </Divider>
);

// ---------------------------------------------------------------------------

/**
 * Coalesced screen-reader announcements.
 *
 * One sentence per window, plan-level only, never a timer tick. Assertive is
 * reserved for exactly three things elsewhere in this surface: an approval
 * becoming required, an approval reaching a terminal state, and an agent
 * disagreement. Nothing else earns an interruption.
 */
const TraceLiveRegion: React.FC<{ run?: RunState }> = ({ run }) => {
  const config = getCopilotConfig();
  const [message, setMessage] = useState('');
  const pendingRef = useRef<string[]>([]);

  const signature = run
    ? `${run.status}|${run.stepIds.map((id) => run.steps[id]?.status).join(',')}`
    : '';

  useEffect(() => {
    if (!run) return;
    const running = run.stepIds.map((id) => run.steps[id]).find((s) => s && s.status === 'running');
    const completed = run.stepIds.map((id) => run.steps[id]).filter((s) => s && s.status === 'complete').length;
    if (running) {
      pendingRef.current.push(
        `Step ${running.index + 1} of ${run.stepIds.length}, ${running.title}, running.`
      );
    } else if (run.status === 'completed') {
      pendingRef.current.push(
        `Run complete. ${completed} steps. ${run.approvalIds.length} signature(s) required.`
      );
    }
  }, [run, signature]);

  useEffect(() => {
    const id = setInterval(() => {
      const batch = pendingRef.current;
      pendingRef.current = [];
      if (batch.length > 0) setMessage(batch[batch.length - 1]);
    }, config.ariaCoalesceMs);
    return () => clearInterval(id);
  }, [config.ariaCoalesceMs]);

  return (
    <Box aria-live="polite" aria-atomic="true" sx={visuallyHidden}>
      {message}
    </Box>
  );
};

// ---------------------------------------------------------------------------

export interface TracePaneProps {
  run?: RunState;
}

const TracePane: React.FC<TracePaneProps> = ({ run }) => {
  const { density, setDensity, streamStatus, incomplete } = useCopilot();
  const now = useNow();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [followTail, setFollowTail] = useState(true);
  const [missedCount, setMissedCount] = useState(0);
  const lastStepCount = useRef(0);

  const steps = useMemo(
    () => (run ? run.stepIds.map((id) => run.steps[id]).filter(Boolean) : []),
    [run]
  );

  useEffect(() => {
    if (!scrollRef.current) return;
    const grew = steps.length > lastStepCount.current;
    lastStepCount.current = steps.length;
    if (!grew) return;

    if (followTail) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    } else {
      // A banker reading step 2 while the agent writes step 9 must not be yanked
      // away. Same bug class as Chat.tsx's unconditional scrollIntoView —
      // deliberately not repeated.
      setMissedCount((c) => c + 1);
    }
  }, [steps.length, followTail]);

  const elapsed = run?.startedAt ? Math.max(0, now - new Date(run.startedAt).getTime()) : 0;

  return (
    <Paper
      variant="outlined"
      component="section"
      aria-label="Plan and trace"
      sx={{ display: 'flex', flexDirection: 'column', height: '100%', minWidth: 0 }}
    >
      <Box sx={{ p: 1, borderBottom: 1, borderColor: 'divider' }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            {run ? run.title : 'No run selected'}
          </Typography>
          {run && (
            <Chip
              size="small"
              variant="outlined"
              color={run.status === 'failed' ? 'error' : run.status === 'running' ? 'primary' : 'default'}
              label={run.status}
            />
          )}
          <Box sx={{ flexGrow: 1 }} />
          <ToggleButtonGroup
            size="small"
            exclusive
            value={density}
            onChange={(_, value) => value && setDensity(value as TraceDensity)}
            aria-label="trace density"
          >
            <ToggleButton value="summary">Summary</ToggleButton>
            <ToggleButton value="detailed">Detailed</ToggleButton>
            <ToggleButton value="raw">Raw</ToggleButton>
          </ToggleButtonGroup>
        </Stack>
        {run && (
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            {steps.length} steps · {Math.floor(elapsed / 1000)}s
            {run.revisions.length > 0 ? ` · plan v${run.planVersion}` : ''}
          </Typography>
        )}
      </Box>

      {incomplete && (
        <Box sx={{ p: 1, bgcolor: 'warning.main', color: 'warning.contrastText' }}>
          <Typography variant="caption">
            Some trace frames were lost. This trace is INCOMPLETE and is not being presented as a
            full record.
          </Typography>
        </Box>
      )}

      {streamStatus !== 'live' && streamStatus !== 'resumed' && streamStatus !== 'idle' && (
        <Box sx={{ p: 1, bgcolor: 'action.hover' }}>
          <Typography variant="caption">
            {streamStatus === 'failed'
              ? 'Live updates unavailable. The run continues on the server.'
              : 'Reconnecting — the agent is still running on the server.'}
          </Typography>
        </Box>
      )}

      <Box
        ref={scrollRef}
        role="tree"
        aria-label="Agent plan trace"
        aria-live="off"
        aria-busy={run?.status === 'running'}
        onScroll={(e) => {
          const el = e.currentTarget;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          setFollowTail(atBottom);
          if (atBottom) setMissedCount(0);
        }}
        sx={{ flexGrow: 1, overflowY: 'auto', p: 1, minHeight: 200 }}
      >
        {!run && (
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            Describe what you need in the command bar below. The plan, every tool call, and every
            proposed action will appear here as they happen.
          </Typography>
        )}

        {steps.map((step, index) => {
          const revision = run?.revisions.find((r) => r.addedStepIds.includes(step.id));
          const showMarker =
            revision && (index === 0 || !run?.revisions.find((r) => r.addedStepIds.includes(steps[index - 1].id)));
          return (
            <React.Fragment key={step.id}>
              {showMarker && revision && (
                <PlanRevisionMarker version={revision.version} reason={revision.reason} />
              )}
              <PlanStepNode step={step} run={run as RunState} density={density} />
            </React.Fragment>
          );
        })}

        {run && run.rootSubagentIds.length > 0 && (
          <Box sx={{ mt: 2 }}>
            <Divider sx={{ mb: 1 }} />
            {run.rootSubagentIds.map((id) => (
              <SubagentNode key={id} subagent={run.subagents[id]} run={run} density={density} depth={1} />
            ))}
          </Box>
        )}
      </Box>

      {missedCount > 0 && (
        <Box sx={{ p: 0.5, textAlign: 'center', bgcolor: 'action.hover' }}>
          <Typography
            variant="caption"
            component="button"
            onClick={() => {
              setFollowTail(true);
              setMissedCount(0);
              if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
            }}
            sx={{ border: 0, background: 'none', cursor: 'pointer', color: 'primary.main' }}
          >
            ↓ {missedCount} new step(s)
          </Typography>
        </Box>
      )}

      <TraceLiveRegion run={run} />
    </Paper>
  );
};

export default TracePane;
