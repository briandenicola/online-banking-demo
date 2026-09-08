# Mutation testing: repaired, and what it immediately found

**Author:** Coordinator
**Status:** Ratified
**Scope:** `.github/workflows/mutation-testing.yml`, `src/banker-copilot-service`

## Context

We chose mutation testing over coverage metrics deliberately: coverage says a line ran,
mutation says a line is *defended*. The nightly job had been failing on `main` for at least
three consecutive nights. Only the Python half was red; the .NET Stryker job was fine.

## Why it was broken

Three independent faults, each invisible on its own:

1. **mutmut was installed unpinned**, so the 3.x release arrived silently and broke a 2.x
   invocation. `--paths-to-mutate`, `--tests-dir` and `--no-progress` no longer exist in 3.x,
   and configuration moved into `[tool.mutmut]` — which mutmut reads at *import* time, so no
   CLI flag can compensate for its absence.
2. **`mutmut run … || true`** masked the failure. A mutmut that never started looked exactly
   like a run with nothing to report. This is the same fail-open shape we have been finding
   all epic: the absent case reading as the good case.
3. **Fixed-depth repo-root resolution.** `tests/conftest.py` computed
   `REPO_ROOT = SERVICE_ROOT.parents[1]`, and two more test modules restated it as
   `parents[3]`. mutmut 3.x copies the service into a `mutants/` sandbox one level deeper, so
   every one of those resolved to `src/` and the shared fixtures vanished.

## Decisions

- **Pin `mutmut==3.7.0`.** An unpinned test-quality tool can degrade silently, and a
  degraded assertion tool is worse than none because it still reports.
- **Remove `|| true`.** Verified empirically that `mutmut run` exits **0 with surviving
  mutants** and non-zero only when it cannot run. So the job now fails for exactly one
  reason: mutation testing did not happen. Survivors are reported, not fatal — a job that is
  permanently red is as uninformative as one that is permanently green.
- **Resolve the repo root by walking up for markers** (`config/copilot-tools.yaml` + `src/`),
  raising if not found. Absent root is a hard error: these suites assert against the real
  shipped manifests, and silently falling back to a fixture is how a suite starts agreeing
  with itself.
- **Import the root, don't restate it.** The two duplicate `parents[3]` copies now import
  from `conftest`. A repo root stated three times is a repo root wrong twice.
- **`source_paths = ["app"]` with `only_mutate = ["app/tools/*"]`.** Copying only
  `app/tools` made the sandbox unimportable; widening the *mutation* target instead would
  have buried the signal in noise from unrelated modules.

## What the first real run found

873 mutants, 517 killed, 356 survived. Classifying the survivors mattered more than the
ratio: **184 were error-message string mutations** (mutmut mutates string literals
prolifically; these carry no security meaning) and 172 were logic. Most of the logic
survivors were error-*code* arguments rather than guard conditions.

One was real, and serious:

> `_confine_to_one_segment` in `app/tools/executor.py` rejects control characters via
> `ord(ch) < 0x20 or ord(ch) == 0x7F`. Changing that `or` to `and` makes the condition
> **unsatisfiable** — control characters are no longer rejected at all — and the full suite
> stayed green (177 passed).

Confirmed by tampering the real source, not just trusting the mutant. Path parameters are
model-controlled and reachable by prompt injection; a newline reaching a URL is
request-splitting territory. The guard was correct and completely unheld.

Pinned with tests that isolate each half of the `or`, per the standing rule that a guard
defended only in aggregate erodes silently. The diagonal:

| Tamper | Result |
|---|---|
| drop the `< 0x20` half | **5 red** (newline, CR, tab, NUL, unit-separator), DEL test green |
| drop the `== 0x7F` half | **1 red** (DEL), C0 tests green |
| restored | 34 green |

Added a positive control (`a b` → `a%20b`) so that over-tightening the boundary to `<= 0x20`
cannot masquerade as a correct guard.

## An equivalent mutant, recorded so nobody chases it

`return quote(raw, safe="")` → `quote(raw)` **survives, and correctly so.** The default
`safe="/"` differs from `safe=""` on exactly one character, and a raw `/` is already refused
several lines earlier by `_SEGMENT_BREAKERS`. No input distinguishes the two, so no honest
test can pin it. It stays as defence-in-depth for a future edit that relaxes the earlier
check. Writing a test that appeared to cover it would have been a false pass.

## Consequence

`mutants/`, `.mutmut-cache` and `mutmut-results.xml` are gitignored as build artifacts of a
test run. Python suite: 177 → **184**.
