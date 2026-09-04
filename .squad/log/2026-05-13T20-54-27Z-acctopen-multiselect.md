# Session Log: Linus — Account Opening Multi-Select

**Timestamp:** 2026-05-13T20-54-27Z  
**Focus:** Block multi-select on DocumentUpload (Option 3)

## Summary

Linus (Frontend) amended commit 418cbdd (Basher's acctopen-422 field-name fix) with follow-up Option 3 fix: remove `multiple` attribute from file input, change signature to singular `File`, update UI copy. Build succeeded. 24/24 tests pass. Commit: d4b52be.

## Why Option 3

Backend FastAPI endpoint signature is singular (`file: UploadFile`). Frontend `<input multiple>` allowed 2+ files, but FastAPI's singular binding silently dropped extras. This fix enforces the actual backend contract upfront.

## Related

- Decision merged: `.squad/decisions.md` — "Block Multi-Select for Account Opening Document Upload"
- Amends 418cbdd (Basher's parallel fix) — both are P2 wave-3 work
