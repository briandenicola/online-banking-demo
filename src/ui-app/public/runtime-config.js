/*
 * Runtime configuration for the SPA.
 *
 * WHY THIS IS A .js FILE AND NOT .json
 * ------------------------------------
 * index.html loads this with a plain synchronous <script> tag BEFORE the React
 * bundle. That means feature flags are resolved before the first render, so the
 * app never flashes the wrong surface on boot. A fetched /config.json would be
 * async and would guarantee a flash of the default UI on every page load —
 * unacceptable for a flag whose entire job is deciding which surface you see.
 *
 * HOW TO OVERRIDE PER DEPLOYMENT
 * ------------------------------
 * This file is baked into the image at /usr/share/nginx/html/runtime-config.js
 * and is meant to be REPLACED at deploy time by mounting over it:
 *
 *   docker-compose:  ./infra/local/runtime-config.js:/usr/share/nginx/html/runtime-config.js:ro
 *   kustomize:       ConfigMap volume, subPath: runtime-config.js
 *
 * Editing the mounted file and reloading the browser changes the deployed
 * default with no rebuild. See docs/design/banker-copilot-ui.md §10.
 *
 * SECURITY NOTE — READ THIS BEFORE ADDING ANYTHING
 * ------------------------------------------------
 * This file is served to every anonymous visitor and is world-readable. It
 * carries PRESENTATION settings only. Never put a secret, a key, a connection
 * string, or anything whose disclosure matters into this file. The feature
 * flags below are UI toggles and are NOT security controls — see
 * src/config/featureFlags.ts for the full statement of that guarantee.
 */
window.__RUNTIME_CONFIG__ = {
  featureFlags: {
    // Show the legacy 8-tab admin console at /admin.
    // Default TRUE: retiring the tabs was explicitly overruled in favour of
    // coexistence so the two surfaces can be compared honestly
    // (Brian, 2026-09-04). Now instrumented for that comparison.
    classicAdminTabs: true,

    // Show the Banker Copilot harness at /copilot.
    // Flipped to TRUE in Phase 2, on the condition written down in Phase 1:
    // the route now renders the real harness. Both surfaces are visible by
    // default because a comparison you have to opt into is one nobody runs.
    // This is a presentation toggle. It grants no authority — every signature
    // is checked by authority-service, which has never heard of this flag.
    bankerCopilot: true,

    // Collect the side-by-side comparison measurements (§11). Local-buffer
    // only; export is manual, from the strip at the top of either surface.
    comparisonInstrumentation: true,
  },
};
