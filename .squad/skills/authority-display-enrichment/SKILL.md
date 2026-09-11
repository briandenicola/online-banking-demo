# Authority Display Enrichment

Use when an approval/API card needs human-readable context for policy, evidence, or subject fields without changing the authority payload.

## Pattern

1. Keep persisted authority inputs minimal and canonical: `payload`, `evidence`, `facts`, policy snapshot, and hash fields.
2. Add presentation fields in the response mapper, not in the payload:
   - evidence `label`
   - evidence `summary`
   - approval `subject`
3. Derive only from already-stored facts/evidence unless a deliberate service lookup is required and tested.
4. Never add display-only data to `hashFields`; use tests to prove response enrichment does not mutate stored `payload` or `evidence`.
5. Put policy-affecting facts in `EvaluationContext` instead. Example: `context.supersedes` changes the rung decision; `subject.label` does not.

## Test hooks

- Unit-test the response shape for representative user/account actions.
- Unit-test no mutation of source `Approval.Payload` or `Approval.Evidence`.
- Unit-test policy guard structure when a field must not use `raiseBy`.
