/**
 * Banker Copilot runtime configuration.
 *
 * Standing rule from Brian: no hardcoded IPs, CIDRs, thresholds, or dollar
 * amounts — configuration only. This module is where every Copilot tunable
 * lives, so a component never carries a magic number and an operator never has
 * to rebuild the bundle to change one.
 *
 * Resolution mirrors `config/featureFlags.ts` deliberately — same layering, same
 * precedence, same file. Inventing a second config mechanism for one surface
 * would be exactly the kind of duplication this epic keeps paying for:
 *
 *   1. `window.__RUNTIME_CONFIG__.copilot`   — deployment default, mounted file
 *   2. `REACT_APP_COPILOT_*`                 — build-time env (static access; CRA
 *                                              inlines these textually, so a
 *                                              computed lookup silently yields
 *                                              undefined in a production build)
 *   3. the defaults below
 *
 * NOTE ON THE ANTI-FATIGUE VALUES. The dwell table and the signature-rate
 * thresholds are configurable, but they are configurable WITHIN BOUNDS: every
 * accessor clamps to a floor. An operator who sets every dwell to zero has
 * turned the friction off, and friction proportional to stakes is the only
 * anti-fatigue mechanism in §6 that actually scales cost with consequence. A
 * config knob that can empty a control is not a knob, it is a bypass — so the
 * floors are enforced here rather than trusted to a deployment.
 */

import { logger } from '../utils/logger';

export interface CopilotEndpoints {
  /** Harness base path. Rusty's gateway routes this with `proxy_buffering off`. */
  copilotBase: string;
  /** Approval store base path. A DIFFERENT service, deliberately — §0.1. */
  authorityBase: string;
  sessions: string;
  /** `{sessionId}` is substituted. */
  sessionStream: string;
  sessionMessages: string;
  /** A run is not a session: seq is run-scoped and each run has its own trace. */
  sessionRuns: string;
  runTrace: string;
  approvals: string;
}

/**
 * Minimum time the material payload fields must have been visible before `Sign`
 * enables, in milliseconds, keyed by stakes.
 *
 * This is the mechanism worth defending hardest (§6.1): it is the only one that
 * scales cost with consequence, and uniform friction is how you get either
 * rubber-stamping or a shadow process.
 */
export interface DwellPolicyMs {
  l1Reversible: number;
  l1Irreversible: number;
  l2Agree: number;
  l2Disagree: number;
  /** Applies to a re-proposed payload: you get no credit for reading the old one. */
  resupersededMultiplier: number;
}

export interface CopilotConfig {
  endpoints: CopilotEndpoints;
  dwellMs: DwellPolicyMs;
  /** Soft threshold for the session approval meter, and the window it counts over. */
  sessionSignatureSoftLimit: number;
  sessionSignatureWindowMs: number;
  /** Share of sub-threshold L1 items that demand a transcribed fact (0..1). */
  spotCheckRate: number;
  /** Never show more than this many approval cards in "Needs you" at once. */
  queueVisibleLimit: number;
  /** Visual tree depth cap; deeper subagents flatten behind a disclosure. */
  maxTraceDepth: number;
  /** Above this many visible nodes, switch to windowed rendering. */
  virtualiseAboveNodes: number;
  /** SSE heartbeat expectation and reconnection backoff. */
  heartbeatIntervalMs: number;
  missedHeartbeatsBeforeDegraded: number;
  reconnectBaseMs: number;
  reconnectMaxMs: number;
  /** How long a detected seq gap may stay open before a full snapshot resync. */
  gapResyncTimeoutMs: number;
  /** Cap on out-of-order frames buffered while a gap is open. */
  gapBufferLimit: number;
  /** Minimum characters in a denial reason. Mirrors the server; never enforces. */
  denialReasonMinLength: number;
  /** Minimum characters when overriding the supervisor agent's verdict. */
  overrideJustificationMinLength: number;
  /** Post-signature undo window for REVERSIBLE actions only. */
  undoWindowMs: number;
  /** Live-region coalescing window for screen-reader announcements. */
  ariaCoalesceMs: number;
  /**
   * Demo mode. Replays a recorded envelope array through the REAL reducer, so a
   * demo exercises the same code path the product does. Off by default because
   * a replay control on a live banker's screen is a footgun.
   */
  demoModeEnabled: boolean;
  /** Replay the recording on mount. Only meaningful when demo mode is enabled. */
  demoAutoplay: boolean;
}

