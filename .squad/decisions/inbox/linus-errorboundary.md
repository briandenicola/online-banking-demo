# Decision: ErrorBoundary Architecture (Issue #92)

**Author:** Linus (Frontend Dev)
**Date:** 2026-05-12
**Status:** Implemented

## Context
No React ErrorBoundary existed in the app. Any uncaught render error caused a full white screen — unacceptable for a banking application.

## Decision
Implemented a **two-layer ErrorBoundary strategy**:

1. **Top-level boundary** in `App()` wrapping all providers and router — catches catastrophic failures (context crashes, router errors). This is the last-resort safety net.

2. **Per-route boundaries** on every authenticated page route (Dashboard, Accounts, Transactions, Transfers, Chat, Settings, Account Opening, Admin). Each boundary is section-aware and isolated — a crash in Chat won't take down Dashboard. The AppShell navigation stays alive.

## Fallback UI
- Professional, reassuring tone: "Your accounts and data are safe"
- Section-specific messaging (e.g., "unexpected issue in Dashboard")
- "Try Again" resets the error state, "Go to Dashboard" provides an escape hatch
- MUI-styled, consistent with existing banking theme

## Alternatives Considered
- **Single top-level boundary only:** Simpler but kills navigation on any page error. Rejected for a banking app.
- **react-error-boundary library:** Adds a dependency for what's ultimately ~100 lines of code. Class component is fine since ErrorBoundary requires `componentDidCatch` (no hooks equivalent).

## Files Changed
- `src/ui-app/src/components/ErrorBoundary.tsx` — new component
- `src/ui-app/src/components/__tests__/ErrorBoundary.test.tsx` — 6 tests
- `src/ui-app/src/App.tsx` — wired top-level + per-route boundaries
