# Now — where the team is

**Last updated:** 2026-09-09 08:30 CDT
**Branch:** `332-beta` — clean tree, 95 commits ahead of `main`, **nothing pushed**.
**`main` is untouched and stays untouched** until Brian personally deploys, tests and validates in `332-beta`.

---

## The one thing to do first

**Brian must rebuild and deploy FOUR images. Nothing else can proceed until he does.**

```
task cloud:build:account-service
task cloud:build:transaction-service
task cloud:build:authority-service
task cloud:build:ui-app
task cloud:deploy
task cloud:demo:reset -- --reseed
```

Why four:
- Three services changed in Turk's read fix (`1879d43`, `9a346e3`, `5f9d8f1`).
- **`ui-app` must ship in the SAME deploy as the service.** Linus's finding: new UI + old service degrades honestly, **old UI + new service actively lies**. The cluster is currently in that lying state — the copilot service was rebuilt with the real primary assessment, `ui-app` was not.

**Do NOT run any of this for him.** Confirm before ANY action touching his machine or Azure. Reading files is fine unprompted.

---

## What just landed (this session)

### Turk — the banker-customer read fix (the blocker)

Brian logged into the browser as `banker`, saw the *banker* owning sample accounts, and asked why he wasn't seeing customers with the banker working their cases. His words: **"this is the point of the harness that we're creating."** Danny ruled (`3b23945`, `docs/design/banker-customer-read-ruling.md`); Turk implemented.

| SHA | What |
|---|---|
| `1879d43` | **account-service** — banker/supervisor may read *and adjust* a customer account. **Admin may not** (platform authority ≠ banking authority). Denial → `403`, absence → `404`. `UpdateBalance` carries the same authority, so the demo cannot fail one step later, *after* a successful approval, where it would look like the harness had worked. |
| `9a346e3` | **transaction-service — the real defect.** The endpoint documented as "transactions for this account" was implemented as "the caller's transactions, narrowed to this account", so for any non-owner it returned `200 []` **by construction for every account in the bank**. Now queries by account, authorizes explicitly, old filter **deleted** rather than kept as a fallback. |
| `5f9d8f1` | **authority-service** — a policy demanding the account ledger without also demanding the account now **aborts startup**; transaction-service cannot tell "no such account" from "clean history" and must never be asked to. |
| `0fe1bb3` | Evidence fixtures' provenance marked stale, bodies untouched. |

**Two things Turk flagged that need attention:**

1. **The startup guard was not free.** The shipped policy violated it in three actions — flagged-transaction review, score override, transfer reversal — so with the guard in and the policy unamended, **authority-service does not start**. He amended all three to also require the account; it binds from the same `accountId` the ledger already needed, so no working flow loses an argument. **Those three actions now gather one more piece of evidence than they did — Livingston must know before he measures.**
2. **He narrowed the ruling in one place, deliberately, and put it on the record.** For a caller with no banking authority asking about an empty ledger he answers **`403`, not `200 []`**. §B2's table says "permitted and empty" gets `200 []`, but this service does not own accounts, so an unprivileged caller's entitlement can only be read off the rows returned — and zero rows prove nothing. Answering `200 []` there would have rebuilt the defect he had just deleted, one field over. Errs closed, costs no shipping caller (the copilot always holds banker; nothing else calls it).

11 tampers, each caught by a named test — including the empty-array hole, guarded on its own. Suites green: **407 Python, 41 account, 19 transaction, 139 + 224 authority.**

### Rusty — the seeder and the probe (`e37e695`, `6ca478c`)

- **The probe now drives the real path** instead of predicting it: login → session (`sessionId`) → run (`runId`) → trace, classifying on the **positive frame `approval.required`**. On failure it reports the service's own refusal (`run.error` `code`/`message`, or upstream status off `tool.failed`) rather than a prediction of one. A `run.error` following a failed read is labelled a *consequence*, never `[GATE B]` — he caught himself making exactly that mistake in his first cut.
- Because an honest probe **writes**, `demo:show` only probes with `-- --probe`, and otherwise says plainly that it did not check.
- **Poll loop fixed** — it waits on the count of scored subjects owned by accounts *this run* seeded, resolved once before the loop, with separate messages for "nothing scored at all" and "nothing scored that is ours."
- **Reseed:** **Casey and Dana own every account and history. Banker/supervisor/admin own none**, and a guard asserts that shape's *absence* (Danny was explicit: remove them entirely, do not leave them present-but-unused, so nothing can quietly fall back). The empty account, near-threshold pattern and duplicate credits are untouched — Livingston measured the model reasoning about those contents, so only ownership moved. He also followed Turk's §B3.2 pairing into the dataset.

Verified: static suite green, 3 tampers fail as designed, probe correct across 7 mocked API outcomes with `"2500.00"` confirmed on the wire. **Not verified:** nothing ran against Azure beyond read-only checks; no approval created. Task 3 is correct-by-ruling, **not verified-by-run**, until the deploy lands.

---

## Sequence from here — do these in order

