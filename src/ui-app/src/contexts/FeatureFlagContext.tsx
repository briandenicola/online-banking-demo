/**
 * Feature flag context.
 *
 * Follows the existing provider convention in this folder (AuthContext,
 * AccountContext): a typed context, a `useX` hook that throws outside the
 * provider, and synchronous initialisation from browser storage so there is no
 * flash of the wrong state on first render.
 *
 * REMINDER: flags are a PRESENTATION toggle, never a security control. The full
 * statement of that guarantee lives in ../config/featureFlags.ts — read it
 * there rather than trusting this summary.
 *
 * Runtime-toggleable by design: `setFlag` writes a localStorage override and
 * re-renders immediately. No rebuild, no redeploy, no page reload. That is the
 * whole point — the surfaces can be switched live, mid-demo, in front of an
 * audience.
 */
import React, { createContext, useCallback, useContext, useMemo, useState, ReactNode } from 'react';
import {
  FeatureFlagName,
  FeatureFlagValues,
  ResolvedFlag,
  FLAG_DEFINITIONS,
  FLAG_NAMES,
  clearOverrides,
  flagValues,
  ingestUrlOverrides,
  persistOverride,
  resolveFlags,
} from '../config/featureFlags';

interface FeatureFlagContextType {
  flags: FeatureFlagValues;
  /** Provenance per flag, for the toggle UI and for debugging. */
  resolved: Record<FeatureFlagName, ResolvedFlag>;
  isEnabled: (name: FeatureFlagName) => boolean;
  /** Persist a per-browser override and re-render. */
  setFlag: (name: FeatureFlagName, value: boolean) => void;
  /** Drop all local overrides, returning to the deployment default. */
  resetFlags: () => void;
}

const FeatureFlagContext = createContext<FeatureFlagContextType | undefined>(undefined);

export const useFeatureFlags = (): FeatureFlagContextType => {
  const context = useContext(FeatureFlagContext);
  if (!context) throw new Error('useFeatureFlags must be used within FeatureFlagProvider');
  return context;
};

/** Convenience hook for the common single-flag case. */
export const useFeatureFlag = (name: FeatureFlagName): boolean =>
  useFeatureFlags().isEnabled(name);

export const FeatureFlagProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [resolved, setResolved] = useState<Record<FeatureFlagName, ResolvedFlag>>(() => {
    // Ingest ?ff=... into sessionStorage BEFORE resolving, so a link-supplied
    // value is visible on the very first render rather than one render late.
    ingestUrlOverrides();
    return resolveFlags();
  });

  const setFlag = useCallback((name: FeatureFlagName, value: boolean) => {
    persistOverride(name, value);
    setResolved(resolveFlags());
  }, []);

  const resetFlags = useCallback(() => {
    clearOverrides();
    setResolved(resolveFlags());
  }, []);

  const flags = useMemo(() => flagValues(resolved), [resolved]);

  const isEnabled = useCallback(
    (name: FeatureFlagName) => flags[name] === true,
    [flags]
  );

  const value = useMemo(
    () => ({ flags, resolved, isEnabled, setFlag, resetFlags }),
    [flags, resolved, isEnabled, setFlag, resetFlags]
  );

  return <FeatureFlagContext.Provider value={value}>{children}</FeatureFlagContext.Provider>;
};

export { FLAG_DEFINITIONS, FLAG_NAMES };
export type { FeatureFlagName, FeatureFlagValues, ResolvedFlag };
