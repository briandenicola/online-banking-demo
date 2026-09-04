# Session Log: Cloud Smoke Fixes Deployed
**Date:** 2026-05-13  
**Time:** 2026-05-13T16:46:47Z  
**Branch:** squad/p2-wave-3  
**Environment:** https://onlinebankingdemo.bjdazure.tech

## What Was Fixed

### 1. Frontend Auth State Initialization (Linus)
- **Problem:** AuthContext async state restoration caused redirect flash to /login on page load, breaking test fixtures
- **Fix:** Moved user restoration to `useState` initializer (synchronous localStorage read)
- **Impact:** Fixed 2 dashboard-related smoke test failures

### 2. Registration Username Validation (Linus)
- **Problem:** Frontend sent email addresses as username (with @), backend regex validation requires alphanumeric/underscore/dot/hyphen only
- **Fix:** Extract email local part and sanitize in RegisterPage + test fixture
- **Impact:** Fixed 1 registration smoke test (default account provisioning now succeeds)

### 3. Login Email Fallback (Turk)
- **Problem:** Frontend sends email as login identifier, backend only checked Username field
- **Fix:** Added email fallback lookup in AuthController.Login
- **Impact:** Fixed 1 dashboard test (after deploy)

## Deployment Result

✅ **20 of 21 smoke tests passing** (up from 16/21)

**Sole Remaining Failure:** `Registration — new user can register` — waitForURL timeout post-registration. Root cause: RegisterPage not redirecting to /login after successful registration (frontend state issue). Fix staged in commit b565fd5.

## Commits

1. `babe94d` — Basher: Fix account/transaction DTOs (enum capitalization)
2. `b565fd5` — Linus: Frontend auth + username sanitization
3. `25fe743` — Turk: Email fallback to AuthController.Login

## Decisions Documented

- `.squad/decisions/inbox/basher-cloud-smoke-fix.md`
- `.squad/decisions/inbox/linus-cloud-smoke-fix.md`
- `.squad/decisions/inbox/turk-jwt-email-login-fix.md`

