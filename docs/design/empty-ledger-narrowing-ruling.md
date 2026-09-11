# Ruling — the §B2.2 narrowing, the empty ledger, and a falsified cost claim

**Author:** Danny (Lead/Architect) · **Date:** 2026-09-09 · **Branch:** `332-beta`
**Status:** RULED. Blocking Brian's reseed. Hand-off: **Rusty** (implements, `scripts/demo/demo.sh`),
**Turk** (comment/blast-radius wording only, no redeploy).
**Amends** `banker-customer-read-ruling.md` §B2 by confirming the narrowing Turk shipped in `9a346e3`
and correcting the record on its cost. Supersedes nothing.

**Inputs read:** `src/transaction-service/Controllers/TransactionsController.cs`,
`scripts/demo/demo.sh` (lines 380–420, 610–660, 1250–1285), `config/demo-dataset.json`,
`config/copilot-tools.yaml`, `src/shared/Contracts/Models/Transaction.cs`,
`src/banker-copilot-service/app/tools/{executor,propose}.py`.
No deploy, no `kubectl`, no `az`, no commit. Nothing implemented.

---

## §E0 — The ruling in one line, then the physical next step

**The narrowing stands. The seeder is the thing that is wrong: it asks a question it cannot prove
entitlement to. Four call sites move from `GET /api/transactions/account/{id}` to
`GET /api/transactions/my` filtered on `accountId` — the caller asking "what have *I* posted",
which its own token proves.**

**Physical next step for Brian: none of this needs a transaction-service redeploy.** The fix is
entirely in `scripts/demo/demo.sh`, which is read from disk at run time. Rusty edits it; Brian
re-runs `task cloud:demo:reset -- --reseed`. The four pods deployed at 20:26Z stay exactly as they
are.

1. **Narrowing stands, unamended in behaviour.** A non-privileged caller's entitlement here is
   derived from returned rows and there is nothing else in this service to derive it from. Zero
   rows prove nothing. `403` is right. §E1
2. **`200 []` to a non-privileged caller is refused.** It would rebuild §B2.2's defect one field
   over. §E1.1
3. **Rejected: transaction-service calls account-service.** Architecturally cleaner, and not worth
   a new synchronous service-to-service hop on a read path in a demo. §E2
4. **Rejected: the seeder borrows the banker token.** That is lesson 44 in a different file. §E3
5. **Accepted: the seeder uses `/api/transactions/my`.** Not data-shaping — entitlement-by-token.
   §E4
6. **Three counts change meaning and must be relabelled, not quietly swapped.** §E5
7. **The cost claim was falsified. The rule that replaces it names the search roots.** §E6

---

## §E1 — The narrowing stands

Turk's reasoning is correct and I am not disturbing it.

`transaction-service` does not own accounts. For a caller holding neither `banker` nor
`supervisor`, the only available evidence of entitlement is the rows themselves. An empty result
carries no such evidence. It is therefore **not** the §B2 table's "permitted and empty" row — it is
"entitlement unknown", and unknown errs closed.

This is the same architectural gap the §B3.2 startup guard already concedes, wearing a second
costume. §B3.2 says the service cannot distinguish *no such account* from *clean history*. Here it
cannot distinguish *not your account* from *your account, no history*. One gap, two symptoms. The
guard stays as-is and is not reopened by this ruling.

### §E1.1 Why `200 []` is refused

An empty array returned to a caller whose entitlement was never established is a true-looking
answer produced by an accident of the query. That sentence is the whole of §B2.2. I will not
re-ship it in a narrower window and call it a courtesy.

### §E1.2 Does the defect make the demo FAIL or LIE?

It makes it **FAIL** — loudly, at seed time, with a `403` and an exit status. That is the good kind
of defect: it stopped the run and named itself. Every candidate fix below is judged on whether it
keeps that property.

### §E1.3 The empty account is unaffected

`config/demo-dataset.json` carries Dana's Savings account, `initialBalance: 0`, labelled *"opened,
never used — deliberately empty"*, preserved because Livingston measured the model reasoning over
real ledger contents. The copilot reads it through `list_account_transactions`
(`config/copilot-tools.yaml:126`), executing with the **invoking banker's bearer token**
(`app/tools/executor.py`), which holds `CustomerFinancialRead`. It gets `200 []`. **The model path
is unaffected by the narrowing.** The empty account remains readable, remains empty, and remains
in the measurement.

