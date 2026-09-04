/**
 * Feature flags for the ui-app.
 *
 * ============================================================================
 * THIS IS A PRESENTATION TOGGLE. IT IS NOT A SECURITY CONTROL.
 * ============================================================================
 *
 * Read this before you reason about a flag as though it enforces something,
 * because it does not, and someone eventually will.
 *
 * Every value resolved here comes from the browser: a URL query parameter, a
 * localStorage entry, or a world-readable JavaScript file served to anonymous
 * visitors. All three are user-controlled. Anyone with devtools can set any
 * flag to any value in about four seconds, and nothing stops them.
 *
 * What that means concretely:
 *
 *   - Hiding a nav item hides a nav item. It does not make the destination
 *     unreachable, unguessable, or unauthorised.
 *   - Refusing to render a route (which we DO — see the guarantee below) removes
 *     the React screen. It does not remove the HTTP API behind it. Every request
 *     that screen would have made is still reachable with curl and a valid token.
 *   - Turning a flag off protects nothing and leaks nothing. Turning it on
 *     grants nothing.
 *
 * The actual boundaries, unchanged by anything in this file:
 *
 *   1. Authentication  — a valid JWT, enforced server-side.
 *   2. Authorisation   — role checks in the gateway and in each service, and
 *                        the authority ladder in authority-service for anything
 *                        that changes state.
 *   3. `isAdmin`       — the client-side role gate in App.tsx, which is itself
 *                        only a convenience mirror of (2), not a control either.
 *
 * If you find yourself writing "we can hide it with the flag" as the answer to
 * a security question, the answer is wrong. Add a server-side check.
 *
 * ----------------------------------------------------------------------------
 * THE ROUTE GUARANTEE — stated explicitly rather than implied
 * ----------------------------------------------------------------------------
 *
 * When a surface flag is off, this app hides the navigation AND refuses to
 * render the route, showing an explanatory notice with a one-click re-enable.
 *
 * We refuse the route for EXPERIMENTAL HYGIENE, not for security: the whole
 * point of the coexistence period is measuring two surfaces against each other,
 * and a participant who wanders onto the disabled surface mid-task silently
 * contaminates the measurement. Refusing the route makes that hard to do by
 * accident.
 *
 * The refusal is deliberately *loud and reversible* — it names the flag and
 * offers to turn it back on — precisely so nobody mistakes it for an
 * authorisation failure. An authorisation failure would not offer you a button
 * that fixes it.
 *
 * ----------------------------------------------------------------------------
 * RESOLUTION ORDER (first match wins)
 * ----------------------------------------------------------------------------
 *
 *   1. URL query param     ?ff=bankerCopilot:on,classicAdminTabs:off
 *                          Mirrored into sessionStorage, so it survives in-tab
 *                          navigation and dies with the tab. Good for sharing a
 *                          link that opens on a specific surface.
 *   2. localStorage        Set by the in-app toggle. Persists across reloads.
 *                          This is the mid-demo flip: no rebuild, no redeploy,
 *                          not even a page reload — just a re-render.
 *   3. Runtime config      window.__RUNTIME_CONFIG__.featureFlags, from
 *                          public/runtime-config.js. The DEPLOYMENT default,
 *                          changeable by remounting that file.
 *   4. Build-time env      REACT_APP_FF_<UPPER_SNAKE>, following the existing
 *                          REACT_APP_DEMO_MODE convention in pages/Login.tsx.
 *                          Baked at build time; last resort.
 *   5. Hardcoded default   FLAG_DEFINITIONS below.
 *
 * Layers 1 and 2 are per-browser, which is also how per-user assignment works
 * for the A/B comparison (§11). There is no per-user server-side flag store and
 * we do not need one.
 */

export type FeatureFlagName =
  | 'classicAdminTabs'
  | 'bankerCopilot'
  | 'comparisonInstrumentation';

export interface FeatureFlagDefinition {
  name: FeatureFlagName;
  /** Shown in the toggle UI. */
  label: string;
  /** Shown in the toggle UI and on the route-refusal notice. */
  description: string;
  /** Value when no layer above supplies one. */
  defaultValue: boolean;
  /**
   * True when this flag gates a whole navigable surface. Surface flags hide
   * nav AND refuse routes (see the route guarantee above). Non-surface flags
   * only change behaviour within a surface.
   */
  gatesSurface: boolean;
  /**
   * A scheduled change to `defaultValue`, written down because deferred
   * default changes are exactly the decisions that get forgotten. Rendered in
   * the toggle UI so it stays in front of whoever is looking at the flags.
   */
  plannedDefaultChange?: {
    to: boolean;
    when: string;
    rationale: string;
  };
}

