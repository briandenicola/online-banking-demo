# Session Log: 2026-05-14T19:17:07Z — Eval Pipeline Fix + Deploy Refactor

## Summary
Basher fixed two critical eval pipeline bugs (FastAPI serialization + incomplete-eval silent success). Coordinator refactored deploy pipeline to use stream-substitute pattern. Both parallel, ~441s combined.

## Issues Fixed
- **Bug A:** FastAPI doesn't serialize `@property` fields on `EvalResults` → C# crash with KeyNotFoundException
- **Bug B:** ai-service didn't check `status=="completed"` after Foundry poll → returned incomplete results silently

## Files Changed
- `src/ai-service/app/routes/api.py` — Added completion check, flattened EvalResults response
- `src/prompt-eval-service/Services/EvaluationService.cs` — Added defensive parsing, zero-result handling
- Deploy pipeline script — Stream-substitute pattern replaces sed-mutate

## Key Learning
All env-specific values in manifests must be derived at deploy time from Terraform state (Convention over Configuration). Never persist hardcoded ACR names, tags, or endpoints in committed files.

## Next Steps
- Redeploy both services via `task cloud:deploy`
- Trigger live eval from UI, confirm no KeyNotFoundException
- Test incomplete/timeout error messages

## Decision Drops
- `basher-eval-keynotfound-20260115.md` (full RCA + contract)
- `copilot-directive-2026-05-14T19-02-30Z-convention-over-config.md` (user directive)
