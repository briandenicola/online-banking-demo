# Linus — P2 Wave 1 Decisions

**Date:** 2026-05-12
**Branch:** `squad/p2-wave-1`
**Issues:** #95, #100, #98, #111

## D1 — Test file convention: COLOCATED (kill `__tests__/`)

**Decision.** All ui-app component tests live next to the component:
`src/components/Foo.tsx` + `src/components/Foo.test.tsx`. The
`src/components/__tests__/`, `src/pages/__tests__/`, and `src/api/__tests__/`
directories are deprecated and removed.

**Rationale.** Pairs had genuinely diverged — colocated versions matched the
real component APIs (e.g. mocking `createApplication` as the actual component
imports it), while `__tests__/` versions tested an older imagined `onSubmit`
callback API. Colocated also matches CRA defaults and most React project
templates. One orphan note: `ErrorBoundary.test.tsx` still lives in
`src/components/__tests__/` because it has no colocated dup — moving it is
a P3 cleanup, not blocking.

**Side effect.** Test count dropped 290 → 118. The removed tests were either
duplicates against the same component or tests against
`src/components/AdminApplicationsTab.tsx`, which was orphaned dead code (only
`account-opening/AdminApplicationsTab.tsx` is wired to AdminPage). Both the
dead component and its tests were removed.

## D2 — accountOpening API canonical names

**Decision.** Single canonical name per operation; legacy aliases removed.

| Operation                  | Canonical name        | Removed                          |
|----------------------------|-----------------------|----------------------------------|
| POST /applications         | `createApplication`   | `submitApplication` (wrong shape)|
| GET  /applications/{id}    | `getApplication`      | `getApplicationStatus`           |
| GET  /applications/{id}/audit | `getAuditTrail`    | `getApplicationAudit`            |
| GET  /applications         | `listApplications`    | `listApplicationsLegacy`         |
| PATCH /applications/{id}/review | `reviewApplication` | `reviewApplicationLegacy`     |

Also removed: `ReviewRequest` interface (only used by the legacy review),
`accountOpeningApi` default export.

**Rationale.** `submitApplication` was an actual bug — it wrapped the body
as `{ formData: payload }` but the FastAPI `ApplicationCreate` model expects
the flat object, so any caller would 422. The other pairs were aliases of
identical implementations. Canonical names follow the resource-noun pattern
(`createApplication`, `listApplications`) except `getAuditTrail`, which was
kept because it's the name already used in the consolidated test contract
and reads more naturally than `getApplicationAudit`.

## D3 — Admin endpoint UX for non-admin users

**Decision.** Non-admin users on `/transactions` skip the
`/admin/transactions` enrichment call entirely (guarded by `isAdmin` from
`AuthContext`). They see transactions without risk-score chips or AI
explanations.

**Rationale.** Silently catching a 403 worked but generated noise on every
load. Skipping the call is honest and removes a backend round-trip for the
common case (most users are not admin).

## D4 — Frontend error logging: central `logger` seam, not direct `console.error`

**Decision.** New module `src/ui-app/src/utils/logger.ts`. All places that
previously used `console.error` now import `logger` and call
`logger.error('msg', err)`. The logger:
- no-ops in `NODE_ENV === 'test'` (no test pollution),
- in `NODE_ENV === 'production'` no-ops for non-error levels and routes
  errors to `console.error` only in dev — in prod they're swallowed pending
  real telemetry,
- in dev passes through to the matching `console` method.

**Why not just rethrow to `ErrorBoundary`?** React `ErrorBoundary` does not
catch async errors thrown from event handlers, effects, or callbacks. A
rethrow there would have been silent in practice. The logger preserves the
error and the existing UI `setError` state surfaces it to the user.

**Future work.** When telemetry is wired (App Insights / OTEL browser SDK),
the swap is one file. No call sites change.

## D5 — `any` → `unknown` + inline type guards

**Decision.** Removed all four `any` usages flagged in #111 by replacing
with `unknown` plus an inline cast to a narrow shape, e.g.:

```ts
const serverMessage =
  (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
```

**Rationale.** Already the pattern in `AccountOpeningPage.tsx`. Avoids
pulling in axios's `isAxiosError` type guard everywhere and keeps the
narrowing local to the call site. If we later adopt `axios.isAxiosError`
project-wide, that's a follow-up sweep.

## Verification

- `cd src/ui-app && npm test -- --watchAll=false` → 11 suites, 118 tests, all green
- `cd src/ui-app && npm run build` → compiled with only pre-existing warnings (no new ones)
- 4 commits on `squad/p2-wave-1`: 6b1dec2, 1c7d6f0, 7ee344b, 08f86de
