# Session Log: Chatbot DNS Fix
**Session Timestamp:** 2026-05-06T22-03-00Z

## Summary
Fixed hostname mismatch in `infra/cloud/outputs.tf` for AI Foundry endpoint. Changed `local.project_name` to `local.openai_name` for the hostname while preserving `local.project_name` in the path. Chatbot service DNS resolution now functional.
