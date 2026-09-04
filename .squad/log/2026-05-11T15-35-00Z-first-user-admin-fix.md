# Session Log: First User Auto-Promoted to Admin

**Timestamp:** 2026-05-11T15:35:00Z  
**Work:** Online Banking Demo — User Service Bootstrap Logic

## Summary

Fixed bootstrapping issue: when a fresh system has zero users, the first person to register now gets `Role = "admin"` automatically.

## Implementation

1. **UserService (Cosmos DB):** Added `IsContainerEmptyAsync()` check before creating new user. If container empty, new user promoted to admin.

2. **InMemoryUserService:** Added parallel in-memory check. If dictionary empty, first user promoted to admin.

3. **Audit logging:** Both services log the promotion at INFO level for auditability.

## Outcome

✅ Both services now correctly promote the first registered user to admin. Subsequent users get default "user" role. Logic is auditable and testable.

## Files Modified

- src/user-service/Services/UserService.cs
- src/user-service/Services/InMemoryUserService.cs

## Commit

**SHA:** ad75a70
