import {
  FLAG_DEFINITIONS,
  clearOverrides,
  envVarNameFor,
  flagValues,
  ingestUrlOverrides,
  persistOverride,
  resolveFlags,
} from '../featureFlags';

type TestWindow = Window & { __RUNTIME_CONFIG__?: { featureFlags?: Record<string, unknown> } };
const testWindow = window as TestWindow;

describe('featureFlags resolution', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    delete testWindow.__RUNTIME_CONFIG__;
  });

  it('falls back to hardcoded defaults when no layer supplies a value', () => {
    const values = flagValues(resolveFlags());
    expect(values.classicAdminTabs).toBe(FLAG_DEFINITIONS.classicAdminTabs.defaultValue);
    expect(values.bankerCopilot).toBe(FLAG_DEFINITIONS.bankerCopilot.defaultValue);
  });

  it('defaults to tabs visible and harness hidden today', () => {
    // The harness does not exist yet, so this default is load-bearing: it is
    // what keeps the app usable on a fresh browser with no config mounted.
    const values = flagValues(resolveFlags());
    expect(values.classicAdminTabs).toBe(true);
    expect(values.bankerCopilot).toBe(false);
  });

  it('lets runtime config override the hardcoded default', () => {
    testWindow.__RUNTIME_CONFIG__ = { featureFlags: { bankerCopilot: true } };
    const resolved = resolveFlags();
    expect(resolved.bankerCopilot.value).toBe(true);
    expect(resolved.bankerCopilot.source).toBe('runtimeConfig');
  });

  it('lets a localStorage override beat runtime config', () => {
    testWindow.__RUNTIME_CONFIG__ = { featureFlags: { classicAdminTabs: true } };
    persistOverride('classicAdminTabs', false);
    const resolved = resolveFlags();
    expect(resolved.classicAdminTabs.value).toBe(false);
    expect(resolved.classicAdminTabs.source).toBe('localStorage');
  });

  it('lets a URL override beat a localStorage override', () => {
    persistOverride('bankerCopilot', false);
    ingestUrlOverrides('?ff=bankerCopilot:on');
    const resolved = resolveFlags();
    expect(resolved.bankerCopilot.value).toBe(true);
    expect(resolved.bankerCopilot.source).toBe('url');
  });

  it('keeps URL overrides in sessionStorage, not localStorage', () => {
    // A link someone sent you must not permanently reconfigure your browser.
    ingestUrlOverrides('?ff=bankerCopilot:on');
    expect(window.sessionStorage.getItem('ff_bankerCopilot')).toBe('true');
    expect(window.localStorage.getItem('ff_bankerCopilot')).toBeNull();
  });

  it('clears the URL layer when the user deliberately flips a switch', () => {
    // Otherwise a link-supplied value silently outranks the switch the user
    // just flipped, which looks exactly like a broken toggle.
    ingestUrlOverrides('?ff=bankerCopilot:on');
    persistOverride('bankerCopilot', false);
    const resolved = resolveFlags();
    expect(resolved.bankerCopilot.value).toBe(false);
    expect(resolved.bankerCopilot.source).toBe('localStorage');
  });

  it('parses multiple flags and common boolean spellings from the URL', () => {
    ingestUrlOverrides('?ff=bankerCopilot:true,classicAdminTabs:0');
    const values = flagValues(resolveFlags());
    expect(values.bankerCopilot).toBe(true);
    expect(values.classicAdminTabs).toBe(false);
  });

  it('treats a bare flag name in the URL as enable', () => {
    ingestUrlOverrides('?ff=bankerCopilot');
    expect(resolveFlags().bankerCopilot.value).toBe(true);
  });

  it('ignores unknown flag names and unparseable values', () => {
    ingestUrlOverrides('?ff=notAFlag:on,bankerCopilot:banana');
    const resolved = resolveFlags();
    expect(resolved.bankerCopilot.value).toBe(false);
    expect(resolved.bankerCopilot.source).toBe('default');
  });

  it('ignores a malformed runtime config rather than throwing', () => {
    testWindow.__RUNTIME_CONFIG__ = { featureFlags: { bankerCopilot: { nope: true } } };
    expect(() => resolveFlags()).not.toThrow();
    expect(resolveFlags().bankerCopilot.source).toBe('default');
  });

  it('survives a missing runtime config entirely', () => {
    // The mounted file can fail to load; the app must still boot.
    delete testWindow.__RUNTIME_CONFIG__;
    expect(() => resolveFlags()).not.toThrow();
  });

  it('clearOverrides returns every flag to the deployment default', () => {
    testWindow.__RUNTIME_CONFIG__ = { featureFlags: { bankerCopilot: true } };
    persistOverride('bankerCopilot', false);
    ingestUrlOverrides('?ff=classicAdminTabs:off');

    clearOverrides();

    const resolved = resolveFlags();
    expect(resolved.bankerCopilot.value).toBe(true);
    expect(resolved.bankerCopilot.source).toBe('runtimeConfig');
    expect(resolved.classicAdminTabs.source).toBe('default');
  });

  it('derives the CRA env var name for each flag', () => {
    expect(envVarNameFor('bankerCopilot')).toBe('REACT_APP_FF_BANKER_COPILOT');
    expect(envVarNameFor('classicAdminTabs')).toBe('REACT_APP_FF_CLASSIC_ADMIN_TABS');
  });

  it('records a planned default change for every surface flag', () => {
    // The deferred default change is the decision most likely to be forgotten,
    // so it is asserted rather than merely commented.
    for (const definition of Object.values(FLAG_DEFINITIONS)) {
      if (definition.gatesSurface) {
        expect(definition.plannedDefaultChange).toBeDefined();
      }
    }
  });
});
