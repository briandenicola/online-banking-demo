# Skill: API Outbound Projection (storage ↔ UI contract drift)

## When to use

When the persisted document and the UI's expected shape diverge — e.g.:
- The UI reads `application.stages[]` but Cosmos has `agentResults[]`.
- The UI reads `application.riskTier` but the value lives in `agentResults[*].findings.riskTier`.
- The UI wants flattened convenience fields (`firstName`) that are nested in `formData.firstName`.

…and you don't want to migrate the storage layer or rewrite every writer.

## Pattern

1. Keep the Pydantic model and Cosmos repository **identical to the storage shape**. No new fields, no derived properties. Writes stay symmetric with reads.
2. Add `app/services/projection.py` (or `app/projections/<entity>.py`) with a single `project_<entity>(model) -> dict` helper that:
   - Calls `model.model_dump(mode="json")` as the base.
   - Adds derived fields (lookups, denormalizations, status-machine snapshots).
   - Returns a plain dict — FastAPI serializes it.
3. Wire `project_<entity>()` into **every** route that returns the entity. Add a `project_<entities>()` list helper for collection routes.
4. Unit-test the projection in isolation against synthetic models. The route tests (which often use mocked repositories) keep working because the shape they assert on is now the projected shape.

## Anti-patterns

- ❌ Don't add derived fields as Pydantic `@computed_field`s on the storage model — they get serialized into Cosmos on the next write and you end up with stale, duplicated state in the document.
- ❌ Don't rename storage fields to match the UI — every existing document and every writer breaks.
- ❌ Don't derive on the UI side from raw `agentResults` — the same logic ends up duplicated across every component that reads the entity.

## Reference implementation

- `src/account-opening-service/app/services/projection.py` — derives `stages[]` and `riskTier` from `agentResults`.
- `src/account-opening-service/app/routes/api.py` — calls `project_application()` / `project_applications()` on the way out of every read endpoint.
- `src/account-opening-service/tests/test_projection.py` — 6 cases covering pending / in-progress / completed stages and risk-tier extraction.

## Related issues

- #124 — original bug ("No stage data available" on admin dashboard).
