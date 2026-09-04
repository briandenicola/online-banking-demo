/**
 * Copilot harness context — store instance, stream lifecycle, one shared ticker.
 *
 * Follows the provider convention already in `contexts/` (AuthContext,
 * AccountContext): typed context, a `useX` hook that throws outside the
 * provider. What is different is that state does NOT live in `useState` — see
 * `state/copilotStore.ts` for why. React subscribes to the external store via
 * `useSyncExternalStore`, and every hook below returns a NARROW slice so a tool
 * call completing in step 3 cannot re-render the approval dock.
 *
 * The ticker deserves its own note. Twenty queue rows with twenty independent
 * `setInterval`s is a classic own-goal, and worse here than usual: countdowns
 * that drift apart make expiry look arbitrary. One 1s interval broadcasts "now"
 * to every countdown and elapsed timer.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';
import {
  Approval,
  CopilotEvent,
  RunState,
  StreamStatus,
  TraceDensity,
} from './types';
import { CopilotState, createCopilotStore, CopilotStore } from '../../state/copilotStore';
import { openCopilotStream, CopilotStreamHandle } from '../../api/copilotStream';
import { createSession, sendMessage, startRun, fetchRunTrace } from '../../api/copilot';
import { listApprovals, signApproval, denyApproval } from '../../api/approvals';
import { logger } from '../../utils/logger';

export interface CopilotContextValue {
  store: CopilotStore;
  streamStatus: StreamStatus;
  incomplete: boolean;
  sessionId?: string;
  activeRunId?: string;
  density: TraceDensity;
  setDensity: (density: TraceDensity) => void;
  showTimings: boolean;
  setShowTimings: (value: boolean) => void;
  selectedApprovalId?: string;
  selectApproval: (id?: string) => void;
  highlightedNodeId?: string;
  highlightNode: (id?: string) => void;
  /** Submit an intent. Opens a session if one is not already open. */
  submitIntent: (intent: string) => Promise<void>;
  /** Refresh the approval queue from authority-service. */
  refreshApprovals: () => Promise<void>;
  sign: (approvalId: string, expectedPayloadHash: string, comment?: string) => Promise<Approval>;
  deny: (approvalId: string, reason: string) => Promise<Approval>;
  /** Replay a recorded envelope array — deterministic demo mode and tests. */
  replay: (events: CopilotEvent[]) => void;
  lastError?: string;
}

const CopilotContext = createContext<CopilotContextValue | undefined>(undefined);

export const useCopilot = (): CopilotContextValue => {
  const context = useContext(CopilotContext);
  if (!context) throw new Error('useCopilot must be used within CopilotProvider');
  return context;
};

// ---------------------------------------------------------------------------
// Shared ticker
// ---------------------------------------------------------------------------

const TickContext = createContext<number>(0);

/** "Now", broadcast once per second to every countdown on the surface. */
export const useNow = (): number => useContext(TickContext);

const TickProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return <TickContext.Provider value={now}>{children}</TickContext.Provider>;
};

// ---------------------------------------------------------------------------
// Narrow-slice hooks
// ---------------------------------------------------------------------------

function useStoreSelector<T>(select: (state: CopilotState) => T): T {
  const { store } = useCopilot();
  return useSyncExternalStore(
    store.subscribe,
    () => select(store.getSnapshot()),
    () => select(store.getSnapshot())
  );
}

export function useCopilotState(): CopilotState {
  return useStoreSelector((s) => s);
}

export function useRun(runId?: string): RunState | undefined {
  return useStoreSelector((s) => (runId ? s.runs[runId] : undefined));
}

export function useApproval(approvalId?: string): Approval | undefined {
  return useStoreSelector((s) => (approvalId ? s.approvals[approvalId] : undefined));
}

