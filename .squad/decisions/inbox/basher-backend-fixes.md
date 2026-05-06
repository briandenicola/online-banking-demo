# Backend Critical Bug Fixes — Decisions

**Author:** Basher  
**Date:** 2026-05-05  
**Status:** Implemented

## Decisions Made

### 1. Transfer Service Balance Updates — Saga-lite Approach
**Decision:** Implemented sequential debit/credit with compensation (reverse debit if credit fails).  
**Rationale:** Full saga pattern with event-driven compensation was too complex for this fix. Current approach handles the most common failure mode (destination credit failure). For production, recommend upgrading to full event-driven saga via event-processor.

### 2. Login 404 Fix — Dual Route Registration
**Decision:** Added login/register to both AuthController (`/api/auth/`) and UsersController (`/api/users/`).  
**Rationale:** Frontend calls `/api/users/login`, nginx routes `/api/users/` to user-service. Rather than change frontend or nginx, exposing login on both route prefixes ensures backward compatibility and matches user expectations.

### 3. Password Hashing — BCrypt.Net-Next
**Decision:** Replaced SHA256+salt with BCrypt (work factor 11, default).  
**Rationale:** SHA256 is not an appropriate password hashing algorithm (too fast, no adaptive work factor). BCrypt provides built-in salt and configurable cost. Note: existing password hashes in Cosmos DB will be incompatible — a migration strategy is needed for production.

### 4. Chatbot-Budget Route Alignment
**Decision:** Fixed chatbot URLs to call budget-service's actual routes directly (not via nginx proxy path).  
**Rationale:** Service-to-service calls go directly to `http://budget-service:8003`, not through nginx. The `/api/budget/` prefix is only added by nginx for external clients. Chatbot should call `/insights/{userId}` and `/categorize` directly.

### 5. Input Validation Strategy
**Decision:** Added DataAnnotations to shared DTO classes.  
**Rationale:** ASP.NET Core automatically validates DTOs with `[ApiController]` attribute. This provides baseline validation without additional middleware. For complex validation, FluentValidation (already referenced in user-service) can be added later.

## Open Items for Follow-up

- [ ] Password hash migration strategy for existing Cosmos DB records
- [ ] Full saga pattern for transfers with event-processor compensation
- [ ] Account-service balance endpoint needs auth (currently no ownership check for service-to-service calls)
- [ ] Budget-service `/categorize` endpoint uses query param — should be POST body
