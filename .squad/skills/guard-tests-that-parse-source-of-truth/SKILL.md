# Guard tests that parse the source of truth, then tamper-test each guard

## Problem

A fixture, seed dataset, or config file encodes assumptions about another file: an enum's allowed
values, a policy threshold, a route, a status name the UI renders. Restating those values in a test
creates a second copy that drifts silently — the test keeps passing while production breaks. Worse,
a test that never fails is indistinguishable from a test that cannot fail.

Concrete example from this repo: `scripts/seed-data.sh` posted `"checking"` and `"deposit"` for
months. Both are rejected by case-sensitive server regexes. Nothing caught it because nothing
compared the script to the DTO.

## Pattern

**1. Parse, never restate.** The test reads expected values out of the authoritative file at run
time:

- allowed enum values from the `[RegularExpression(...)]` attribute in the C# DTO
- thresholds, action ids, escalators and required evidence keys from the policy YAML
- the status buckets the UI actually renders, from the component's grouping function

If the source of truth changes, the test's expectations change with it. If a value the test needs
disappears, the *parse* fails loudly — which is itself a useful signal.

**2. Assert relationships, not values.** Don't assert `amount == 975`. Assert `amount` is derived
from the named threshold and lands on the correct side of it. The dataset stores
`{"@threshold": "...", "@delta": -25}` so the relationship is the thing being written down, and the
number is derived at run time from live config.

**3. Model the mechanism, not just the shape.** The most valuable guard here evaluates each policy
action's own rules against the seeded payload to prove no rule fires before the escalator does —
because escalators step up from whatever rung the action rules produced, and one step too many
lands on a level that is refused outright. That bug is invisible to any schema check.

**4. Keep it environment-free.** The test must run with no cluster, no Docker, no credentials —
pure file parsing. That is what makes it runnable in the one situation where you most need it: when
you are not allowed to touch the environment.

**5. Tamper-test every guard.** For each assertion: deliberately break the input, confirm that
exact assertion fails, revert, confirm a clean run passes. An untampered guard is an untested
guard. Do this at the moment you write the guard, not later.

## Worked example

`tests/demo/test-demo-dataset.sh` in this repo. Guards tamper-tested (break → FAIL → revert):
lowercase `accountType`; unknown `actionId`; removed `registerFirst`; bogus threshold name; a
literal URL injected into the script; a dropped required evidence field; a dual-control amount
pushed above the line; a removed L2 co-signature approval; an escalator amount pushed above its
action's own rule; an escalator moved onto an already-L2 action. All ten failed as intended.

## When to reach for this

- A script or dataset must agree with an enum, regex, threshold or route defined elsewhere.
- You are building something you are not permitted to execute against the real environment.
- The failure mode is "runs fine, produces subtly wrong data" rather than "crashes".

## When not to

If the two files are genuinely independent, parsing one into the other's test invents a coupling
that does not exist. Only do this where the dependency is real.
