# Decision: the supervisor's independence is structural, not instructed

**Author:** Turk (Backend Dev)
**Date:** 2026-09-05
**Branch:** `squad/332-phase3-supervisor`
**Status:** proposed — needs Danny to ratify the "single-parameter builder is the control" framing

## The ruling

The L2 independent second opinion is made independent by **what the supervisor agent is handed**,
not by what it is told. The builder that assembles the supervisor's input takes **exactly one
parameter — the banker's `BankerIntent`** — and there is no parameter, field, or channel through
which the proposing agent's reasoning, plan, or conclusion can travel. Independence is therefore a
property of the type signature, provable by inspection, rather than a discipline the prompt asks
the model to observe.

Concretely, in `src/banker-copilot-service/app/planner/fanout.py`:

- `build_supervisor_input(intent: BankerIntent) -> SupervisorInput` — single param. Calling it
  with a second argument (the primary output) is a `TypeError`, not a code smell. That is the
  control, and it is enforced by Python's own call machinery.
- The supervisor re-derives from the **same underlying facts** by re-running the evidence tools
  with arguments bound from the banker's raw inputs (payload / facts / context) — never from the
  primary agent's evidence cache. A genuine second draw, not a re-reading of the first.
- Agreement between the two opinions is computed **only after both are in hand**; neither result
  is visible to the other while it is being formed.

## Why not "please ignore the above"

Because an instruction to ignore context is satisfied by a model that read the context and then
claims it ignored it, and you cannot tell the difference from the outside. A second opinion that
*could* see the first is not independent even if it swears it looked away. The only version of
this that survives an adversary is the one where the first opinion is **not in the room** — so the
data handed to the supervisor simply does not contain it.

## How it's proven (and how I tried to fool it)

Two complementary tests over the PRODUCTION builder, in
`src/banker-copilot-service/tests/test_supervisor_blind_construction.py`:

1. **Structural** — `builder_accepts_only_intent()` asserts the single-parameter signature and
   that passing a primary result raises `TypeError`. This is the load-bearing test; it cannot pass
   vacuously because it exercises the real call.
2. **Token-scan cross-check** — `independence_report` scans everything the supervisor was handed
   for tokens that appear only in the primary's narrative. This is a *belt* over the structural
   *braces*. It must run over a **non-empty** corpus or it proves nothing, so the fixture seeds the
   primary output with distinctive tokens (`QURKLE9`, `approve-immediately`) that the banker's own
   framing never uses. I learned this the hard way: an earlier fixture let the primary and the
   intent share ordinary words like "wire", and the scan reported a false leak. The lesson is
   recorded in my history — a token-scan is only as honest as the distinctness of its corpus.

**Tamper record:** I widened the builder to accept `build_supervisor_input(intent, primary)` and
threaded `primary` into the returned input. `builder_accepts_only_intent` failed immediately on the
signature assertion, and the token-scan test then failed on the leaked tokens. Reverted; both green.
Two independent guards each caught the same break, which is what I wanted — the structural test is
the one that must never be removed, the scan is insurance.

## Boundary I did not cross

`banker-copilot-service` still registers **zero write tools**; the fan-out engine spawns a
read-only supervisor sub-agent and cannot propose or execute anything. The harness still boots
`readTools: N, writeTools: 0`, and the test that asserts it is untouched. The supervisor produces
an *opinion*; the human co-signature and the `authority-service` executor remain the only path to a
state change.