const DEFAULTS: CopilotConfig = {
  endpoints: {
    copilotBase: '/api/copilot',
    authorityBase: '/api/authority',
    sessions: '/sessions',
    sessionStream: '/sessions/{sessionId}/stream',
    sessionMessages: '/sessions/{sessionId}/messages',
    sessionRuns: '/sessions/{sessionId}/runs',
    runTrace: '/runs/{runId}/trace',
    approvals: '/approvals',
  },
  dwellMs: {
    l1Reversible: 3000,
    l1Irreversible: 8000,
    l2Agree: 15000,
    l2Disagree: 25000,
    resupersededMultiplier: 1,
  },
  sessionSignatureSoftLimit: 10,
  sessionSignatureWindowMs: 60 * 60 * 1000,
  spotCheckRate: 0.07,
  queueVisibleLimit: 5,
  maxTraceDepth: 3,
  virtualiseAboveNodes: 200,
  heartbeatIntervalMs: 15000,
  missedHeartbeatsBeforeDegraded: 2,
  reconnectBaseMs: 500,
  reconnectMaxMs: 15000,
  gapResyncTimeoutMs: 5000,
  gapBufferLimit: 200,
  denialReasonMinLength: 20,
  overrideJustificationMinLength: 20,
  undoWindowMs: 30000,
  ariaCoalesceMs: 2500,
  demoModeEnabled: false,
  demoAutoplay: false,
};

/**
 * Hard floors. See the module comment: a config value may tune a control, never
 * empty one.
 *
 * `spotCheckRate` has no floor because zero is a legitimate operational choice
 * (it is a sampling mechanism, not a gate) — but the dwell floors are absolute.
 */
const FLOORS = {
  dwellMs: {
    l1Reversible: 1000,
    l1Irreversible: 3000,
    l2Agree: 5000,
    l2Disagree: 10000,
  },
  denialReasonMinLength: 20,
  overrideJustificationMinLength: 20,
  queueVisibleLimit: 1,
  maxTraceDepth: 1,
} as const;

interface RuntimeShape {
  copilot?: Record<string, unknown>;
}

function runtimeSection(): Record<string, unknown> {
  if (typeof window === 'undefined') return {};
  const cfg = (window as unknown as { __RUNTIME_CONFIG__?: RuntimeShape }).__RUNTIME_CONFIG__;
  const section = cfg && cfg.copilot;
  return section && typeof section === 'object' ? (section as Record<string, unknown>) : {};
}

