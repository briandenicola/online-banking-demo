# Auditing a "blind" agent's persisted trace

**When to reach for this:** a system claims one agent forms an opinion *independently* of another
(second opinion, adversarial review, blind grading, dual control), and you need to decide whether
the shared audit record breaks that claim.

## The trap

Blindness is enforced at spawn time (a narrow input type, a one-parameter builder). But the audit
record almost always combines both parties into ONE persisted document, because a reviewer needs
both positions side by side. Read cold, that document looks like exactly the leak the design
forbids — and people either panic-refactor it or wave it away. Both are wrong.

## The three questions that settle it

Ask these in order. The answer is only "no leak" if all three hold.

1. **Ordering.** Is the combined document assembled *strictly after* both opinions exist? Find the
   `await` on the second party's work and confirm the combining code is below it. This is the
   entire defence — everything else follows from it.
2. **Read-back.** Could the blind party ever *read* that document? Check three things, not one:
   - what objects it is constructed with (does it hold the approval / stream / sink?),
   - what the tool manifest declares — **is there any tool that reads a trace or an audit store?**
   - whether a *repeat* invocation could see the previous run's combined record.
3. **Readership.** Who can `GET` the trace? The fullest record of a run is usually the most
   sensitive object in the system and the least-tested route in the codebase.

If 1–3 hold, the combined record is a **post-hoc audit artifact**, not a leak. Say so, write the
posture statement, and do not build machinery. An audit record that cannot show both positions side
by side fails at its only job.

## What to do instead of refactoring

Ordering held only by statement order inside one function **is not held**. Convert the three facts
into three tests:

```
seq(any frame holding BOTH opinions) > seq(second party's own verdict frame)
the blind party's OWN trace document contains nothing authored by the first party
only the owner can read the trace   # 404, not 403 — existence is not the caller's business
```

## Two gaps this reliably finds

Both were live in a real codebase behind a fully green suite:

- **The subagent's own child trace is scanned by nobody.** Every sentinel scan reads the *parent*
  run id. A child run (`<runId>::supervisor`) is a separate document with its own partition key.
  Seeding its `run.started` with the primary's assessment — the most natural "make the trace
  readable for reviewers" edit there is — is invisible to every parent-run test.
- **The trace route's ownership check is unheld.** Deleting one `await _load_owned_session(...)`
  line left 234/234 green while making every banker's full reasoning trace world-readable to any
  authenticated peer.

## Anti-vacuity, non-negotiable

Every absence assertion needs a matching presence assertion in the same test, or it passes by
describing an empty haystack:

- the combined frame *really exists* before you assert what follows it,
- the child trace *really has* a `tool.completed` before you assert it is clean,
- the **owner really gets 200** before you assert the intruder gets 404.

## Tamper diagonal

Break each guard *alone* and confirm exactly one test goes red. A tamper that reddens six tests
tells you little (you broke a contract, not the guard); a tamper that reddens exactly the intended
one proves that guard is independently held. If a tamper reddens *nothing*, you wrote prose.

## Also worth recording

Look for the *deliberate* narrow channel and name it in the docs, so it is a known bound rather than
a later surprise. In the case that produced this skill: the blind party re-runs the same read **tool
ids** the action required, derived from the first party's evidence keys. IDs, not values, with
arguments bound from the original request. That is fine — but only because it is written down.
