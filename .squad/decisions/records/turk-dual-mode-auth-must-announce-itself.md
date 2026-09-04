---
date: 2026-09-04
author: Turk (Backend)
status: proposed
component: all services (cross-cutting)
issue: 332
---

# Dual-mode auth must announce which mode it chose

## What happened

Running `authority-service` locally, every write returned:

```
500 {"error":"InternalError","message":"Failed to acquire token"}
```

The cause, eventually: `AZURE_CLIENT_ID` is set in the developer's shell. Our dual-mode pattern
reads that as "use Entra ID", so the service tried `ClientSecretCredential` against the real
tenant, which refused with a Conditional Access policy. Nothing was wrong with the service, the
policy, Redis, or Cosmos. The service had silently selected production auth on a laptop.

Ten minutes to find, and only because I could read the structured log and pull out the inner
`MsalClaimsChallengeException`. The user-visible message named neither the dependency nor the
mode.

## Why this is worth a decision rather than a shrug

The dual-mode switch — `AZURE_CLIENT_ID` present → Entra, absent → connection string — is a good
pattern and I am not proposing changing it. The problem is that **it is an invisible branch
driven by ambient environment state**, and every service in this repo has it: transfer-service,
transaction-service, account-service, the Python services, and now authority-service.

The failure mode is the same everywhere: an env var the developer does not remember setting
silently changes which identity the service presents, and the resulting error surfaces as a
generic 500 from whichever dependency happened to be touched first.

## Proposal

Two small things, applied consistently:

1. **Log the chosen mode at startup, once, per dependency.** `"Redis: Entra ID auth (client
   id 7f3a…)"` or `"Redis: connection string auth (redis:6379)"`. The branch stops being
   invisible. This is three lines per service.
2. **Name the dependency in the error.** "Failed to acquire token" should be "Failed to acquire an
   Entra token for Redis". A 500 that does not say what it was talking to costs the same ten
   minutes every time.

I have deliberately **not** made this change, because it touches services Rusty and others own
and it is a repo-wide convention rather than my call. In `authority-service` I will follow
whatever is ratified.

## Ask

Danny / Rusty: is this worth a small sweep across the services? I think the cost is minutes per
service and the saving is the next person's afternoon.