---

## §E2 — Rejected: transaction-service asks account-service who owns the account

This is the architecturally correct answer. It puts the ownership question to the service that owns
it, closes the gap rather than routing around it, and would let the §B2 table be implemented in
full.

Rejected for this demo, on "smallest measured change" and "do not overengineer a demo":

- It adds a synchronous cross-service call on a read path that the copilot exercises repeatedly
  under a latency budget the harness already measures.
- It introduces a failure mode — account-service unreachable — that must then be given its own
  honest answer, because `503` and `403` are different facts and this repo has already paid for
  collapsing two facts into one status. That is a second ruling's worth of work.
- It changes the deployed image, and therefore blocks Brian behind a build and a rollout for a
  defect whose entire blast radius is one shell script.

**The evidence that the caller-side fix is sufficient is already in the seeder:**
`resolve_account_refs` (line ~617) probes `GET /api/accounts/{id}` with each customer token until
one returns `200`. The ownership fact is already reachable from the caller, without a new hop.

Ticketed as the real-system note, deferred. If this repo ever grows a second non-privileged caller
of this endpoint, that is the trigger to build it.

---

## §E3 — Rejected: the seeder pre-reads with the banker token

Cheapest to write, and wrong. Rusty's lesson 44 bites exactly here: *when data has to be shaped so
a defect does not show, the workaround has become the design, and it stays invisible precisely
because it makes everything pass.*

Borrowing a banker token to perform a customer's idempotency check is privilege-borrowing to dodge
a check. It would make the seed pass while leaving the seeder permanently unable to describe what
a customer can actually do — and the next person to read `seed_transactions()` would conclude,
falsely, that seeding requires banker authority.

---

## §E4 — Accepted: the seeder asks the question it can prove

`GET /api/transactions/my` returns `GetUserTransactionsAsync(userId)` — the caller's own rows,
across accounts, each carrying `AccountId` (`src/shared/Contracts/Models/Transaction.cs:11`).
Filter client-side on the account id.

**Why this is not §E3 in disguise, stated once so nobody relitigates it:** borrowing the banker
token dodges the entitlement check by acquiring authority the caller does not have. `/my` does the
opposite — it asks a question whose entitlement the caller's own token *is*. The seeder wants to
know "have I already posted this?" and "how many rows have I put on this account?". Both are
questions about the caller's own rows. It was only ever asking them through an account-scoped
endpoint by habit.

**Why it is not §B2.2's defect returning, either:** §B2.2's defect was presenting *caller-narrowed
rows* as *the account's ledger*, at the API boundary, to anyone. Here the caller-narrowed rows are
labelled as caller-narrowed rows, in the caller, for the caller's own bookkeeping. The lie was
never the narrowing; it was the label.

### §E4.1 The four call sites — Rusty implements

**Filter on `(.accountId // .AccountId)`, both cases**, matching the house pattern already used
throughout `demo.sh` (`(.id // .Id)`, `(.amount // .Amount)`, `(.description // .Description)`).
A bare `accountId` against a PascalCase body matches zero rows, so the idempotency check reports
"not yet posted" on every run and the seed double-posts — a failure that *passes*. That is the one
way this fix can fail quietly and the casing guard is what removes it.

| Line | Function | Purpose | Change |
|---|---|---|---|
| ~401 | `seed_transactions` | already-posted idempotency check | `/my`, filter `(.accountId // .AccountId) == $a`, then match on `(.description // .Description)` as today |
| ~627 | `resolve_account_refs` | `<prefix>TransactionCount` evidence ref | `/my` with the owner token already resolved at line ~617, filter on `(.accountId // .AccountId)` and count |
| ~642 | `build_unscored_fallback_refs` | fallback transaction, largest absolute amount | `/my`, filter on `(.accountId // .AccountId)`, then sort as today |
| ~1271 | verify pass | per-account transaction count in the status table | `/my`, filter and count; **and change the printed label to `%s owner's transaction(s)`** — see §E5 |

