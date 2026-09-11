# Session Log — Inbox Merge and Decision Records Durable

**Date:** 2026-09-11T15:20 UTC  
**Branch:** `main` (HEAD `3b1dfcb`)  
**Status:** 13 decision records merged to decisions.md, inbox cleared, committed and pushed

---

## Context

Epic #332 (Banker Copilot) is now closed. PRs #362 and #363 merged to main. During the beta phase, 13 decision records accumulated in `.squad/decisions/inbox/` (gitignored and at risk of loss). This session made them durable by merging into the team memory record.

---

## Deliverables

### Records Merged (13 total)

✓ danny-decisions-ledger-growth.md — Ruling on 64KB budget for active ledger, split by constraint/narrative kind, stored in `.squad/decisions/records/` with stubs in decisions.md  
✓ danny-propose-payload-resolution.md — Ruling on identifier resolution, account ownership binding, and server-filled hash fields  
✓ danny-refusal-code-reachability.md — Ruling on refusal code accuracy; `subject_not_found`/`ambiguous_subject` reachable, model pre-emption blocked  
✓ linus-assert-the-property-not-the-proxy.md — Security test rule: assert the property, not a stand-in; import enforcing module, never mirror constants  
✓ linus-cloud-e2e-gate-and-citation-contract.md — Gate by throwing, not skipping; citation validation on evidence keys; three smaller issues flagged  
✓ scribe-decisions-ledger-growth.md — Scribe's proposal for ledger archiving (rejected by Danny; provided context for his ruling)  
✓ turk-account-ownership-binding.md — Implementation of account ownership binding; derivation pattern, not existence-check; 14 tests covering boundary  
✓ turk-action-metadata-parity.md — A/B measurement and withdrawal; experiment was void (wrong prompt); descriptions are better but wire stays at 0  
✓ turk-catalogue-availability-and-model-budget.md — Catalogue fetch defects; `_required_evidence` return type distinguished; refusal code `authority_catalogue_unavailable`; model timeout calibrated to 60s  
✓ turk-evidence-keys-and-facts-boundary.md — Evidence keyed per-invocation; facts stop merging across subjects; boundary held at evidence serialization  
✓ turk-harness-tool-surface.md — Live harness models 9 of 15 tools; confound larger than effect; wire recommendation withdrawn; 64KB fidelity test pinned  
✓ turk-live-model-acceptance-mode.md — Defect 1: all model calls broken (string vs Message); Defects 2–4: intent prompt, evidence citation, read-then-propose gaps; 2 xfails remain demo-gated  
✓ turk-read-only-leash.md — Structural leash in two layers; `COPILOT_PROPOSE_ENABLED=0` default; refusal code `forbidden_action`; account-binding fix now unreachable  

### Inbox Cleared

✓ All 13 files deleted from `.squad/decisions/inbox/` after content verified present in `.squad/decisions.md` via grep  
✓ Distinctive phrases from each record confirmed in merged file  

### Team Memory State

- **decisions.md:** ~524KB (was 388KB; +127KB net from 13 records)
- **decisions-archive.md:** 733KB (untouched; 59 duplicate entries flagged for cleanup)
- **Ledger growth ruling (Danny):** Documented; implementation deferred to future session (requires `.squad/decisions/records/` directory, stub conversion, merge conflict resolution)

---

## Critical Findings Preserved

### Blocking Merge (§8 of danny-refusal-code-reachability.md)

L2 credit prompt works 1 in 3 times. Cause: actions lack descriptions and field schemas that read tools provide. Fix: add `config/copilot-actions.yaml` with descriptions and payload field specs (YAML already in repo pattern, just sibling file).

### Blocking Demo (§4 of danny-refusal-code-reachability.md, §3.2c of danny-propose-payload-resolution.md, others)

1. `reasonCode` has no server-side enum; model chooses rendering gate
2. Card does not show what account identifier resolved from/to (Turk's subject enrichment required)
3. `subject_lookup_unavailable` refusal code has no UI copy
4. Answer model citation validation rejects legitimate evidence-key citations (evidence keyed by tool id)
5. Read-then-propose in single turn not yet supported

### Unproven in Cloud

Non-disclosure property unproven in cloud e2e (test failed at refusal code assertion, never reached message assertion). Recorded as unproven, not as failing.

### Unexplained

Cloud `objective_unmappable` on refund prompt remains unexplained (A/B used wrong prompt; live harness tool surface mismatch; root cause still open).

---

## No Merge Blockers

§4 (reasonCode enum + render control) and §3 (refusal code fixes) required before demo; not required before merge to main. Section #8 identified as merge-blocking; shipping L2 credit at 1/3 reliability would record epic as done when it is not.

---

## Ledger Growth Ruling Not Executed

Danny's directive 0 is load-bearing: do not enable budget enforcement until records directory exists and stub format is proven. Future session will:

1. Create `.squad/decisions/records/` directory
2. Convert 59 current entries to stubs (constraint in decisions.md, narrative in per-record file)
3. Move 8 largest entries (41% of file) first
4. Mark supersessions explicitly
5. Resolve `.gitattributes merge=union` conflict
6. Enable unconditional post-merge budget check

This session appended records only; no archiving or compaction performed.

---

## Commit Details

Commit includes:
- decisions.md with 13 new records appended (no rewrites or edits to existing entries)
- Inbox directory now empty (13 files deleted)
- Session log entry

Trailers:
```
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
Copilot-Session: 0daa41d3-7658-4c41-bab0-70492f90c2f0
```

---

## Reference

- Epic #332 closed; PRs #362, #363 merged
- Read-only leash deployed and proven in cloud (writes blocked, refusals correct, approval system unreachable)
- Two coordinator errors encountered and repaired during beta: un-substituted kustomize manifests applied to live namespace; leash incorrectly reported as being on main branch
- Next session: decisions ledger archiving per Danny's 64KB/kind ruling
