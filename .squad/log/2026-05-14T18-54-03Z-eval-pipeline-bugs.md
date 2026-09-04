---
date: 2026-05-14T18:54:03Z
session: eval-pipeline-bugs
---

# Session Log: Evaluation Pipeline Bug Fixes

**Issues Fixed:**
1. **prompt-eval-service HttpClient timeout** (keaton) — Changed from default 100s to 10min for Foundry calls
2. **ai-service EvalResults.total accessor** (fenster) — Fixed TypeError from `len()` call on non-collection object

**Root Cause:** Both services were not designed for long-running Foundry evaluation jobs (3-5+ minutes):
- HttpClient premature cancellation at 100s boundary
- Incorrect EvalResults API usage (len vs property accessor)

**Verification:** Services will be rebuilt and redeployed. Patterns documented for future team members.