export function useApprovals(): Approval[] {
  const map = useStoreSelector((s) => s.approvals);
  const ids = useStoreSelector((s) => s.approvalIds);
  return useMemo(() => ids.map((id) => map[id]).filter(Boolean), [ids, map]);
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export interface CopilotProviderProps {
  children: React.ReactNode;
  /** Test/demo seam: pre-seeded store. */
  store?: CopilotStore;
  /** Skip network calls entirely (fixture player / tests). */
  offline?: boolean;
}

export const CopilotProvider: React.FC<CopilotProviderProps> = ({
  children,
  store: injectedStore,
  offline = false,
}) => {
  const storeRef = useRef<CopilotStore>(injectedStore || createCopilotStore());
  const store = storeRef.current;
  const handleRef = useRef<CopilotStreamHandle | null>(null);

  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [density, setDensity] = useState<TraceDensity>('detailed');
  const [showTimings, setShowTimings] = useState(false);
  const [selectedApprovalId, setSelectedApprovalId] = useState<string | undefined>(undefined);
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | undefined>(undefined);
  const [lastError, setLastError] = useState<string | undefined>(undefined);

  const streamStatus = useSyncExternalStore(
    store.subscribe,
    () => store.getSnapshot().stream.status,
    () => store.getSnapshot().stream.status
  );
  const incomplete = useSyncExternalStore(
    store.subscribe,
    () => store.getSnapshot().stream.incomplete,
    () => store.getSnapshot().stream.incomplete
  );
  const activeRunId = useSyncExternalStore(
    store.subscribe,
    () => store.getSnapshot().activeRunId,
    () => store.getSnapshot().activeRunId
  );

  useEffect(
    () => () => {
      if (handleRef.current) handleRef.current.close();
    },
    []
  );

  const resync = useCallback(
    async (targetRunId: string) => {
      // A gap we could not close means the trace has holes. Rebuilding from the
      // persisted envelopes through the SAME reducer is the only recovery that
      // cannot produce a state the live path could not have produced.
      //
      // Keyed by RUN, not by session: seq is run-scoped, so resyncing a session
      // would mean rebuilding one run's trace from another run's frames.
      store.setDraining(true);
      try {
        const trace = await fetchRunTrace(targetRunId);
        store.reset();
        trace.events.forEach((event) => store.dispatchSync(event));
        // The server tells us whether it managed to persist every frame. If it
        // did not, the trace stays flagged incomplete even though the resync
        // "succeeded" — a recovered trace with holes is still a trace with
        // holes, and hiding that is the one thing this surface must not do.
        store.setIncomplete(trace.degraded);
      } catch (error) {
        logger.error('copilot: trace resync failed', error);
        store.setIncomplete(true);
      } finally {
        store.setDraining(false);
      }
    },
    [store]
  );

  const openStream = useCallback(
    (id: string) => {
      if (offline) return;
      if (handleRef.current) handleRef.current.close();
      handleRef.current = openCopilotStream({
        sessionId: id,
        onEvent: (event) => store.dispatch(event),
        onStatusChange: (status) => store.setStreamStatus(status),
        onResyncRequired: (_fromSeq: number, gappedRunId?: string) => {
          store.setIncomplete(true);
          const target = gappedRunId || store.getSnapshot().activeRunId;
          if (target) resync(target);
        },
      });
    },
    [offline, resync, store]
  );

  const submitIntent = useCallback(
    async (intent: string) => {
      setLastError(undefined);
      try {
        // Open a session if there isn't one, then always start a RUN. Creating
        // a session does not execute anything — a session is a container, and
        // the planner only moves when a run is started inside it.
        let id = sessionId;
        if (!id) {
          const session = await createSession({ objective: intent });
          id = session.sessionId;
          setSessionId(id);
          openStream(id);
        } else {
          await sendMessage(id, intent);
        }
        await startRun(id, { objective: intent });
      } catch (error) {
        logger.error('copilot: intent submission failed', error);
        setLastError('The harness did not accept that request. It is not running on the server.');
      }
    },
    [openStream, sessionId]
  );

  const refreshApprovals = useCallback(async () => {
    if (offline) return;
    try {
      // Two scopes, deliberately. `awaiting-me` is the co-sign queue and the
      // server excludes the caller's own requests from it — a supervisor never
      // sees a request they could not sign, because showing it invites the try.
      const [mine, awaiting] = await Promise.all([
        listApprovals({ scope: 'mine' }),
        listApprovals({ scope: 'awaiting-me' }),
      ]);
      [...mine, ...awaiting].forEach((approval) => store.putApproval(approval));
    } catch (error) {
      logger.warn('copilot: approval refresh failed', error);
    }
  }, [offline, store]);

  const sign = useCallback(
    async (approvalId: string, expectedPayloadHash: string, comment?: string) => {
      const updated = await signApproval(approvalId, { expectedPayloadHash, comment });
      store.putApproval(updated);
      return updated;
    },
    [store]
  );

  const deny = useCallback(
    async (approvalId: string, reason: string) => {
      const updated = await denyApproval(approvalId, reason);
      store.putApproval(updated);
      return updated;
    },
    [store]
  );

  const replay = useCallback(
    (events: CopilotEvent[]) => {
      // Animations are suppressed during a drain: replaying 200 frames with the
      // one-shot highlight flashes enabled produces a flash cascade nobody can
      // read and some people cannot safely look at.
      store.setDraining(true);
      events.forEach((event) => store.dispatchSync(event));
      store.setDraining(false);
    },
    [store]
  );

  const value = useMemo<CopilotContextValue>(
    () => ({
      store,
      streamStatus,
      incomplete,
      sessionId,
      activeRunId,
      density,
      setDensity,
      showTimings,
      setShowTimings,
      selectedApprovalId,
      selectApproval: setSelectedApprovalId,
      highlightedNodeId,
      highlightNode: setHighlightedNodeId,
      submitIntent,
      refreshApprovals,
      sign,
      deny,
      replay,
      lastError,
    }),
    [
      store,
      streamStatus,
      incomplete,
      sessionId,
      activeRunId,
      density,
      showTimings,
      selectedApprovalId,
      highlightedNodeId,
      submitIntent,
      refreshApprovals,
      sign,
      deny,
      replay,
      lastError,
    ]
  );

  return (
    <CopilotContext.Provider value={value}>
      <TickProvider>{children}</TickProvider>
    </CopilotContext.Provider>
  );
};

export default CopilotProvider;
