# ADR-003: JWT Claim-Based Roles over External RBAC

**Status**: Accepted  
**Date**: 2026-05  
**Author**: Brian De Nicola

## Context

The application needs role-based access control (User vs Admin) to protect admin-only features: user management, prompt evaluation, anomaly dashboard configuration. Options range from embedding roles in JWT claims to using an external authorization service (OPA, Entra App Roles, Casbin).

## Decision

Embed roles directly in **JWT token claims** issued by the User Service, and validate them with ASP.NET Core `[Authorize(Roles = "Admin")]` attributes and React route guards.

### Reasons

1. **Simplicity** — Roles are stored in Cosmos DB (`Users` container, `role` field) and embedded in the JWT at login time. No external service calls needed for authorization.
2. **Self-contained tokens** — Each service validates the JWT signature and extracts the role claim locally. No network call to an authorization service, reducing latency and eliminating a single point of failure.
3. **First-user-to-admin convention** — The User Service startup code checks if any admin exists; if not, it promotes the oldest registered user. This eliminates manual seeding for demo environments.
4. **Frontend integration** — The React app reads the `role` claim from the decoded JWT to show/hide admin UI elements (user management, evaluation tabs). No additional API call needed.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Entra App Roles** | Enterprise-grade, centralized, auditable | Requires Entra AD app registration per environment, complex local dev setup, token size growth |
| **OPA / Casbin** | Fine-grained policies, policy-as-code | Extra sidecar/service, operational overhead for a demo app, overkill for User/Admin binary |
| **Database lookup per request** | Always current (no stale JWT)  | Network call per request, defeats stateless JWT benefits, higher latency |

## Consequences

- **Positive**: Zero external dependencies for authz, sub-millisecond role checks, works identically in local and cloud
- **Negative**: Role changes require re-login (new JWT), role granularity limited to what fits in claims, token size grows with claims
- **Operational**: Roles managed via Admin panel → User Management; `user-service/Controllers/UsersController.cs` issues JWTs with `ClaimTypes.Role`
