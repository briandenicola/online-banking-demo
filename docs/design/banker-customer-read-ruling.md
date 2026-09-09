# Ruling — how a banker reads a customer's account

**Author:** Danny (Lead/Architect) · **Branch:** `332-beta` · **Status:** ruled, for Turk to
implement immediately · **Supersedes nothing; complements** `gate-b-evidence-contract-ruling.md`
(§R5) and `primary-assessment-ruling.md` (§P8.1, the two-stage measurement).

---

## §B0 — The ruling in one line, then the seven points

**A banker reads a customer's account by holding the `banker` role, which is already in the token
they already carry — and every path that today answers a denial with a success stops doing so, so
that the false evidence Gate B cannot see becomes an evidence key that is simply absent.**

1. **Role-based.** `banker` or `supervisor` may read any customer account and its transactions.
   **Not `admin`** — this repo already ruled admin implies neither. §B1
2. **No new identity machinery.** The role claim is already minted, already expanded by the role
   hierarchy, already in the copilot's bearer token. Two controllers change. §B1.3
3. **Three facts, three answers.** Absent → `404`. Forbidden → `403`. Permitted and empty → `200
   []`. A `200` with an empty array becomes the *only* way to say "genuinely nothing", and it
   becomes true. §B2
4. **That is also the evidence fix, and it costs nothing extra.** A `4xx` is not projected, so the
   required evidence key is *absent*, so `EvidenceComplete` fails and the propose is rejected. The
   lie stops being checkable-but-unchecked and starts being **unrepresentable**. §B3
5. **One startup guard.** A policy that requires `list_account_transactions` without also requiring
   `get_account` **aborts startup** — because transaction-service cannot tell "no such account"
   from "no transactions" and must never be asked to. §B3.2
6. **The write side is blocked too, and Brian will hit it within ten minutes of the read fix.**
   `UpdateBalance` has the same owner check. §B4.3
7. **This lands BEFORE stage 1 is measured, not between stage 1 and stage 2.** It moves the
   accounts under test, and that is a third uncontrolled variable. §B5

**Yes, the demo narrative changes.** See §B6 — Rusty and Brian both need this before the next
demo.

---

## §B1 — How a banker legitimately reads a customer's account

### §B1.1 The ruling: role-based, and say the blast radius out loud

Any identity holding `banker` or `supervisor` may read any customer account and any customer
account's transactions. Not assignment. Not delegation. Not service identity.

**The blast radius, stated deliberately rather than discovered later:** one compromised banker
credential reads every customer's balances and transaction history. That is the actual exposure
and I am accepting it for a demo. It is accepted because the demo's subject is *the harness's
control of a banker's actions*, and inventing a customer-assignment model to sit underneath it
would add a second authorization story that the harness does not exercise, does not display, and
cannot demonstrate failing.

**`admin` is excluded.** `InMemoryUserService` and `Constants.cs` already carry the rule that
*admin implies neither banker nor supervisor* — platform authority is not banking authority. A new
constant is therefore required; do **not** reuse `BankingRoles.IdentityRead`, which includes
`Admin` because reading an identity record is a platform act and reading a customer's money is
not.

```csharp
// src/shared/Auth/BankingRoles.cs
// Reading a customer's money is BANKING authority, not platform authority. `admin` is absent
// deliberately and by precedent (§5.8.2: admin implies neither banker nor supervisor).
public const string CustomerFinancialRead = "banker,Banker,supervisor,Supervisor";
```

### §B1.2 What a real bank adds, so the demo can narrate the gap honestly

Three things, and the demo should *say* them rather than imply they are present:

1. **Relationship or assignment scoping** — a banker sees the customers in their book, and
   anything outside it is a break-glass act.
2. **Purpose-of-access** — the read is accompanied by a stated reason, and unreasoned bulk reads
   are the thing monitoring is actually looking for.
3. **Customer-visible disclosure** — the customer can see who at the bank looked at their account.

Point three is worth saying out loud during the demo, because **we are closer to it than to the
other two**: every evidence read the copilot performs is already recorded on the approval with the
tool id and the acting banker. The harness produces the audit trail that this control needs. That
is an honest claim, and it is the only one of the three I will let anyone make.

The narration line I will endorse: *"Any banker can read any account here. A real bank would scope
that to their book and demand a stated purpose. What we already have is the record of who looked
at what — which is the part that is usually missing."*

### §B1.3 The three rejected options, and why

- **Assignment-based.** Rejected: needs a banker↔customer relationship store that nothing else in
  the demo reads or writes, and its failure mode ("not your customer") is a screen nobody will see
  during the demo. Real, deferred, ticketed.
