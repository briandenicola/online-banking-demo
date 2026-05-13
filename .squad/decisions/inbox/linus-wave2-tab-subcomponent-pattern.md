# Decision: Tab Subcomponent Composition Pattern

**Date:** 2026-05-13
**Author:** Linus
**Wave:** P2 Wave 2 (#99)
**Status:** Established

## Context

`AdminPage.tsx` is the host for 8 tabs. Earlier waves extracted the simpler tabs into focused
files (`AdminUserManagementTab`, `AdminLoginAuditTab`, `AdminFoundryStatusTab`, etc.). Wave 2
finished the job by extracting the two remaining inline panels and splitting the 661-line
`AdminEvalTab` into three sub-components.

This decision codifies the props shape and ownership boundaries so future tab/sub-tab work
follows the same shape without re-litigating.

## Decision

### Tab subcomponents owned by a parent that fetches data

Standard prop shape:

```ts
interface XxxTabProps {
  data: T[];                                   // server-state, owned by parent
  onRefresh: () => Promise<void> | void;       // re-fetch trigger
  onError: (message: string) => void;          // bubble user-facing error to parent's <Alert>
  // ...feature-specific bubble-up callbacks (e.g. onRunRequested(templateId))
}
```

**Parent owns:** server data, polling/refresh interval, top-level `<Alert>`.
**Child owns:** ephemeral UI state — sort field/direction, expanded row, dialog open state,
form field values, per-row action-loading flags. Children call `apiClient` directly for
their own write actions and report back via `onRefresh` / `onError`.

### When to add a sub-folder

Use a feature sub-folder under `components/` (e.g. `components/eval/`) when a tab decomposes
into **3+ files plus shared types**. For 1–2 files, keep them flat in `components/`.
Shared types go in `<feature>/types.ts`, never duplicated across the sub-files.

### Dialogs as their own components

Modal dialogs that own non-trivial state (form fields, multi-select) become their own
component, controlled by `{ open, onClose, onStarted }` props. The parent stays a thin
orchestrator and just toggles `open`.

## Rationale

- Mirrors the already-established earlier-wave pattern (Admin*Tab files already in
  `components/`); no new pattern invented, just made explicit.
- Keeps `useState` count per file under ~5 — the previous AdminEvalTab had 15+.
- Children are independently testable because they accept data via props instead of
  hitting `apiClient` for reads.
- The `onError(message)` callback (instead of children rendering their own `<Alert>`)
  keeps a single error surface per page and avoids stacked error banners.

## Examples in tree

- `components/FlaggedTransactionsTab.tsx`, `components/AllTransactionsTab.tsx` — flat tabs.
- `components/eval/{PromptTemplateEditor,EvaluationRunner,EvaluationResults,types}` —
  sub-folder with shared types.
- `components/AdminEvalTab.tsx` — example of a thin orchestrator (~100 lines: fetches +
  composes children + manages one inter-child dialog state).

## Non-goals

- This does **not** mandate React Context for cross-child state. For tab compositions
  this small, props are clearer than context.
- This does **not** require children to fetch their own data. Centralized fetching in
  the parent enables consistent refresh semantics (single 30s interval, single error banner).
EOF