function num(raw: unknown): number | undefined {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw === 'string' && raw.trim() !== '') {
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function bool(raw: unknown, envValue: string | undefined, fallback: boolean): boolean {
  if (typeof raw === 'boolean') return raw;
  if (typeof raw === 'string' && raw.trim() !== '') return raw.trim().toLowerCase() === 'true';
  if (typeof envValue === 'string' && envValue.trim() !== '') {
    return envValue.trim().toLowerCase() === 'true';
  }
  return fallback;
}

function str(raw: unknown): string | undefined {
  return typeof raw === 'string' && raw.trim() !== '' ? raw.trim() : undefined;
}

/**
 * CRA inlines `process.env.REACT_APP_*` by literal text substitution at build
 * time. A computed lookup resolves to undefined in the production bundle while
 * working perfectly under `npm start`, so these MUST be written out statically.
 * The verbosity is the workaround, not an oversight.
 */
function buildEnv(): Record<string, string | undefined> {
  return {
    copilotBase: process.env.REACT_APP_COPILOT_BASE_PATH,
    authorityBase: process.env.REACT_APP_AUTHORITY_BASE_PATH,
    dwellL1Reversible: process.env.REACT_APP_COPILOT_DWELL_L1_REVERSIBLE_MS,
    dwellL1Irreversible: process.env.REACT_APP_COPILOT_DWELL_L1_IRREVERSIBLE_MS,
    dwellL2Agree: process.env.REACT_APP_COPILOT_DWELL_L2_AGREE_MS,
    dwellL2Disagree: process.env.REACT_APP_COPILOT_DWELL_L2_DISAGREE_MS,
    sessionSignatureSoftLimit: process.env.REACT_APP_COPILOT_SIGNATURE_SOFT_LIMIT,
    sessionSignatureWindowMs: process.env.REACT_APP_COPILOT_SIGNATURE_WINDOW_MS,
    spotCheckRate: process.env.REACT_APP_COPILOT_SPOT_CHECK_RATE,
    queueVisibleLimit: process.env.REACT_APP_COPILOT_QUEUE_VISIBLE_LIMIT,
    heartbeatIntervalMs: process.env.REACT_APP_COPILOT_HEARTBEAT_MS,
    undoWindowMs: process.env.REACT_APP_COPILOT_UNDO_WINDOW_MS,
    demoModeEnabled: process.env.REACT_APP_COPILOT_DEMO_MODE,
    demoAutoplay: process.env.REACT_APP_COPILOT_DEMO_AUTOPLAY,
  };
}

function clampFloor(value: number, floor: number, label: string): number {
  if (value < floor) {
    logger.warn(
      `copilotConfig: ${label}=${value} is below the enforced floor ${floor}; using the floor. ` +
        'Anti-fatigue controls are tunable but not removable.'
    );
    return floor;
  }
  return value;
}

let cached: CopilotConfig | null = null;

/** Resolve once per page load; `resetCopilotConfig()` exists for tests. */
export function getCopilotConfig(): CopilotConfig {
  if (cached) return cached;

  const rt = runtimeSection();
  const env = buildEnv();
  const rtDwell = (rt.dwellMs && typeof rt.dwellMs === 'object'
    ? (rt.dwellMs as Record<string, unknown>)
    : {}) as Record<string, unknown>;
  const rtEndpoints = (rt.endpoints && typeof rt.endpoints === 'object'
    ? (rt.endpoints as Record<string, unknown>)
    : {}) as Record<string, unknown>;

  const pick = (rtValue: unknown, envValue: string | undefined, fallback: number): number =>
    num(rtValue) ?? num(envValue) ?? fallback;

  const endpoints: CopilotEndpoints = {
    copilotBase:
      str(rtEndpoints.copilotBase) ?? str(env.copilotBase) ?? DEFAULTS.endpoints.copilotBase,
    authorityBase:
      str(rtEndpoints.authorityBase) ?? str(env.authorityBase) ?? DEFAULTS.endpoints.authorityBase,
    sessions: str(rtEndpoints.sessions) ?? DEFAULTS.endpoints.sessions,
    sessionStream: str(rtEndpoints.sessionStream) ?? DEFAULTS.endpoints.sessionStream,
    sessionMessages: str(rtEndpoints.sessionMessages) ?? DEFAULTS.endpoints.sessionMessages,
    sessionRuns: str(rtEndpoints.sessionRuns) ?? DEFAULTS.endpoints.sessionRuns,
    runTrace: str(rtEndpoints.runTrace) ?? DEFAULTS.endpoints.runTrace,
    approvals: str(rtEndpoints.approvals) ?? DEFAULTS.endpoints.approvals,
  };

  const dwellMs: DwellPolicyMs = {
    l1Reversible: clampFloor(
      pick(rtDwell.l1Reversible, env.dwellL1Reversible, DEFAULTS.dwellMs.l1Reversible),
      FLOORS.dwellMs.l1Reversible,
      'dwellMs.l1Reversible'
    ),
    l1Irreversible: clampFloor(
      pick(rtDwell.l1Irreversible, env.dwellL1Irreversible, DEFAULTS.dwellMs.l1Irreversible),
      FLOORS.dwellMs.l1Irreversible,
      'dwellMs.l1Irreversible'
    ),
    l2Agree: clampFloor(
      pick(rtDwell.l2Agree, env.dwellL2Agree, DEFAULTS.dwellMs.l2Agree),
      FLOORS.dwellMs.l2Agree,
      'dwellMs.l2Agree'
    ),
    l2Disagree: clampFloor(
      pick(rtDwell.l2Disagree, env.dwellL2Disagree, DEFAULTS.dwellMs.l2Disagree),
      FLOORS.dwellMs.l2Disagree,
      'dwellMs.l2Disagree'
    ),
    resupersededMultiplier: Math.max(
      1,
      pick(rtDwell.resupersededMultiplier, undefined, DEFAULTS.dwellMs.resupersededMultiplier)
    ),
  };

  cached = {
    endpoints,
    dwellMs,
    sessionSignatureSoftLimit: Math.max(
      1,
      pick(
        rt.sessionSignatureSoftLimit,
        env.sessionSignatureSoftLimit,
        DEFAULTS.sessionSignatureSoftLimit
      )
    ),
    sessionSignatureWindowMs: Math.max(
      60000,
      pick(
        rt.sessionSignatureWindowMs,
        env.sessionSignatureWindowMs,
        DEFAULTS.sessionSignatureWindowMs
      )
    ),
    spotCheckRate: Math.min(
      1,
      Math.max(0, pick(rt.spotCheckRate, env.spotCheckRate, DEFAULTS.spotCheckRate))
    ),
    queueVisibleLimit: clampFloor(
      pick(rt.queueVisibleLimit, env.queueVisibleLimit, DEFAULTS.queueVisibleLimit),
      FLOORS.queueVisibleLimit,
      'queueVisibleLimit'
    ),
    maxTraceDepth: clampFloor(
      pick(rt.maxTraceDepth, undefined, DEFAULTS.maxTraceDepth),
      FLOORS.maxTraceDepth,
      'maxTraceDepth'
    ),
    virtualiseAboveNodes: pick(rt.virtualiseAboveNodes, undefined, DEFAULTS.virtualiseAboveNodes),
    heartbeatIntervalMs: pick(
      rt.heartbeatIntervalMs,
      env.heartbeatIntervalMs,
      DEFAULTS.heartbeatIntervalMs
    ),
    missedHeartbeatsBeforeDegraded: Math.max(
      1,
      pick(
        rt.missedHeartbeatsBeforeDegraded,
        undefined,
        DEFAULTS.missedHeartbeatsBeforeDegraded
      )
    ),
    reconnectBaseMs: pick(rt.reconnectBaseMs, undefined, DEFAULTS.reconnectBaseMs),
    reconnectMaxMs: pick(rt.reconnectMaxMs, undefined, DEFAULTS.reconnectMaxMs),
    gapResyncTimeoutMs: pick(rt.gapResyncTimeoutMs, undefined, DEFAULTS.gapResyncTimeoutMs),
    gapBufferLimit: pick(rt.gapBufferLimit, undefined, DEFAULTS.gapBufferLimit),
    denialReasonMinLength: clampFloor(
      pick(rt.denialReasonMinLength, undefined, DEFAULTS.denialReasonMinLength),
      FLOORS.denialReasonMinLength,
      'denialReasonMinLength'
    ),
    overrideJustificationMinLength: clampFloor(
      pick(rt.overrideJustificationMinLength, undefined, DEFAULTS.overrideJustificationMinLength),
      FLOORS.overrideJustificationMinLength,
      'overrideJustificationMinLength'
    ),
    undoWindowMs: Math.max(0, pick(rt.undoWindowMs, env.undoWindowMs, DEFAULTS.undoWindowMs)),
    ariaCoalesceMs: pick(rt.ariaCoalesceMs, undefined, DEFAULTS.ariaCoalesceMs),
    demoModeEnabled: bool(rt.demoModeEnabled, env.demoModeEnabled, DEFAULTS.demoModeEnabled),
    demoAutoplay: bool(rt.demoAutoplay, env.demoAutoplay, DEFAULTS.demoAutoplay),
  };

  return cached;
}

export function resetCopilotConfig(): void {
  cached = null;
}

/** `/sessions/{sessionId}/stream` → `/api/copilot/sessions/sess_1/stream`. */
export function copilotUrl(template: string, params: Record<string, string> = {}): string {
  const { endpoints } = getCopilotConfig();
  const path = Object.entries(params).reduce(
    (acc, [key, value]) => acc.split(`{${key}}`).join(encodeURIComponent(value)),
    template
  );
  return `${endpoints.copilotBase}${path}`;
}

export function authorityUrl(path: string): string {
  const { endpoints } = getCopilotConfig();
  return `${endpoints.authorityBase}${path}`;
}

export const COPILOT_CONFIG_DEFAULTS = DEFAULTS;
export const COPILOT_CONFIG_FLOORS = FLOORS;
