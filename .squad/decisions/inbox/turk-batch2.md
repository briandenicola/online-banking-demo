# Turk — Batch 2 Decisions

## Decision: Dead-Letter Stream Naming Convention
**Context:** Both Go event-processor and Python ai-service now use dead-letter queues for failed Redis stream messages.
**Decision:** Use `{stream-name}-dlq` convention (e.g., `banking-events-dlq`). Configurable retry count via `DLQ_MAX_RETRIES` env var (default 3).
**Status:** Implemented — needs Danny's review for architecture alignment.

## Decision: Redis TLS ServerName Verification
**Context:** Go event-processor used `InsecureSkipVerify: true` and Python used `ssl_cert_reqs=None`, disabling TLS certificate verification.
**Decision:** Use proper TLS verification. Go extracts hostname from connection string for `ServerName`. Python uses `ssl_cert_reqs="required"` with system CA bundle. Local docker-compose (no AZURE_CLIENT_ID) uses plain connections.
**Risk:** Azure Managed Redis cluster nodes may use internal IPs for node-to-node communication. The previous `InsecureSkipVerify` comment mentioned this. If cluster MOVED/ASK redirects fail TLS verification, we may need to revisit with a custom dialer that maps cluster node IPs to the original hostname. Monitor after deployment.
**Status:** Implemented — needs validation in Azure environment.

## Decision: LLM Tool Functions Use JWT Forwarding
**Context:** chatbot-service tool functions accepted `user_id` as an LLM-provided parameter, allowing prompt injection for cross-user data access.
**Decision:** Remove all user identity parameters from tool function signatures. Use `_current_auth_token` ContextVar to forward the JWT to downstream services, which resolve user identity from the token. This is consistent with the "never trust client-supplied user_id" pattern from issue #26.
**Status:** Implemented.

## Observation: ai-service Admin Prompts Already Fixed
The `/api/admin/prompts` endpoint was already gated behind `require_admin` and returns only names/types (no system prompt text) — this was done in issue #26. No further changes needed.
