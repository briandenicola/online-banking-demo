# Decision: Email Lookup Document Pattern for Uniqueness

**Date:** 2026-05-11
**Author:** Basher
**Status:** Implemented
**Priority:** P1

## Context

Cosmos DB has no unique constraint on non-partition-key fields. The user-service container uses `id` as partition key. Email uniqueness was enforced via check-then-create, which is vulnerable to TOCTOU race conditions under concurrent requests.

## Decision

Use a "lookup document" pattern: before creating a user, atomically create a document with `id = "email-lookup:{normalizedEmail}"` in the same container. Cosmos's built-in PK uniqueness guarantee (409 Conflict) prevents duplicates. This is a well-known Cosmos DB pattern for enforcing uniqueness on non-PK fields.

## Implications

- All queries that enumerate user documents (GetAllUsers, IsContainerEmpty, admin count) must filter out `email-lookup:` documents using `NOT STARTSWITH(c.id, 'email-lookup:')`.
- `DeleteUserAsync` must clean up the corresponding lookup document.
- If new fields need uniqueness in the future (e.g., phone number), the same pattern applies with a different prefix.
- Existing users created before this fix won't have lookup docs. The soft email check (`GetUserByEmailAsync`) still runs first and catches most cases; the lookup doc is a race-condition safety net.