- **Delegation / consent grants.** Rejected: it is the right answer for a *customer-initiated*
  flow, and every flow in this harness is banker-initiated. It would model a journey the demo does
  not contain.
- **Service identity for the copilot, with `capabilityScope` becoming load-bearing.** Rejected,
  and this is the important one. I corrected the coordinator earlier that `capabilityScope` is
  declared metadata and enforcement is upstream by bearer token. Making it load-bearing moves the
  enforcement point **while the feature is mid-measurement**, and it breaks the property that
  makes the current design defensible: the copilot can do **exactly** what the banker who invoked
  it can do, and not one thing more. A service identity is by construction more powerful than its
  caller, and every question about the harness then becomes "yes, but what could the service
  identity have done?" Ticketed as the real-bank note, refused for now.

---

## §B2 — The 404-versus-empty asymmetry: three facts, three answers

Today two distinct facts render identically, and one of them renders as a *success*. The table is
the ruling; implement it exactly.

| Case | `GET /api/accounts/{id}` | `GET /api/transactions/account/{accountId}` |
|---|---|---|
| No such account | `404` | see §B3.2 — this endpoint may not answer it, and must not pretend to |
| Exists; caller is not the owner and holds neither `banker` nor `supervisor` | **`403`** | **`403`** |
| Exists; caller permitted; no transactions | `200` account body | **`200 []` — and this is now the only way an empty array is produced** |

### §B2.1 `403`, not `404`, for the forbidden case

Answering a denial with `404` hides account-id existence from an authenticated hostile caller.
That is a real control and I am **removing it deliberately**, because here it costs more than it
buys:

- The demo's threat model does not include an authenticated banker enumerating account ids; every
  banker in it can already read every account by §B1.
- The cost is concrete and has already been paid once: when denial and absence are the same
  answer, **nothing downstream can tell them apart** — not the copilot, not the projection, not
  the supervisor, not the human reading the card. Brian's standing test applies and answers
  itself: this defect does not make the demo fail, it makes the demo **lie**.

Enumeration hardening — a `404` at the edge with the true status in the audit log — is
**deferred-before-`main`, ticketed**. It is a five-line change *once the internals distinguish the
two facts*, and it is unimplementable until they do. Fix the distinction first; that is the part
that has architectural consequence.

### §B2.2 `GetAccountTransactions` must stop deriving the answer from the caller

This is the defect, not a symptom of it:

```csharp
var userTransactions = await _transactionService.GetUserTransactionsAsync(userId);  // the CALLER's
var accountTransactions = userTransactions.Where(t => t.AccountId == accountId);
return Ok(accountTransactions);
```

The endpoint is documented as "transactions for this account" and implemented as "the caller's
transactions, narrowed to this account". For any caller who is not the owner it returns `200 []`
*by construction, for every account in the bank*. It is not an authorization check that happens to
be lenient — **there is no authorization check at all**, and the empty result is a coincidence of
the query that reads as a fact about the world.

Required:

1. Add `GetAccountTransactionsAsync(string accountId)` to `ITransactionService` — query **by
   accountId**, not by user.
2. In the controller: caller is permitted if they hold `banker`/`supervisor`
   (`User.IsInRole(...)`, already populated from the expanded role claims) **or** they own the
   transactions returned. For the non-privileged, non-owner case return `403`.
3. Do not keep the old filter as a fallback. Delete it. A fallback here would preserve the exact
   path that produces the lie, and the standard from §P12.5 applies: *a filtered channel is a
   promise, an absent parameter is a fact.*

### §B2.3 `GetAccount` and `GetAccountByNumber`

Keep the `404` when `GetAccountByIdAsync` returns null. Change the second check — the one that
currently returns `404` because the owner does not match — to permit `banker`/`supervisor` and
otherwise return `403`. Two endpoints, same edit.

---

## §B3 — What holds this at the evidence layer

### §B3.1 §B2 *is* the structural fix. There is no new machinery.

Gate B checks shape, not truth, and I am not going to make it check truth — that is not something
a projection can do. The reason a false statement could pass it was never Gate B's weakness. It
was that **the upstream returned `200` for a denial**, so a successful response existed to project
and the projection did its job faithfully on a body that was itself the lie.

Once denial is a `4xx`:

- the tool call **fails** and is recorded as a failed read — a positive, specific fact, per the
  standing rule that a signal must never be the absence of an error;
- **no projection is built**, because there is no success to project;
- the required evidence key is **absent** from the evidence dict;
- `EvidenceComplete` fails and the propose is rejected `422`.

