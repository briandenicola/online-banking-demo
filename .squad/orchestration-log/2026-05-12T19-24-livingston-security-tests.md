# Livingston — 2026-05-12T19:24 UTC

## Task
Write security tests for all auth fixes (Issues #25, #26, #27)

## Mode
Background Agent

## Status
✅ COMPLETED

## Deliverables

### Test Suites Added
- `account-service/SecurityTests.cs` — 9 tests (xUnit/Moq)
- `transaction-service/SecurityTests.cs` — 8 tests (xUnit/Moq)
- `transaction-service/FailClosedSecurityTests.cs` — 3 tests (xUnit/Moq)
- `transfer-service/SecurityTests.cs` — 5 tests (xUnit/Moq)
- `budget-service/test_security.py` — 13 tests (pytest)
- `chatbot-service/test_security.py` — 14 tests (pytest)
- `ai-service/test_security.py` — 28 tests (pytest)

### Infrastructure Changes
- `src/Directory.Build.props` — Excludes stale root-owned build artifacts
- Pytest + httpx added to chatbot-service dev dependencies
- Created transaction-service.Tests project

### Decision Document
- `.squad/decisions/inbox/livingston-security-tests.md` — Test suite summary with findings and open items

## Summary

Added 80 security tests across all services to verify auth boundaries:

**Key Findings:**
1. ✅ .NET auth fixes verified — All ownership checks return NotFound correctly; X-User-Id spoofing rejected
2. ✅ Python JWT auth solid — All services properly validate JWTs (expired, wrong secret, wrong issuer all rejected); admin endpoints enforce role-based access
3. ⚠️ Fail-closed gap remains (Issue #27) — HttpRequestException unhandled; transaction-service needs try/catch to return 503
4. ⚠️ ChatBot cross-user protection works but InMemoryTransactionService has unfixed filtering bug

All tests run without external dependencies. Safe to add to CI pipeline.
