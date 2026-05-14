# Ceremonies

> Team meetings that happen before or after work. Each squad configures their own.

## Design Review

| Field | Value |
|-------|-------|
| **Trigger** | auto |
| **When** | before |
| **Condition** | multi-agent task involving 2+ agents modifying shared systems |
| **Facilitator** | lead |
| **Participants** | all-relevant |
| **Time budget** | focused |
| **Enabled** | ✅ yes |

**Agenda:**
1. Review the task and requirements
2. Agree on interfaces and contracts between components
3. Identify risks and edge cases
4. Assign action items

---

## Retrospective

| Field | Value |
|-------|-------|
| **Trigger** | auto |
| **When** | after |
| **Condition** | build failure, test failure, or reviewer rejection |
| **Facilitator** | lead |
| **Participants** | all-involved |
| **Time budget** | focused |
| **Enabled** | ✅ yes |

**Agenda:**
1. What happened? (facts only)
2. Root cause analysis
3. What should change?
4. Action items for next iteration

---

## Post-Batch Smoke

| Field | Value |
|-------|-------|
| **Trigger** | auto |
| **When** | after |
| **Condition** | batch closed ≥2 issues AND any issue touched UI, shared module, or a service consumed by another agent's recent work |
| **Facilitator** | lead (Danny) |
| **Participants** | lead only (may spawn ralph or domain agent if regression found) |
| **Time budget** | focused (~2-3 min) |
| **Enabled** | ✅ yes |

**Why this exists:** Agents self-verify their own deploys. That's the thin spot — author bias means broader regressions hiding behind a "fix" don't get caught until the user reports them (e.g., #119/#120 looked green to Linus but the Account regression was sitting right next to it). Lead runs an independent smoke pass before the batch is "done."

**Agenda:**
1. **Identify blast radius.** From the closed issues, list the user journeys most likely impacted (e.g., #127 + #129 → "Account Opening end-to-end + dashboard tile read").
2. **Run the journey end-to-end on cluster.** Use `CUSTOM_DOMAIN` from root `.env` (currently `onlinebankingdemo.bjdazure.tech`) — never localhost. Real auth, real data path. No `kubectl patch`, no local overrides.
3. **Compare against pre-batch baseline.** If a tile/page worked before the batch and doesn't now, that's a regression — file a fresh issue immediately, do NOT amend the closed one.
4. **Verdict.** One of:
   - ✅ **Clean** — log to `.squad/decisions/inbox/lead-smoke-{timestamp}.md`, batch is done.
   - ⚠️ **Regression found** — file new issue with `squad,bug` labels, route to the right agent, ceremony cost is paid (it caught the bug it was designed to catch).
   - 🚧 **Smoke blocked** (auth broken, deploy not ready, etc.) — escalate to user, do NOT mark batch done.

**Out of scope:**
- Re-reviewing the code that was just merged (that's the author + reviewer's job).
- Performance regressions (separate ceremony if/when we add one).
- Anything not on the affected user journey — Lead is not running the full app smoke every batch, just the slice the batch touched.

**Cost:** ~1 sonnet-tier spawn per qualifying batch (~30s wall). Skip when batch is single-issue or touches only docs/infra-only changes.
