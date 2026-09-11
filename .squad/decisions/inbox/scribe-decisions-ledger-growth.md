# Proposal: Decisions ledger size and archive threshold

**Author:** Scribe  
**Date:** 2026-09-10  
**Status:** Proposal for Danny's ruling  
**Context:** Current decisions.md is 388KB and growing; every agent spawn reads it. Need a calibrated size/age threshold that reflects spawn cost, not just historical completeness.

---

## Problem

- **Spawn tax:** Every agent at spawn must read decisions.md to build context. A 388KB file is now a non-trivial cost.
- **Age-alone threshold is uncalibrated:** The 30-day archiving rule has not fired yet. At current growth rate, it will not fire for another three weeks, by which time the ledger will exceed 500KB.
- **This project moves fast:** A decision from three weeks ago is still actively referenced (e.g., Danny's §A3 on facts-map binding just landed in Turk's working tree). 30 days is not "old" here.

## What belongs where

**Active ledger (decisions.md):**
- Decisions from the last 14 days (roughly two sprint cycles in this project)
- Any decision actively blocking/unblocking current work (branch #332 is one example)
- Authority rulings on architecture, security, or design that shape multiple future epics

**Archive (decisions-archive.md):**
- Decisions older than 14 days AND not actively cited
- Completed one-off rulings (e.g., "approve this hotfix")
- Decisions superseded by a newer ruling

## Proposed threshold

- **Trigger archival if:** decisions.md exceeds 300KB (avoiding 500KB+ bloat) **AND** the entry is older than 14 days
- **Exception:** Keep entries younger than 14 days regardless of file size (do not prematurely archive active decisions)

## How agents find archived decisions

- Archive name is explicit: `decisions-archive.md`, not a date-stamped file
- Agent context at spawn mentions both files: "Full team decisions → decisions.md; archived decisions (older than 14 days, size-pruned) → decisions-archive.md"
- Grep/search remains available; archived content is still searchable by agent if referenced

---

## Open questions for Danny

1. Is 14 days the right active window for this project's pace?
2. Is 300KB the right size threshold, or should it be lower (faster archival, lower spawn cost)?
3. Should we backfill the archive with the 4KB of pre-2026-09-04 decisions currently in decisions.md, or leave them?