export const FLAG_DEFINITIONS: Record<FeatureFlagName, FeatureFlagDefinition> = {
  classicAdminTabs: {
    name: 'classicAdminTabs',
    label: 'Classic Admin (legacy tabs)',
    description:
      'The original 8-tab admin console at /admin. Kept alongside the Banker Copilot harness so the two surfaces can be compared on the same tasks.',
    defaultValue: true,
    gatesSurface: true,
    plannedDefaultChange: {
      to: true,
      when: 'Unchanged when Phase 2 lands, and unchanged at Phase 5.',
      rationale:
        'Phase 5 was changed from "admin tab retirement" to coexistence (Brian, 2026-09-04). Retiring the tabs is no longer a scheduled event: it requires an explicit ruling supported by comparison data, not the passage of a phase. Until such a ruling exists, this default stays true.',
    },
  },
  bankerCopilot: {
    name: 'bankerCopilot',
    label: 'Banker Copilot harness',
    description:
      'The agentic harness at /copilot: task queue, live plan/trace pane, artifact canvas, and the approval surface.',
    defaultValue: false,
    gatesSurface: true,
    plannedDefaultChange: {
      to: true,
      when: 'When Phase 2 lands — i.e. when /copilot renders a real harness rather than a placeholder.',
      rationale:
        'False today because the harness does not exist, and shipping a nav item to an empty route is worse than shipping nothing. Flips to true with Phase 2 so BOTH surfaces are visible by default: coexistence is the point, and a comparison you have to opt into is a comparison nobody runs.',
    },
  },
  comparisonInstrumentation: {
    name: 'comparisonInstrumentation',
    label: 'Surface comparison measurement',
    description:
      'Records task timings, interaction counts, and surface switches for the Classic-vs-Copilot comparison. Buffered in the browser only; nothing is transmitted.',
    defaultValue: true,
    gatesSurface: false,
  },
};

export const FLAG_NAMES = Object.keys(FLAG_DEFINITIONS) as FeatureFlagName[];

export type FeatureFlagValues = Record<FeatureFlagName, boolean>;

/** Which layer supplied the value. Surfaced in the toggle UI for debuggability. */
export type FlagSource =
  | 'url'
  | 'localStorage'
  | 'runtimeConfig'
  | 'buildEnv'
  | 'default';

export interface ResolvedFlag {
  name: FeatureFlagName;
  value: boolean;
  source: FlagSource;
}

const STORAGE_PREFIX = 'ff_';
const URL_PARAM = 'ff';

interface RuntimeConfigShape {
  featureFlags?: Record<string, unknown>;
}

/** Tolerant parse. Anything unrecognised yields undefined so the next layer wins. */
function parseBool(raw: unknown): boolean | undefined {
  if (typeof raw === 'boolean') return raw;
  if (typeof raw !== 'string') return undefined;
  const v = raw.trim().toLowerCase();
  if (v === 'true' || v === '1' || v === 'on' || v === 'yes') return true;
  if (v === 'false' || v === '0' || v === 'off' || v === 'no') return false;
  return undefined;
}

function isFlagName(name: string): name is FeatureFlagName {
  return Object.prototype.hasOwnProperty.call(FLAG_DEFINITIONS, name);
}

/** `REACT_APP_FF_BANKER_COPILOT` for `bankerCopilot`. */
export function envVarNameFor(flag: FeatureFlagName): string {
  return `REACT_APP_FF_${flag.replace(/([A-Z])/g, '_$1').toUpperCase()}`;
}

function safeStorage(kind: 'local' | 'session'): Storage | null {
  try {
    const s = kind === 'local' ? window.localStorage : window.sessionStorage;
    // Touch it — Safari private mode throws on write, not on access.
    const probe = `${STORAGE_PREFIX}__probe`;
    s.setItem(probe, '1');
    s.removeItem(probe);
    return s;
  } catch {
    return null;
  }
}

/**
 * Reads `?ff=a:on,b:off` and mirrors it into sessionStorage.
 *
 * Session-scoped on purpose: a URL you were sent should not permanently
 * reconfigure your browser. localStorage is reserved for a deliberate in-app
 * toggle, where the user knows they changed something.
 */
export function ingestUrlOverrides(search?: string): Partial<FeatureFlagValues> {
  const applied: Partial<FeatureFlagValues> = {};
  if (typeof window === 'undefined') return applied;

  const raw = search ?? window.location?.search ?? '';
  if (!raw) return applied;

  let params: URLSearchParams;
  try {
    params = new URLSearchParams(raw);
  } catch {
    return applied;
  }

  const spec = params.get(URL_PARAM);
  if (!spec) return applied;

  const session = safeStorage('session');
  for (const pair of spec.split(',')) {
    const [name, value] = pair.split(':').map((p) => (p ? p.trim() : p));
    if (!name || !isFlagName(name)) continue;
    const parsed = parseBool(value === undefined ? 'on' : value);
    if (parsed === undefined) continue;
    applied[name] = parsed;
    if (session) session.setItem(STORAGE_PREFIX + name, String(parsed));
  }
  return applied;
}