1. **Brian rebuilds + deploys the four images** (above), then `task cloud:demo:reset -- --reseed`.
2. **Watch authority-service actually starts.** The new §B3.2 guard aborts startup on a bad policy. If it crash-loops, read the abort message — it names the offending action.
3. **Confirm the seed now exits 0.** It was exiting 3 on a *false* GATE B blocker. If it still fails, read what it says: Rusty's probe now reports the service's real refusal, so the message is trustworthy in a way the old one was not.
4. **Capture the evidence fixtures — NEEDS BRIAN'S APPROVAL, it is a live read against Azure.** Regenerate `tests/fixtures/evidence-samples/{get_account,list_account_transactions}.json` against a **customer-owned** account, and add **two new fixtures, the `403` and the `404`** — both literally unproducible before today. Turk deliberately did not do this without a go-ahead.
5. **Fill the copilot queue.** Livingston's 42 approvals all `TTL_EXPIRED` overnight — the queue is empty (`NEEDS YOU 0` for both roles). ~6 real L2 runs. `amount` must be a **decimal STRING** (`"2500.00"`); a JSON number is refused `payload_not_canonicalizable`. L2 threshold is `1000.00`.
6. **Brian walks §7.1–7.7** in the browser at `https://onlinebankingdemo.bjdazure.tech`.
7. **Only then** Livingston measures **stage 1** — and he must be told about item 1 above (three actions gather one more evidence item). Note this fix **moves the accounts under test, so Livingston's previous 42 runs do not survive it**. Sequencing is part of Danny's ruling: this lands **before** stage 1 is measured, **never between stage 1 and stage 2**.

---

## Open rulings needed from Danny

1. **Rusty's:** repeat seeds each leave a fresh probe approval, because a real run's approval cannot be recognised for reuse. An honest probe writes; how should repeated seeding handle that?
2. **Linus's:** neither agent classifies its own key factors, so **the factor-divergence indicator is structurally silent on all live data**. Linus chose silence over fabrication and wants it ruled on rather than left implicit.

Neither is spawned. Both were queued to go while Brian built.

---

## Also outstanding

- **Scribe has never run this session** — the decision inbox has 12 unmerged files (Turk ×4, Danny ×2, Linus ×3, Rusty, Livingston). `decisions.md` is behind.
- `docs/design/banker-copilot-deployment-verification.md` §4.2 needs updating with Livingston's result.
- **Stage 2** (ceiling budget 0 → 3, a **config edit only** in `harness-limits.yaml`) is **blocked** on Turk's ticket: `quarantined` is overridable and nothing pins the production call site. Latent, not live — one caller, passes nothing. **Budget must stay 0 in committed config** until stage 1 is measured; two deploys = two measurements = attribution preserved.
- §7.4 (the voided-by-policy card) needs a policy edit mid-flight to stage.
- **Deferred-before-`main`:** §R4 evidence↔payload identity, §R3 provenance envelope, §R5 `list_login_audits` upstream filter, §R6 `get_user.status`, multi-role tokens 500-ing ai-service admin auth, and **state-changing endpoints should verify the approval record, not the role** (a banker's authority to move a balance comes from the co-signature, not the job title — Danny framed this for the next epic).
- **#140 loan originations** — `release:backlog`, `squad:turk`. `loan.*` sits inert in `authority-policy.yaml:637+`. **Brian said hold.**

---

## How Brian wants to be worked with

- **Confirm before ANY action touching his machine or Azure.** Reading files is fine unprompted.
- **Keep responses short, plain-language, actionable.** He said the output was *"extremely hard to follow."* Lead with what he should do.
- **Check in every 5–10 minutes** while work is running. He does not like being uninformed.
- **A spawn claim without an agent ID, or a commit claim without a SHA, is to be treated as not done.** This rule exists because I claimed to have spawned two agents and had not. Verify with `list_agents` and `git log`.
- **Tamper-test every guard** — break it, confirm a test fails, revert.
- **Do not overengineer a demo.** His two tests: *"does the defect make the demo FAIL, or make it LIE?"* and *"smallest measured change."*
- **Never `kubectl apply -k deploy/kustomize/base`** — it is a template full of `REPLACE_WITH_*`. Deploy via `task cloud:deploy`.

## Environment

Sub `BJD_Core_Subscription` (`ccfc5dda-43af-4b5e-8cc2-1dda18f2382e`) · AKS `model-osprey-55220-aks` · ACR `modelosprey55220acr` · RG `model-osprey-55220-rg` · ns `banking-demo` · ingress `https://onlinebankingdemo.bjdazure.tech` (public DNS, valid TLS — **no `-k`**).
Users `admin` / `banker` / `banker2` / `supervisor` / `retail` / `verify-target` / `casey` / `dana`, password in `$DEMO_SEED_PASSWORD`.

**API quirks that cost hours:** `POST /api/copilot/sessions` → **`sessionId`**; `.../runs` → **`runId`**; trace at `GET /api/copilot/runs/{runId}/trace`; login is `/api/auth/login` (`/api/users/login` → 405). Approvals have a **TTL and expire overnight** — not a bug, but demo data goes stale.

**Test commands:** Python `cd src/banker-copilot-service && python3 -m pytest tests/ -q`. UI `cd src/ui-app && npx react-scripts test --watchAll=false --testPathPattern <x>` (plain `npx jest` bypasses the CRA babel transform). **13 `account-opening` UI failures are pre-existing.**
