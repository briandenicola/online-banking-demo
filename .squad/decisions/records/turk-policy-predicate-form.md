---
date: 2026-09-04
author: Turk (Backend)
status: proposed
component: authority-service
issue: 332
---

# The policy file uses structured predicates, not the expression language I specified

## What

My design doc (§3.3) sketched escalator conditions as a small expression language —
`payload.amount >= threshold("transfer_l2_amount")`. What I built instead is a structured
predicate: an explicit `{ field, op, threshold }` object, combined by `allOf` / `anyOf` / `not`.

```yaml
when:
  allOf:
    - { field: payload.amount, op: gte, threshold: flag_review_l2_amount }
    - { field: facts.priorReversals, op: countGte, threshold: repeat_reversal_count }
```

## Why I changed it

**An expression language cannot be checked for the thing Brian actually banned.** The hard rule
is zero hardcoded thresholds. With a structured predicate I can enforce that mechanically at
load: magnitude operators (`gte`, `gt`, `lte`, `lt`, `countGte`) **must** name a threshold, and
the loader refuses to start if one carries a bare number. Equality and membership may carry
literals, and only non-numeric ones. With a free-form expression I would have to parse the
expression to find out whether `>= 5000` had been typed inline — and a parser that is one bug
away from missing a literal is a control that reports success it has not verified.

Two smaller reasons. A structured predicate is enumerable, which is what lets the property-based
monotonicity test generate random escalator subsets and prove none of them lowers a rung — you
cannot enumerate the subsets of a string. And it is what lets a fired escalator carry the
threshold *name*, *env var* and *resolved value* into the explanation, so a supervisor is told
"250,000.00 is at or above 100,000.00 (POLICY_FLAG_REVIEW_L2_AMOUNT)" rather than an echo of the
source text.

## Cost, honestly

The policy file is more verbose and less pleasant to read than the expression form, and complex
conditions nest. That is a real loss for the human reviewing the ladder, and the ladder is meant
to be reviewable. I traded readability for checkability because an unenforceable rule against
magic numbers is worth nothing, but if the verbosity becomes the reason nobody reads the policy
then I have moved the problem rather than solved it. Worth revisiting with a compact surface
syntax that compiles to the structured form.

## Ask

Ratify the structured form, or tell me the readability cost outweighs the enforcement.
