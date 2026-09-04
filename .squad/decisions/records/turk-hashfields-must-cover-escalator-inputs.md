---
date: 2026-09-04
author: Turk (Backend)
status: proposed
component: authority-service, policy schema
issue: 332
---

# Every field an escalator reads must be in `hashFields` — and the loader should enforce it

## The bug I shipped and the test caught

`transaction.flag.review` was declared as:

```yaml
hashFields: [transactionId, decision, note]
moneyFields: []
```

`amount` is not there. `amount` is also **the field the L2 escalator reads** — it is what turns a
one-signature review into a two-signature one.

So the signature bound the transaction id, the decision and the note, and did **not** bind the
number that decided how many humans were required. An attacker — or an agent re-planning, or a
plain race — could change 100.00 to 250,000.00 after signing and the signature would still
verify. The approval would say "L1, one signer, reviewed and approved" about a quarter-million
dollars.

I found it only because a tampering test refused to fail. Reading the policy file would not have
found it: both lists are individually plausible, and the defect is in the *relationship* between
two lists that sit forty lines apart.

## The fix, and the bigger fix

I fixed the file. That is the small half.

**The real fix is that the policy loader should reject this at startup.** The invariant is
mechanical and total:

> For every action, every `field` path referenced by any rule or global escalator that could
> apply to that action must appear in that action's `hashFields`.

The loader already walks every predicate to enforce the no-magic-numbers rule, so it has the
field paths in hand. This is a cross-check over data it already has, and it converts a class of
silent authorisation bypass into a crash loop.

I have **not** implemented it yet, because it needs a decision I should not take alone:

1. **Global escalators read `context.*` and `actor.*` paths** (time of day, IP, self-dealing)
   which are not payload fields and must be exempt. The rule is really "every `payload.*` path
   read by anything that can raise this action's rung". `facts.*` is the awkward middle — facts
   are caller-supplied and currently unhashed, which is arguably its own hole.
2. It will **fail some existing action definitions**, which is the point, but it means the check
   cannot be added silently in the same change that adds it.

## Ask

Danny: ratify the invariant and the treatment of `facts.*`. If facts are load-bearing for a rung
and unhashed, a caller can restate the facts at execution time and change the answer — I think
`facts` needs to be in the hash input too, but that widens what a signature covers and I would
rather have that ruled on than assume it.

I will implement whichever way it is ruled. Until then the invariant holds by review only, which
is exactly the state that produced the bug.