Fetch `/my` **once per owner** and reuse it across that owner's accounts. Four call sites, one read
per identity, fewer HTTP calls than today.

---

## §E5 — Three counts change meaning; say so on the surface

This is the condition on §E4 and it is not optional. Each of these was "the account's transactions"
and becomes "the owner's transactions on that account".

- **`<prefix>TransactionCount` (lines ~627, ~642)** is an evidence reference the model reads.
  It must be produced knowing it counts the owner's rows.
- **The verify pass (line ~1271)** prints a per-account count. Its header must read
  **"owner's transaction(s)"**, not "transaction(s)". A verification pass that quietly changes what
  it counts is the single worst place in this repo for an unlabelled meaning change — it is the
  thing everything else is checked against.

**The assumption that makes the two equal, stated rather than assumed:** every account in
`config/demo-dataset.json` has exactly one `owner`, and `Account.UserId` is single-valued. Under
single ownership, the owner's rows on an account *are* the account's ledger. If this repo ever
grows joint accounts, these three counts become under-counts and this paragraph is the ticket.

---

## §E6 — The cost claim was falsified; here is the rule that replaces it

**On the record:** Turk shipped the §B2.2 narrowing on the explicit claim that *"it costs no
shipping caller — the copilot always holds `banker`, and no other caller in the repo uses this
endpoint."* **That claim was false.** `scripts/demo/demo.sh` calls the endpoint at four sites
(~401, ~627, ~642, ~1271), every one with a customer token. The search behind the claim covered
`src/` and was reported as covering the repo.

What the claim got right, and it matters: there is no `ui-app` caller and no other service caller.
**The narrowing costs no product caller.** That is what makes it survivable, and it is why the
ruling in §E1 is "stands" rather than "reverted". Turk's judgement about the *shape* of the
authorization was correct; his statement about its *reach* was not.

### §E6.1 The rule, mechanical rather than exhortative

Any change that narrows an existing response — a status that was a success becoming a `4xx`, a
field that was populated becoming absent, a route that answered becoming one that refuses — must
state its blast radius as **the search that produced it**: the pattern, and the roots. The roots
are, at minimum:

```
src/  scripts/  tests/  config/  infra/  .github/  Taskfile.yml
```

"I searched the repo" is not a blast radius. "`grep -rn 'transactions/account' src/ scripts/
tests/ config/` → 4 hits, listed" is. A narrowing whose cost claim does not name its search does
not pass this gate, and a narrowing whose cost claim is later falsified reopens the narrowing
itself — as this one did, which is why this document exists rather than a coordinator patch.

### §E6.2 Turk's one change here

Correct the comment block in `GetAccountTransactions` so it no longer asserts the falsified claim.
Replace *"it costs no shipping caller — the copilot always holds `banker`, and no other caller in
the repo uses this endpoint"* with the true and narrower statement: the copilot always holds
`banker`; there is **no product caller** — no `ui-app`, no other service; the repo's non-privileged
callers are the four in `scripts/demo/demo.sh`, which read their own rows via `/api/transactions/my`.

**This is a comment change. It does not gate the reseed and must not trigger a redeploy on its own.**
It rides the next image.

---

## §E7 — Answers, in the order asked

**(a) Does the narrowing stand?** **Stands.** Behaviour unchanged. A non-privileged owner reading
their own empty ledger continues to receive `403`, because in this service zero rows are
indistinguishable from no entitlement, and I will not make an unprovable answer look like a fact.
The `200 []` case remains reserved for callers holding `CustomerFinancialRead`, whose entitlement
comes from the token rather than from the rows.

**(b) Who changes what?** **Rusty** — `scripts/demo/demo.sh`, four call sites to
`/api/transactions/my`, one fetch per owner, plus the verify-pass relabel in §E5. **Turk** — the
comment correction in §E6.2, comment only, no behaviour. **Nobody** changes transaction-service
behaviour.

**(c) Redeploy?** **No.** No transaction-service redeploy, no image rebuild, no rollout. The
running pods are correct. Brian reseeds as soon as Rusty's script edit lands.

**(d) The falsified cost claim.** Recorded in §E6, with the replacement rule in §E6.1: a
narrowing's cost claim must name the search that produced it and the roots it covered, and
searching `src/` is not searching the repo.
