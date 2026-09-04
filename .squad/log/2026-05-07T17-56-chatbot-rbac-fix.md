# Session Log: Chatbot RBAC Fix
**Timestamp:** 2026-05-07T17:56:00Z

## Fix
- Chatbot service 503 PermissionDenied on agents/write
- Azure AI Developer role scope corrected from account to project level in identity.tf

## Files
- infra/cloud/identity.tf