The lie moves from *representable and unchecked* to *unrepresentable*. This is the third time this
pattern has paid on this feature, and it is again free — the structural fix is a consequence of
naming the facts correctly at the source, not an addition on top.

**Nothing changes in `copilot-tools.yaml`.** The projection for `list_account_transactions` stays
exactly as written: `accountId: {bind: $args.accountId}`, `count: {count: $}`, `items: {collect:
$}`. It was always correct. It was being fed a lie.

### §B3.2 One new startup guard: `list_account_transactions` may not be required alone

There is a residual ambiguity that §B2 cannot close, and I want it named rather than hoped away:
**transaction-service does not own accounts.** For a permitted caller asking about an accountId
that does not exist, it will return `200 []` — indistinguishable from an account with a clean
history. Making it consult account-service to find out would add a synchronous cross-service call
on every evidence read, which is a heavier change than the defect deserves.

So the honest statement of what that endpoint returns is: *"the transactions recorded against this
accountId"*, which is silent on existence. Existence is `get_account`'s question, and `get_account`
answers it with a `404`.

Therefore, enforced at startup in the authority-policy loader, in the §R5 style:

> **Any action whose `requiredEvidence` names `list_account_transactions` must also name
> `get_account`. A policy that violates this fails to load and the service does not start.**

With that guard, a nonexistent account cannot produce a complete evidence set: `get_account` 404s,
its key is absent, `EvidenceComplete` fails, the propose is rejected. `count: 0` can then only ever
mean what it says. Write the reason in the error message — the next person to hit it needs to know
it is about a fact the transaction service cannot see, not about a preference for thoroughness.

---

## §B4 — Blast radius on what has already shipped

### §B4.1 The evidence fixtures — shape survives, provenance does not

`tests/fixtures/evidence-samples/list_account_transactions.json` carries `count: 7`. It is a
non-empty capture, so it is a capture of the endpoint **working**, not of the defect. The response
body, the projection and the resulting shape are all unchanged by this ruling, so the Gate B seam
tests remain valid and are **not blocked** by this work.

But the fixtures were captured *as banker, against a banker-owned account*, and after this ruling
that is a path the product no longer takes. A fixture captured on a path that no longer runs is
exactly the failure mode I ruled against in §P5.1 — a measurement of a configuration nobody runs.

**Regenerate both fixtures after the fix**, captured **as banker against a customer-owned
account**, because that is the shipping path. Not urgent — it does not block stage 1 — but it must
happen before `main`, and it must be a live capture, not an edit of the existing file. Ticketed.

**Additionally, capture two new fixtures that do not exist today and now can:** the `403` on a
forbidden read and the `404` on an absent account. Until this ruling those two responses were
unproducible, which is why the failed-read path has never had a fixture. It is the path §B3.1
depends on.

### §B4.2 Gate A and `capabilityScope` — unchanged, and that is the point

The token model does not change. Same bearer token, same session, same declared
`capabilityScope`, same upstream enforcement. The role claim this ruling depends on is **already
minted** by `AuthService` and already expanded by the role hierarchy, which emits implied roles as
`ClaimTypes.Role` precisely so existing guards see the expansion.

Gate A's fix holds **unchanged and unmoved**. This is the single strongest argument for the
role-based option over service identity, and it is why §B1.3 rejects the latter: service identity
would move the enforcement point out from under a control we have already measured, mid-feature,
while a two-stage measurement is in flight.

### §B4.3 The write side is blocked too — and it is the next thing Brian hits

`AccountsController.UpdateBalance` carries the same `account.UserId != userId` check and returns
`404`. So after the read fix, a banker will successfully gather evidence on Casey's account,
successfully propose the adjustment, get it approved — **and the execution will 404**. The demo
will fail one step later than it does now, which is worse than failing where it does, because by
then it looks like the harness worked.

Ruling: `UpdateBalance` accepts `banker`/`supervisor` by the same `CustomerFinancialRead` — no,
by a **separate constant with the same members**:

```csharp
// Same members as CustomerFinancialRead today. Separate because a read authority and a WRITE
// authority that happen to coincide are still two different authorities, and the day they
// diverge must be a one-line change, not an audit of every call site.
public const string CustomerFinancialWrite = "banker,Banker,supervisor,Supervisor";
```

**Say the honest limitation:** in a real bank this write would be gated on the *approval record*,
not on the role — the banker's authority to adjust a balance comes from the co-signature, not from
their job title. The harness produces exactly that record and does not yet gate on it. That is the
most interesting deferred item in this ruling and I want it ticketed with that framing:
**deferred-before-`main`: state-changing endpoints verify the approval, not the role.** It is the
seam that would make the approval load-bearing rather than advisory, and it is the natural next
epic.

