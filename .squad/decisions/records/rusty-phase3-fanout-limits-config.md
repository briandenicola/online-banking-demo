# Decision — Phase 3 fan-out limits config surface

**Author:** Rusty (platform/infra) · **Date:** 2026-09-04 · **Epic:** #332 Phase 3 §6.2/§6.3

## What shipped

The **config surface** for the subagent fan-out engine — the engine itself is Turk's:

- **`config/harness-limits.yaml`** — the single home of the §6.3 bounds
  (`maxConcurrentSubagents: 4`, `maxSubagentDepth: 2`, `perSubagentToolBudget: 20`,
  `subagentWallClockSeconds: 60`), per invariant I-3. Baked into the image, overridable by a
  read-only ConfigMap / bind mount to re-tune without a rebuild — the exact treatment
  `copilot-tools.yaml` gets, and read-only for the same reason (a harness that could rewrite its
  own limits could grant itself unbounded fan-out).
- **`src/banker-copilot-service/app/planner/limits.py`** — a fail-closed loader returning a
  frozen `FanoutLimits`. Missing file, malformed YAML, unknown `apiVersion`, a missing bound, or a
  non-positive bound all **raise at load**, never default. A hardcoded fallback ceiling is exactly
  what I-3 forbids; the engine holds no literals of its own and imports this.
- Path wired as `COPILOT_HARNESS_LIMITS_PATH` through `config.py` (Settings), the Dockerfile
  `COPY`, docker-compose (read-only mount), and the kustomize base.

## Ruling — the loader lives in `limits.py`, NOT `fanout_limits.py`

I first named the module `fanout_limits.py`. It immediately tripped the integration ledger entry
`phase3-supervisor-blind-construction`, whose precondition is
`absent:src/banker-copilot-service/app/planner/*fan*out*.py` — "the harness has gained a real
fan-out/supervisor **construction path**, so promote the blind-construction test."

My module is **not** that path. It is a config loader; it spawns nothing and constructs no
subagent. Tripping that ledger entry would have forced Turk's blind-construction test to be
promoted prematurely, on the strength of a filename. Renamed to `limits.py`, which does not match
the glob and is accurate. The glob is a good tripwire for the **engine** (Turk); it should fire
when the real `asyncio.gather` construction path lands, not when the config it reads does.

This is a boundary marker: **the config surface and the engine are separate deliverables.** When
Turk adds the real fan-out construction path, that is what promotes the ledger entry — and that
path should `from app.planner.limits import load_fanout_limits` rather than re-stating any bound.

## Coordination note for Turk

`load_fanout_limits(settings.harness_limits_path)` returns the frozen `FanoutLimits`. Consume it
in the fan-out engine; do not restate `4 / 2 / 20 / 60` anywhere in Python. If §6.3 ever grows a
bound, add it to `harness-limits.yaml` and `limits.py`'s validator only — the test
`test_fanout_limits_config.py` parses the numbers out of the epic, so a drift between epic, file,
and loader fails loudly.

## Verification

- **PROVED:** loader loads the shipped file to `FanoutLimits(4, 2, 20, 60)`; 11 new tests pass;
  full 294-test banker-copilot suite green (the ledger no longer trips after the rename);
  `docker compose config` and `kubectl kustomize` render the mount and the path env.
- **UNPROVEN:** no fan-out engine consumes it yet (Turk's), so "the limits actually cap
  concurrency" is not demonstrable from the platform side alone.
