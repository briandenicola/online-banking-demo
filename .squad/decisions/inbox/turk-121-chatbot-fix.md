# Decision: Chatbot account-balance lookup uses `/api/accounts` (not `/api/accounts/my`)

**Author:** Turk (Backend)
**Date:** 2026-05-13
**Issue:** #121
**Status:** ✅ Implemented & verified in cloud

## Context

`agent_tools.get_user_accounts()` in `src/chatbot-service/app/services/agent_tools.py` was calling `GET {ACCOUNT_SERVICE_URL}/api/accounts/my`. That route does not exist on `account-service` (the .NET `AccountsController` exposes only `[HttpGet] /api/accounts`, deriving the user from the JWT `userId` claim). Every chatbot balance query returned 404, which the tool wrapped into a friendly "couldn't retrieve your accounts" string — the exact symptom in #121.

JWT forwarding (per Basher's #117 pattern) was already correct: the chat handler reads `Authorization` off the inbound request and the tool sets it on the outbound httpx call.

## Decision

1. Chatbot calls **`GET /api/accounts`** to list the authenticated user's accounts. The account-service derives the userId from the JWT claim — no `/my`, `/me`, or path-based user identifier is needed (or supported).
2. When a chatbot tool consumes account JSON, it should accept both `accountType` (current account-service field name) and `type` (legacy / alternate). Use `acct.get("accountType", acct.get("type", ""))`.

## Rationale

- One round trip removed; no auth or routing changes needed elsewhere.
- The defensive field fallback prevents another silent regression if the account-service contract is ever revised — the chatbot tool is far enough from the producing service that a strict-by-default read would be a needless coupling.

## Alternatives considered

1. **Add a `/api/accounts/my` route to account-service** that aliases the existing handler. Rejected — pure noise, the existing route already does what the tool needed; we'd be adding API surface to fix a client-side typo.
2. **Define a Pydantic model in the chatbot for the account payload.** Useful but out of scope for a one-line URL fix; flagged as a follow-up if/when chatbot grows more downstream consumers.

## Follow-ups (not blocking #121)

1. **Logging level for downstream HTTP failures in agent tools.** Currently `logger.warning(...)` with the body truncated to 200 chars. Consider `logger.error` for non-2xx responses from in-cluster services, since these almost always indicate a real bug worth paging on.
2. **Shared API contract / typed clients across services.** The chatbot is now the third place where a hand-written URL or field name has drifted from a producing service (after #117 and the account-opening sanitizer history). A small typed client per downstream service (mirroring what `apiClient` does in the React app) would shrink this class of bug.
3. **Surface the actual downstream status code to the agent.** Right now any non-2xx becomes a single sad-face message. Distinguishing 401/403 (auth issue) from 404/500 (service issue) would let the agent give the user a more truthful response and make on-call triage faster.

## Verification

```
$ curl -sk -X POST https://onlinebankingdemo.bjdazure.tech/api/chat \
       -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
       -d '{"message":"What was my last account balance for each of my accounts","user_id":"x"}'
{"response":"Here are your current balances by account, using masked account numbers:
- Checking ****5852: $28,033.96
- Savings ****8917: $350,000.00
- ... (29 accounts total) ..."}
```

Fix landed in `src/chatbot-service/app/services/agent_tools.py`. Built via `task cloud:build:chatbot-service`, deployed via `task cloud:deploy` (which now rollout-restarts pods automatically per Coordinator's e57d5f0).
