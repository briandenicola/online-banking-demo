# SKILL: Runtime feature flags in a static SPA (CRA + nginx)

**When this applies:** you need a flag you can flip *without a rebuild* in an app that is compiled
to static assets and served by nginx — i.e. no server-side rendering, no runtime environment
variables, possibly no `environment:` block on the container at all.

**Symptoms you are in this situation:** the only existing config idiom is `REACT_APP_*`; the
Dockerfile is multi-stage ending in `nginx:alpine`; someone has asked to "toggle it mid-demo".

---

## 1. Use a `.js` file, not a `.json` file

```html
<!-- public/index.html — in <head>, BEFORE the bundle -->
<script src="%PUBLIC_URL%/runtime-config.js"></script>
```

```js
// public/runtime-config.js — deployments mount over this
window.__RUNTIME_CONFIG__ = { featureFlags: { myFlag: false } };
```

**Why not `fetch('/config.json')`:** it is async. Your app renders once with defaults and then
re-renders with the real config, so every page load flashes the wrong surface. For a flag whose
entire job is deciding *what the user sees*, that defect is the feature failing. A synchronous
`<script>` in `<head>` resolves before React mounts. There is no flash.

**Verify in the built artifact, not the source:** confirm `runtime-config.js` appears in
`build/index.html` ahead of `main.<hash>.js`. Build tooling reorders things.

**The file is world-readable to anonymous visitors. Never put secrets in it.** Say so in a comment
in the file itself, because the file looks exactly like a config file that would hold secrets.

**It mounts identically in both deployment modes**, which is usually why this pattern wins:

```yaml
# docker-compose
volumes: [ ./infra/local/runtime-config.js:/usr/share/nginx/html/runtime-config.js:ro ]
```
```yaml
# kubernetes — note subPath, or you replace the whole html dir
volumeMounts: [{ name: runtime-config, mountPath: /usr/share/nginx/html/runtime-config.js, subPath: runtime-config.js }]
```

Make the app work correctly **with no mount at all** (fall through to a hardcoded default). Then
the mount is an enhancement someone can add later, not a deploy-blocking prerequisite — which
matters when infra is owned by someone else.

---

## 2. Layer the sources, first match wins

| # | Layer | Scope | Use |
|---|---|---|---|
| 1 | URL `?ff=a:on,b:off` → **sessionStorage** | one tab | shareable demo links, A/B assignment |
| 2 | `localStorage` | one browser | the in-app toggle |
| 3 | `window.__RUNTIME_CONFIG__` | deployment | ops default |
| 4 | `REACT_APP_*` | image | keeps the existing idiom alive |
| 5 | hardcoded default | code | always works |

**URL → sessionStorage, toggle → localStorage.** A link someone sends you must not permanently
reconfigure their browser.

**The bug this ordering creates, and the fix:** when the user flips the in-app toggle, *clear the
sessionStorage entry first*. Otherwise a link-supplied value keeps outranking the switch they just
flipped, and the toggle appears broken with no error anywhere.

---

## 3. The CRA trap: `process.env` is textual substitution

```ts
// BROKEN in a production build. Works in `npm start`.
const value = process.env[`REACT_APP_FF_${name}`];

// Correct: static access only.
const BUILD_ENV: Record<string, string | undefined> = {
  myFlag: process.env.REACT_APP_FF_MY_FLAG,
};
```

Webpack's DefinePlugin replaces the literal text `process.env.REACT_APP_FOO` at build time. There
is no `process.env` object in the bundle, so a computed key yields `undefined` — silently, and
only in production. Any dynamic env registry in CRA needs a hardcoded map. **Comment why**, or the
verbosity gets "cleaned up" into the broken version.

---

## 4. Say "not a security control" where it will be read

A browser-sourced flag is user-controlled by definition. Put the statement in three places: a
module comment, the UI copy of any refusal screen, and the design doc.

The distinction that gets muddled: **hiding a nav item hides a nav item; refusing a route removes a
React screen. Neither removes the HTTP API behind it.** Decide explicitly whether hiding also
refuses the route, state *why*, and make the guarantee explicit rather than implied.

**Design the refusal screen to be unmistakable for an authorisation failure:** name the flag, say
in plain language that it is a display setting, and offer a one-click re-enable. An authz denial
would never hand you a button that fixes it. That asymmetry is what stops someone leaving the
screen believing the flag protected something.

---

## 5. Encode deferred default changes in the type, not in a ticket

```ts
plannedDefaultChange?: { to: boolean; when: string; rationale: string };
```

Render it in the flag admin UI and **assert it in a unit test**. "We'll flip this when X ships" is
precisely the decision that gets forgotten; three redundant reminders costs an hour and is
proportionate.

---

## Checklist

- [ ] `runtime-config.js` synchronous in `<head>`, verified in the *built* `index.html`
- [ ] App works with the file absent
- [ ] Mount snippets written for every deployment mode
- [ ] "No secrets" comment in the file
- [ ] URL → sessionStorage; toggle clears sessionStorage before writing localStorage
- [ ] No computed `process.env[...]` anywhere
- [ ] "Not a security control" in code comment + UI copy + doc
- [ ] Route-refusal decision stated explicitly, with its reason
- [ ] Deferred default changes typed, rendered, and tested
- [ ] Validated with a real production build, not just `tsc --noEmit`
