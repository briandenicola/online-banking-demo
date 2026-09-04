# Orchestration Log: basher-foundry-kwarg

**Timestamp:** 2026-05-14T02:03:23Z  
**Agent:** Basher  
**Model:** opus-4.7  
**Duration:** 1396s (completed)

## Task
RCA + worker fix for #137 (FoundryAgent model kwarg).

## Outcome
✅ **COMPLETED**

- Identified two compounding bugs in FoundryAgent calls across account-opening-service
- Fixed by passing `model` via `default_options={"extra_body": {"model": ...}}` instead of direct kwarg
- Added `TestFoundryAgentSignatureContract` to catch signature drift on future SDK pins
- Commits: d120834 + e83b50d
- Artifacts: `.squad/decisions/inbox/basher-foundry-kwarg-rca.md`

## Documentation Updated
- `.squad/agents/basher/history.md` — appended entry
- `.squad/skills/foundry-eval-debugging/SKILL.md` — added Rung 7 (signature contract test)

## Status for Hand-Off
Ready for merge. No follow-up work scoped here; ai-service follow-up recommended but out of scope.
