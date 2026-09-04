/*
 * ui-app runtime configuration — DEPLOYMENT DEFAULTS
 * =================================================
 *
 * This is layer 3 of the five-layer flag resolver in
 * src/ui-app/src/config/featureFlags.ts:
 *
 *   URL ?ff= → localStorage → THIS FILE → REACT_APP_FF_* → code default
 *
 * index.html loads it with a plain synchronous <script> before the React
 * bundle, so flags are resolved before first render and the app never flashes
 * the wrong surface on boot. Linus owns the resolver and the in-image template
 * at src/ui-app/public/runtime-config.js; this file is the deployed override
 * that gets mounted on top of it.
 *
 * WHY THIS FILE LIVES HERE AND NOT IN infra/local/
 * ------------------------------------------------
 * It is mounted two ways and there must be exactly ONE copy of it:
 *
 *   docker-compose : bind mount over /usr/share/nginx/html/runtime-config.js
 *   AKS            : configMapGenerator in deploy/kustomize/base/kustomization.yaml
 *
 * kustomize refuses to read files outside its own root, so a copy under
 * infra/local/ would have forced a second copy under deploy/. Two files that
 * must agree, with nothing comparing them, is the exact bug class that put a
 * retail customer's token into an L1 signature slot earlier today. One file,
 * slightly odd path, beats two files and a tidy one.
 *
 * ABSENCE IS A NORMAL STATE
 * -------------------------
 * The app works with no mount at all — layer 5 supplies safe defaults, and the
 * image already carries Linus's template. Nothing here is a startup dependency
 * and nothing fails closed on it. Deleting the mount degrades to the built-in
 * defaults, which is the intended behaviour, not an outage.
 *
 * CHANGING A FLAG WITHOUT A REBUILD
 * ---------------------------------
 *   docker-compose : edit this file, reload the browser. That is the whole loop.
 *   AKS            : edit this file, re-run the deploy task. kustomize hashes
 *                    the ConfigMap name, so the content change rolls the pod —
 *                    which is required, because subPath mounts do NOT pick up
 *                    ConfigMap updates in place. No image rebuild either way.
 *
 * Per-browser mid-demo flipping is layers 1-2 (the toggle panel), not this
 * file. This file changes what a NEW visitor sees.
 *
 * SECURITY — READ BEFORE ADDING ANYTHING
 * --------------------------------------
 * Served to every anonymous visitor and world-readable. PRESENTATION settings
 * only. Never a secret, key, connection string, endpoint, or anything whose
 * disclosure matters. These flags are UI toggles and are NOT security controls:
 * turning one off protects nothing and turning one on grants nothing — the HTTP
 * APIs behind every surface are gated server-side and are unaffected by this
 * file.
 */
window.__RUNTIME_CONFIG__ = {
  featureFlags: {
    // Legacy 8-tab admin console at /admin.
    // TRUE: Phase 5 was changed from retirement to coexistence so the two
    // surfaces can be compared honestly (Brian, 2026-09-04). Retiring these
    // tabs now requires an explicit ruling against the D5 falsifiers, not the
    // passage of a phase.
    classicAdminTabs: true,

    // Banker Copilot harness at /copilot.
    // FALSE until Phase 2 lands — a nav item pointing at an empty route is
    // worse than no nav item. Flips to TRUE with Phase 2 so BOTH surfaces are
    // visible by default; a comparison you have to opt into is a comparison
    // nobody runs.
    bankerCopilot: false,

    // Side-by-side comparison measurements. Local-buffer only today; no data
    // leaves the browser until an exporter is wired.
    comparisonInstrumentation: true,
  },
};
