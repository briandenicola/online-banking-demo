# Basher Batch 2 — Security & SDK Decisions

## Decision: Standardized error response format across .NET services

**Status:** Implemented  
**Context:** Multiple controllers leaked raw `ex.Message` to API clients, exposing stack details, account IDs, and balances.  
**Decision:** All .NET API errors now follow `{ error: string, correlationId?: string }`. Business exceptions return safe messages; unknown exceptions return "An internal error occurred" with `HttpContext.TraceIdentifier` for log correlation.  
**Alternatives considered:** Global exception filter middleware — deferred as it requires more coordination across services.  

## Decision: Centralized NuGet version management via Directory.Packages.props

**Status:** Implemented  
**Context:** 5 services + 4 test projects + shared lib all had duplicated package versions, with Cosmos SDK on a pre-release version.  
**Decision:** Created `Directory.Packages.props` at repo root. All shared packages managed centrally. Cosmos SDK set to stable `3.58.0`. Azure.Identity unified to `1.16.0`.  
**Risk:** New services must reference packages without `Version=` attribute. Devs unfamiliar with central package management may add versions inline — needs a CI check or PR review convention.  

## Decision: Admin bootstrap via config, not anonymous endpoint

**Status:** Implemented  
**Context:** `POST /api/admin/promote` was `[AllowAnonymous]`, allowing unauthenticated admin promotion when no admins existed.  
**Decision:** Removed `[AllowAnonymous]`. Admin bootstrap happens at startup via `Admin__BootstrapEmail` env var. Falls back to first-user convention. Endpoint now requires admin JWT.  
**For Danny:** No architecture change needed — this is a config-based bootstrap, not a new service or infra dependency.  

## Decision: Demo passwords from config

**Status:** Implemented  
**Context:** `InMemoryUserService` hardcoded `password123` for seed users.  
**Decision:** Password read from `Demo__Password` config. Defaults to random 16-char string logged at startup. Convention over Configuration.  
