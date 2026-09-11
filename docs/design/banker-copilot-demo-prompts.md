# Banker Copilot — Test Queries

Example objectives for the `/copilot` command bar.

Surface: `https://onlinebankingdemo.bjdazure.tech/copilot?ff=bankerCopilot` — sign in as
`banker`, or `supervisor` for co-signature steps.

## Read-only (no approval — safe warm-up)

- `Summarise casey's accounts and recent activity`
- `Why was casey's offshore wire flagged?`
- `Compare dana's checking history against casey's — anything unusual?`

## L2 — two signers (credits: `credit-adjustment`)

Both of these are **credits**: a refund and a duplicate-charge correction are money going back
to the customer. `credit-adjustment` raises any credit to L2 — crediting an account creates
money, which is always dual-control. They sat under an "L1 — one signer" heading until
2026-09-10; the heading was wrong, not the policy. There is now no L1 example in this list.

- `Refund a $35 overdraft fee on retail's checking as goodwill`
- `Credit dana $120 for a duplicate charge on her checking account`

## L2 — two signers (≥ $1,000, or escalated)

- `Post a $2,400 adjustment to casey's savings for the disputed deposit`
- `Unlock verify-target's account — lockout was a stale saved password` ← irreversible, needs supervisor

## Escalation triggers

- `high-risk-customer` → anything touching **casey** (raises L1 → L2)
- `large-flagged-amount` → any amount ≥ $25,000, e.g. `Adjust retail's savings by $26,000`

## Score override

- `Casey's offshore wire is legitimate — she notified us in advance. Lower its risk score.`

  **This one refuses, on purpose.** Terminal `failed`, code `payload_unfillable`, and nothing
  reaches authority. The sentence names the transaction by description, and no tool the copilot
  holds can turn "offshore wire" into a transaction id: the only list tool in the risk plane
  returns records carrying neither a customer nor a description. Making it work would mean a new
  subject-scoped read capability in the risk plane, plus a model choosing which transaction a
  money-affecting action applies to — which the resolver rules forbid outright.

  The capability itself is not missing and is demonstrated elsewhere: the agent proposes a bounded
  new score, two humans sign it, and a reduction below the floor escalates and is refused. What is
  missing is only this *phrasing*. Select the flagged case first, then act on it — which is how a
  banker overriding a risk score should be working anyway.

  Ruled by Danny, 2026-09-10. Pinned by
  `test_demo_score_override_exact_sentence_refuses_payload_unfillable`.
