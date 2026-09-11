# Latent capability audit — is the primitive missing, or just unexposed?

**When to use:** Someone reports a missing capability ("there's no override option", "I can't
amend this", "there's no way to retry"). Before designing it, prove it does not already exist
behind the UI. In a system with a rich domain model, the backend is frequently ahead of the
surface — and a feature you *expose* costs a fraction of a feature you *design*.

**Origin:** Epic #332 Banker Copilot, 2026-09-10. Brian reported the banker could only sign or
deny, with no override. Counter-proposal turned out to be fully implemented, reachable with the
banker's own token, and exposed by zero buttons.

---

## The tell

A **terminal state, enum member, or optional request field** that:

- exists in the schema and the type definitions,
- is asserted by unit tests and integration/demo scripts,
- is documented in the design docs,
- and has **no user-reachable path that produces it.**

That combination means the capability was built, ratified, and then not wired to a surface.
It is not dead code — dead code has no tests. It is *latent* capability.

## The method

**1. Search the write path, not the read path.**

Ask *who writes this value?* — not *who displays it?* A UI-first search finds the rendering
branch and stops, concluding "it's only ever displayed, never produced." Grep the constant
repo-wide, then discard test/fixture/mutation-output directories and read the **one or two
service-layer sites that assign it.**

```
grep -rn "SOME_TERMINAL_STATE" . | grep -v Tests | grep -v __tests__ | grep -v mutants
```

Mutation-testing output directories (`mutants/`, `.stryker/`) will dominate the results and are
pure noise. Filter them early or you will read a generated file and think it is the source.

**2. Read the guard clauses on the producing endpoint, and read them literally.**

The producing path almost always has authorisation guards. Do not paraphrase them — the exact
predicate is the whole answer. `requester_id == actor.user_id` reads like "agents only" and may
in fact mean "the human, always."

**3. Resolve the guard against real identity flow. This is the step that gets skipped.**

Whose credential actually reaches the guarded service? In agentic systems the agent very often
acts under the **user's forwarded token**, not a service principal. If so, the "requester" of an
agent-proposed record *is the human*, and human-authored guards the team believed were closed are
already open.

Trace it explicitly: `auth module → request context → outbound client → service guard`. This
crosses a language boundary (Python caller, C# guard) more often than not, which is exactly why
nobody had noticed. **A guard and the identity that satisfies it are rarely in the same file, and
almost never in the same language.**

**4. Separate "does the action exist" from "may this principal perform it".**

A flag named `agentMayPropose` sounds like a principal check and may be an *action* check —
whether the action is in the harness at all. Read its use site, not its name. Getting this
backwards is the single most likely way to wrongly conclude the capability is closed to humans.

## What to do with the finding

**Do not just ship the button.** A path that was unreachable has not been exercised against a
real principal, and the safety properties may have been reasoned about only for the intended
caller. Two checks before exposing it:

### Check A — does the new caller carry the same evidence and provenance?

If not, the risk profile changed and the authorisation requirement must change with it.
**Less evidence must mean more scrutiny, not the same.** In an authority system, that means the
provenance difference has to become an *input to the rung*, or the rung silently under-prices it.

But be ruthless about whether provenance is actually **knowable**. Ask: *is this fact derived by
the server, or asserted by the caller?* Fields named `agentId`, `sessionId` or `source` are
usually plain request-body fields — fine for display, worthless as evidence. In particular, **if
the agent calls the backend on the user's forwarded token, the backend cannot distinguish agent
from human at all**: same principal, same credential, same code path. A service with no identity
of its own can assert nothing about itself that counts as evidence.

**Design the escalation fail-closed.** A flag meaning "a human did this" is defeated by omitting
it. Instead, escalate on the **absence of positive attestation** — then defeating it requires
manufacturing evidence rather than withholding a boolean. Accept the cost: fail-closed usually
raises the requirement for the *intended* caller too. That is the honest price of a system that
cannot yet tell the callers apart, and it is preferable to a forgeable flag that looks rigorous.

### Check B — re-derive the security property with the new actor substituted in

An existing guard's rationale was written for the original caller. **A property is a claim about
(mechanism, actor), never the mechanism alone.** The same mechanism can be a defence under one
actor and an attack under another — a "replacement voids prior signatures" rule protects against
an agent smuggling an unsigned change, and enables reviewer-shopping the moment a human can drive
it. Enumerate deliberately: *who else can now reach this, and what does it buy them?*

### Check C — what makes the capability *unreachable*?

Reachability is only half the analysis, and the half everyone stops at. Having proved a user
*can* reach the latent path, ask **what closes it** — then check whether the UI funnels people
into exactly that action.

The pattern to look for is a **terminal-state guard**: latent capability X requires the record be
non-terminal, and the only verb currently exposed for the relevant intent is one that makes it
terminal. Users then destroy the remedy while hunting for it, and their bug report reads *"there's
no way to do X"* when the truth is *"there was, until you clicked the only button we gave you."*

Two questions, not one:
- Can they do X?
- Can they still do X **after doing the obvious thing first**?

When the answers differ, the ordering trap is the finding — usually more urgent than the missing
feature, and fixable before it with a sentence of warning copy.

### The cheap hook, in all cases

Look for a **live fact with no consumer** — a value the system already computes and publishes to
its rule engine that no rule currently reads. These are common in evaluators that grew a rich
context document ahead of the policies using it, and they turn a guard into a few lines of
declarative config. If the evaluator is monotone (combines with `max` only), such a rule can
raise a requirement and nothing in the grammar can lower it.

**Sequencing rule:** the guards ship in the same change as the exposure, or strictly before it.
A floor with no button is inert; a button with no floor is a live hole.

## Reporting it

Lead with what already exists, cite file and line for every claim, and state plainly what is
*genuinely* missing — usually far less than the original request implied. Mark any claim you
inherited from a colleague and did not personally verify as unverified. The seam between
confirmed and inherited costs one sentence and is the difference between a ruling and a guess.

## Anti-pattern

Designing the primitive from scratch because the UI has no button for it. You will re-invent a
mechanism that already exists, give it a second name and a second code path, and now the system
has two ways to do one thing — with only one of them covered by the tests and the audit trail.

---

## The inverse search: mandatory inputs with no reader

The audit above finds *capability* that exists and is unexposed. Run the mirror-image search too,
because it finds *model* gaps rather than surface gaps — and those are the ones users describe as
"this feels wrong" rather than "this button is missing."

**Look for a field the system demands and nothing consumes.** The signature:

- it is **mandatory**, and rejected when absent;
- it is **heavily validated** — length floors, anti-mashing rules, "X is not an acceptable value"
  — which is expensive code nobody writes by accident;
- and **every read of it is a sink**: stored, audited, logged, rendered. No branch, no decision,
  no feedback into the process that produced it.

High validation effort is the tell. It means the team believed the field mattered. If no consumer
ever acts on it, that belief was never cashed — the loop it was meant to close does not exist.

Trace it explicitly: *who reads this, and does any reader change what the system does next?*
Beware direction — an event named for the field is usually **outbound** (notifying a UI), not the
system consuming its own signal. Confirm with an unfiltered repo-wide search, and be careful with
grep filters: `grep -v "^.*#"` drops every line containing `#`, which will silently hide most of
a Python codebase and hand you a false negative on exactly the claim you are about to build on.

**Why this outranks the feature that was asked for.** A discarded human input is usually the
*better* primitive hiding behind the requested one. When a user asks to author the thing the
system produced, routing their existing rejection reason back as a **constraint** often serves
them better: they direct rather than originate, the system regenerates with its own supporting
work intact, and you avoid creating an origination surface with no evidence behind it.

**Ask:** *does the system compel people to articulate something it then refuses to listen to?*
That is not a missing button. That is a missing conversation, and it is worth naming as such —
users experience it as being managed rather than served, long before they can say why.

**Label it honestly in the recommendation.** Unlike latent capability, closing this loop is **new
design**. Keep it in a separate tier from the "already built, just expose it" work, or the
expensive item silently absorbs the cheap one and neither ships.

---

## Before you recommend declarative config: run it against every input state

Rulings that land as YAML rules, policy predicates or config thresholds get less scrutiny than
code, because they read like prose. They are code. Evaluate any rule you propose **by hand,
against every input state the system can present** — not just the one that motivated it.

The failure that generalises: **in a ladder whose top value means "refuse," a "step up by one"
operator and a "require more" operator are not the same thing.** `raiseBy: 1` on a mid-ladder item
adds scrutiny; on a top-adjacent item it exits the system entirely. A rule written to add a
reviewer silently became a rule that forbids the action. The prose said *floor*; the config said
*step*; only the config runs.

Practical guard:

- Write the truth table. For a three-value ladder that is three lines. Do it even when — 
  **especially** when — the rule feels obvious.
- Distinguish **floor** semantics (`max(current, X)`) from **increment** semantics
  (`current + n`). They coincide on exactly the input you were thinking about and diverge
  everywhere else.
- Check the top and bottom of any ordered domain. Saturating values usually carry a *qualitative*
  meaning ("out of scope", "refuse", "unbounded") rather than just "more".
- If a structural invariant protects you (monotonicity, clamping, fail-closed defaults), state
  **precisely which failure direction it covers** — and then keep checking the others. An
  invariant that makes one class of mistake impossible tends to stop people looking for the rest.
- Tell the implementer what *not* to write, inline, wherever the wrong version is the natural one.
  A ⚠️ comment in the recommended snippet is cheaper than the incident.

Corollary for reviewers: ask the author to state what their rule does to inputs it was **not**
written for. That question surfaces this class of defect faster than reading the rule again.
