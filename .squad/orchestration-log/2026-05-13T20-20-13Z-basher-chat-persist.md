# Orchestration Log: basher-chat-persist (2026-05-13T20:20:13Z)

**Agent:** Basher (Backend Dev)  
**Mode:** Background (sonnet 4.5)  
**Status:** Complete  
**Task:** Diagnosed missing partition_key in chatbot upsert_item at agent_service.py:102  

## Deliverables

✅ **basher-chat-persist.md** — Chat persistence regression root cause analysis
- Symptom: All chat messages lost immediately after sending
- Root cause: Missing `partition_key=user_id` in `upsert_item()` call (Cosmos SDK v4 behavior)
- Timeline: Bug existed since May 8 (commit bd4f6a7) when chat persistence was first added
- Reproducer provided (send 2 messages, observe history empty)

## Technical Details

1. **Container schema:** `ChatSessions` uses partition key path `/userId` (not `/id`)
2. **SDK behavior:** Python SDK v4 only auto-infers partition key when path is `/id`
3. **For custom paths:** Must explicitly pass `partition_key=<value>` to `upsert_item()`
4. **Current bug:** Writes fail silently (exception swallowed by `except Exception` at line 104)

## Code Reference

- **File:** `src/chatbot-service/app/services/agent_service.py:102`
- **Current:** `await asyncio.to_thread(state.cosmos_chat_container.upsert_item, doc)`
- **Required fix:** `await asyncio.to_thread(state.cosmos_chat_container.upsert_item, doc, partition_key=user_id)`

## Files to Merge

- ✅ `.squad/decisions/inbox/basher-chat-persist.md` → `decisions.md` (diagnosis + fix recommendation)

## Status

Ready for Basher to implement fix + add integration test.