type StorageLayer = Partial<Record<FeatureFlagName, { value: boolean; source: FlagSource }>>;

function readStorageLayer(): StorageLayer {
  const out: StorageLayer = {};
  const session = safeStorage('session');
  const local = safeStorage('local');

  for (const name of FLAG_NAMES) {
    const sessionRaw = session ? session.getItem(STORAGE_PREFIX + name) : null;
    const fromSession = parseBool(sessionRaw === null ? undefined : sessionRaw);
    if (fromSession !== undefined) {
      out[name] = { value: fromSession, source: 'url' };
      continue;
    }
    const localRaw = local ? local.getItem(STORAGE_PREFIX + name) : null;
    const fromLocal = parseBool(localRaw === null ? undefined : localRaw);
    if (fromLocal !== undefined) {
      out[name] = { value: fromLocal, source: 'localStorage' };
    }
  }
  return out;
}

function readRuntimeConfigLayer(): Partial<Record<FeatureFlagName, boolean>> {
  const out: Partial<Record<FeatureFlagName, boolean>> = {};
  const cfg =
    typeof window !== 'undefined'
      ? (window as unknown as { __RUNTIME_CONFIG__?: RuntimeConfigShape }).__RUNTIME_CONFIG__
      : undefined;
  const flags = cfg && cfg.featureFlags;
  if (!flags) return out;

  for (const name of FLAG_NAMES) {
    const parsed = parseBool(flags[name]);
    if (parsed !== undefined) out[name] = parsed;
  }
  return out;
}

function readBuildEnvLayer(): Partial<Record<FeatureFlagName, boolean>> {
  const out: Partial<Record<FeatureFlagName, boolean>> = {};
  // CRA inlines process.env.REACT_APP_* at build time via literal text
  // substitution, so these MUST be written as static property accesses. A
  // computed lookup like process.env[name] resolves to undefined in the
  // production bundle. This is webpack DefinePlugin behaviour, not style.
  const literal: Record<FeatureFlagName, string | undefined> = {
    classicAdminTabs: process.env.REACT_APP_FF_CLASSIC_ADMIN_TABS,
    bankerCopilot: process.env.REACT_APP_FF_BANKER_COPILOT,
    comparisonInstrumentation: process.env.REACT_APP_FF_COMPARISON_INSTRUMENTATION,
  };
  for (const name of FLAG_NAMES) {
    const parsed = parseBool(literal[name]);
    if (parsed !== undefined) out[name] = parsed;
  }
  return out;
}

/** Full resolution across all layers, with provenance. */
export function resolveFlags(): Record<FeatureFlagName, ResolvedFlag> {
  const storage = readStorageLayer();
  const runtime = readRuntimeConfigLayer();
  const buildEnv = readBuildEnvLayer();

  const resolved = {} as Record<FeatureFlagName, ResolvedFlag>;
  for (const name of FLAG_NAMES) {
    const fromStorage = storage[name];
    if (fromStorage) {
      resolved[name] = { name, value: fromStorage.value, source: fromStorage.source };
      continue;
    }
    const fromRuntime = runtime[name];
    if (fromRuntime !== undefined) {
      resolved[name] = { name, value: fromRuntime, source: 'runtimeConfig' };
      continue;
    }
    const fromEnv = buildEnv[name];
    if (fromEnv !== undefined) {
      resolved[name] = { name, value: fromEnv, source: 'buildEnv' };
      continue;
    }
    resolved[name] = { name, value: FLAG_DEFINITIONS[name].defaultValue, source: 'default' };
  }
  return resolved;
}

export function flagValues(resolved: Record<FeatureFlagName, ResolvedFlag>): FeatureFlagValues {
  const out = {} as FeatureFlagValues;
  for (const name of FLAG_NAMES) out[name] = resolved[name].value;
  return out;
}

/** Persist a deliberate in-app override. Survives reload; per-browser. */
export function persistOverride(name: FeatureFlagName, value: boolean): void {
  // Clear the session (URL) layer too, otherwise a link-supplied value would
  // silently outrank the switch the user just flipped — which looks like a bug.
  const session = safeStorage('session');
  if (session) session.removeItem(STORAGE_PREFIX + name);
  const local = safeStorage('local');
  if (local) local.setItem(STORAGE_PREFIX + name, String(value));
}

/** Drop all browser-local overrides and fall back to the deployment default. */
export function clearOverrides(): void {
  const local = safeStorage('local');
  const session = safeStorage('session');
  for (const name of FLAG_NAMES) {
    if (local) local.removeItem(STORAGE_PREFIX + name);
    if (session) session.removeItem(STORAGE_PREFIX + name);
  }
}
