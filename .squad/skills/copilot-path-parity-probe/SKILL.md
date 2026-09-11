# Copilot path parity probe

Use this when validating a Banker Copilot behavior reported from the UI.

## Pattern

1. Read the UI submit path first; do not hand-build a richer request than the browser sends.
2. Reproduce the browser sequence exactly: session bootstrap if present, optional message post, then `POST /sessions/{id}/runs` with the same JSON shape.
3. Compare against any scripted/demo probe and record every extra field it supplies (`actionId`, payload, facts, session context).
4. Classify success from positive trace frames, not from `run.done` alone.
5. A run with no tool frames, no assess frame, and no approval frame is a shell traversal, not proof of model reasoning.
