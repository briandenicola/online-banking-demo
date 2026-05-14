---
updated_at: 2026-05-14T15:50:00Z
focus_area: Foundry validation gates → issues #135/#136
active_issues: [138, 141, 135, 136, 143]
---

# What We're Focused On

Today's gate validation pipeline (Brian's agenda) before starting #135/#136:

1. **TF gate** (#138, #141) — Foundry managed-VNet + connection schema fix
   landed in `b99f3d7` + `ac7dede` + `ef20aab` on `138-foundry-troubleshooting`.
   Awaiting clean `task cloud:up`. May need `terraform force-unlock` and/or
   purge of soft-deleted Foundry account first.
2. **.NET 10 validation** — mechanism TBD, ask Brian.
3. **Eval 403 fix** (PR #143) — verify after TF gate green.

Then: #135 (persist Account Opening workflow stages) + #136 (UI stage progress).

## Process rule (NEW — 2026-05-14)
Sample-first for any Microsoft infra TF. Fetch the official Microsoft sample
via `raw.githubusercontent.com` and diff BEFORE editing. If Basher fails
twice on the same TF surface, coordinator does the surgical edit directly —
no third spawn round. See `.squad/decisions.md` (after Scribe merges
inbox) and `.squad/skills/foundry-managed-vnet/SKILL.md` banner.

## Abandoned / housekeeping
- Background agent `basher-foundry-r2` may still be running with the wrong
  hypothesis. Diff before trusting any commit it lands past `ac7dede`.
