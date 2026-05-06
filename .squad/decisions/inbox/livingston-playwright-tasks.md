# Decision: Playwright E2E Task Naming Convention

**Date:** 2026-07  
**Author:** Livingston (Tester)  
**Status:** Implemented

## Context
Added Taskfile tasks for running Playwright E2E tests by phase and mode.

## Decision
- All E2E tasks live in `Taskfile.e2e.yml`, included under `e2e:` namespace in root `Taskfile.yml`
- Tasks follow pattern: `task e2e:{action}` (e.g., `run`, `ui`, `headed`, `phase1`–`phase4`)
- Phase directories map: auth → phase1, core → phase2, advanced → phase3, admin-ai → phase4
- Documentation lives in `docs/testing.md`

## Rationale
- Consistent with existing `local:` and `cloud:` namespace pattern
- Phase numbering gives a clear execution order for progressive testing
- `docs/testing.md` keeps test docs alongside deployment docs
