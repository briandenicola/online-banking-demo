# Session Log — Demo TTL Override and §R10 Reseed Verification

**Date:** 2026-09-09
**Team:** Rusty (Platform) + Squad (Coordinator)
**Requested by:** Brian (approved both override and reseed)
**Branch:** `332-beta`

---

## THE PROOF

### Reseed at 2026-09-09T23:37:00Z — Result: QUALIFIED

The live reseed succeeded and terminated deterministically on a qualifying subject.

**Scoring poll behavior:**
- **Duration:** ~35 seconds (awaited for qualifier)
- **Termination:** on qualifying subject (no timeout)
- **Flag amount:** `61200`
- **Escalator fired:** `large-flagged-amount`

**Demo output:**
```
flag-review-denied subject: 61200 against the 25000 dual-control line
```

**Approval escalation ladder:**
- **Required rung:** L2 (expected for `large-flagged-amount`)
- **Result:** **deterministic L2** (previous two runs: L2 then L1 by chance)

**Subject verification (live API check):**
```
GET /api/flagged-transaction/<subject-id>
Response: HTTP 200
requiredRung: "L2"
payload.amount: 61200
firedEscalators: ["large-flagged-amount"]
status: returns successfully (not expired)
```

**TTL coverage:**
- All 10 pending approvals carry 8-hour TTLs
- Verified from `/api/authority/policy` — all 9 policy TTLs report `28800` with `overriddenByEnv: true`

---

## ⚠️ THE CAVEAT

**The 8-hour TTL does NOT make a seed survive overnight.**

Seeded approval **expires at 2026-09-10T07:37:00Z** (02:37 CDT), **8 hours after reseed**.

**Brian must reseed tomorrow morning** for the demo to survive the whole working day.

**The value of the 8-hour TTL:**
- A seed created in the morning survives the whole working day (previously died in ~20 minutes)
- Supports repeated runs or long walkthroughs without approval expiration
- Does not extend beyond overnight

---

## Configuration Applied

**ConfigMap:** `banking-demo-config` on `model-osprey-55220-aks`

All 9 approval TTLs set to `28800` (8 hours) via environment variables:

| Threshold | Env Key | Default (Unchanged) |
|-----------|---------|---------------------|
| `approval_ttl_default` | `POLICY_APPROVAL_TTL_SECONDS` | 1800 |
| `ttl_transaction_flag_review` | `POLICY_TTL_TRANSACTION_FLAG_REVIEW` | 1800 |
| `ttl_transaction_score_override` | `POLICY_TTL_TRANSACTION_SCORE_OVERRIDE` | 3600 |
| `ttl_account_opening_review` | `POLICY_TTL_ACCOUNT_OPENING_REVIEW` | 7200 |
| `ttl_transfer_reverse` | `POLICY_TTL_TRANSFER_REVERSE` | 1200 |
| `ttl_balance_adjust` | `POLICY_TTL_BALANCE_ADJUST` | 1200 |
| `ttl_user_lock` | `POLICY_TTL_USER_LOCK` | 900 |
| `ttl_user_unlock` | `POLICY_TTL_USER_UNLOCK` | 1800 |
| `ttl_loan_decision` | `POLICY_TTL_LOAN_DECISION` | 14400 |

**File verification:**
- `git diff config/authority-policy.yaml` = empty (shipped defaults NOT weakened)
- `deploy/kustomize/base/configmap.yaml` updated with rationale in comments
- No image rebuild (digest verification: `sha256:e71a449e…` identical before/after)
- Pod status: `authority-service` 2/2 Running, 0 restarts

---

## Verification Checklist

✅ Live cluster reports all 9 TTLs at 28800 with `overriddenByEnv: true`  
✅ Policy identity stable (banker-copilot-authority, 22 thresholds, 13 action types)  
✅ Policy file unchanged (config/authority-policy.yaml)  
✅ Reseed qualified on live demo  
✅ Escalation deterministic (L2 per `large-flagged-amount`)  
✅ Subject returns HTTP 200 from approval API  
✅ Policy version hash moved correctly (proof override worked, not proof of file edit)  

---