### §B4.4 Livingston's 42 runs are not comparable across this change

This is the item nobody listed and it is the one that costs the most if it is missed. Check 4.2
was measured against **banker-owned accounts**, and Livingston graded every case against those
accounts' real ledgers. This ruling changes which accounts exist, who owns them, and what the
evidence surface returns. His 22.6% baseline does not survive it.

Sequencing ruling, and it is not negotiable against convenience:

> **This lands before stage 1 is measured, not between stage 1 and stage 2.**

Stage 1's entire value is that its number is attributable to exactly one change — the agent count
going from one to two. Landing an account-ownership change in between makes it attributable to
two, and I spent last night's amendment protecting precisely that property. Brian may build and
deploy stage 1 with this included; he may not measure stage 1, land this, and then compare.

---

## §B5 — Scope

**In scope now** — this is the whole list, and it is small:

1. `BankingRoles.CustomerFinancialRead` and `CustomerFinancialWrite`. (§B1.1, §B4.3)
2. `AccountsController.GetAccount` and `GetAccountByNumber`: permit the roles, `403` not `404` on
   denial. (§B2.3)
3. `AccountsController.UpdateBalance`: permit the roles. (§B4.3)
4. `TransactionsController.GetAccountTransactions`: query by accountId, authorize explicitly,
   `403` on denial, delete the caller-derived filter. (§B2.2)
5. `ITransactionService.GetAccountTransactionsAsync(accountId)`. (§B2.2)
6. Authority-policy loader: abort startup if `list_account_transactions` is required without
   `get_account`. (§B3.2)
7. Seeder: customers own the accounts and the transactions; the banker owns none. (§B6)
8. Tests: one per row of the §B2 table per endpoint, plus the startup guard, plus a test that the
   banker-owned-account shape is *gone* from the seeder rather than merely unused.

**Deferred-before-`main`, ticketed not carried:**

- Assignment/relationship scoping of a banker's readable book. (§B1.2)
- Purpose-of-access capture and break-glass. (§B1.2)
- Customer-visible read disclosure. (§B1.2)
- `404`-at-the-edge enumeration hardening, with the true status in the audit log. (§B2.1)
- **State-changing endpoints verify the approval record rather than the role.** (§B4.3)
- Service identity for the copilot with `capabilityScope` made load-bearing. (§B1.3)
- Regenerate the two live evidence fixtures against a customer-owned account; capture the new
  `403` and `404` fixtures. (§B4.1)

**Refused, not deferred:** making Gate B check truth. A projection describes a response; it cannot
know whether the response is true. Every attempt to make it try produces a check that reassures
without holding — and after §B2 there is nothing left for it to catch.

---

## §B6 — Yes, this changes the demo narrative. Rusty and Brian need this.

The data shape changes, and it changes in the direction Brian asked for:

- **Before:** the banker owns sample accounts and the demo shows a banker adjusting **their own
  balance** — which is not a banker's job and is close to the one act a bank would never permit.
  The data shape was a workaround for the defect in §B2.2, not a design.
- **After:** Casey and Dana own accounts with transaction histories. The banker owns nothing and
  works **their** cases. The copilot gathers evidence on a customer's account, and the approval
  record says which banker looked at whose money.

For Rusty: reseed so customers hold the accounts and the transactions; remove banker-owned
accounts entirely rather than leaving them unused, so nothing can quietly fall back to them.

For Brian, before the next demo: the scenario changes from *"a banker adjusts an account"* to *"a
banker adjusts a customer's account"*, and the second is the one the harness was built for. The
one sentence worth adding to the narration is §B1.2's: any banker can read any account here, a
real bank would scope that to their book, and the part we already have is the record of who looked
at what.

---

## §B7 — For the record

Every defect on this feature has been a claim the system was not entitled to make. This is the
purest instance yet, and it is worth naming precisely because it did not look like one.

`return Ok(accountTransactions)` on an empty list is a **success response asserting a fact about
the world** — *this account has no transaction history* — derived from a query that never asked
the question. It then passed through a correct projection, satisfied a correct completeness gate,
and would have been handed to a supervisor as grounds for reasoning. Three correct components in
series, each faithful to its input, carrying a falsehood the whole way because the first one
answered a question it had not been asked.

The seeder's banker-owned accounts are the tell. When the data has to be shaped so that a defect
does not show, **the workaround has become the design** — and it stayed invisible because it made
everything pass.
