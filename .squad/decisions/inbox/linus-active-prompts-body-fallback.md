# Decision: Active AI Prompts — graceful fallback for missing body (#120)

**Status:** ✅ Frontend implemented; backend fix flagged
**Date:** 2026-05-13
**Author:** Linus (Frontend)
**Branch/Commit:** squad/p2-wave-3

## Context
The "Active AI Prompts" panel renders `foundry-risk` and
`foundry-categorizer` cards with empty gray bodies and a `Disabled` badge.

## Investigation
- Frontend reads `prompt.systemPrompt` (camelCase). The `enabled` badge
  logic is `prompt.enabled ? 'Active' : 'Disabled'` — not inverted.
- Backend `GET /api/admin/prompts` (`src/ai-service/app/routes/api.py:285-311`)
  returns ONLY `{name, type, enabled}` — there is **no `systemPrompt`
  field on the response**. The handler iterates `analyzers` /
  `categorizers` and could trivially include `analyzer.SYSTEM_PROMPT`
  but doesn't.
- The `Disabled` badge is therefore truthful: `analyzer.enabled` is
  whatever the analyzer object reports. If foundry-risk and
  foundry-categorizer are both initialized but flagged disabled (e.g.,
  no foundry endpoint configured at startup), badge is correct.

## Decision (frontend-side)
1. `ActivePrompt.systemPrompt` is now `string | undefined` in
   `components/eval/types.ts` to match reality.
2. `PromptTemplateEditor.tsx` renders an italicized placeholder when
   `systemPrompt` is missing/empty, explaining the data is not yet
   exposed by the API and pointing at #120.

## What needs Basher (backend)
1. Include `systemPrompt: analyzer.SYSTEM_PROMPT` (and same for
   categorizers) in the `GET /api/admin/prompts` response.
2. Confirm whether `analyzer.enabled` reflects "agent reachable" or just
   "agent constructed" — the badge should mean the former.

**Comment posted on #120 with the above; issue stays open until backend
ships the body field.**
