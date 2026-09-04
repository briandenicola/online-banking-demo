---
date: 2026-06-05
timestamp: 2026-06-05T19:23:16Z
session: turk-python-symlink-fix
---

# Python Exec Fix Session Log

**Task:** Fix `exec: "python": not found` in MCR Azure Linux containers.

**Solution:** Add `RUN ln -sf /usr/bin/python3 /usr/bin/python` to 4 Python service Dockerfiles before dropping to non-root USER.

**Verification:** All containers start cleanly. No exec errors in logs.

**Status:** ✅ COMPLETE
