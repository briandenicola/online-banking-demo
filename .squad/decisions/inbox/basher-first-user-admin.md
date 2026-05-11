# Decision: First registered user auto-promoted to admin

**Author:** Basher
**Date:** 2026-05-11
**Status:** Proposed

## Context

When a fresh system has zero users, the first person to register gets `Role = "user"` and there's no admin to manage the system. This is a bootstrapping problem.

## Decision

Both `UserService` (Cosmos DB) and `InMemoryUserService` now check if the user store is empty before creating a new user. If empty, the new user gets `Role = "admin"` automatically. The promotion is logged at INFO level for auditability.

## Rationale

- Simplest possible fix — no config flags, environment variables, or seed scripts needed.
- Only applies to the very first user; all subsequent users get the default `"user"` role.
- Logged so it's auditable and won't silently grant admin.

## Trade-offs

- A race condition is theoretically possible if two users register simultaneously on an empty Cosmos container. In practice this is extremely unlikely during initial setup. If needed, a distributed lock could be added later.
