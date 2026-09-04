# Orchestration Log Entry

### 2026-05-13T17:20:09Z — Coordinator: Rollout Restart Integration (cloud:deploy Task)

| Field | Value |
|-------|-------|
| **Agent routed** | Coordinator (User/Brian via DevOps) |
| **Why chosen** | Cross-cutting deployment issue; Taskfile owns cloud:deploy |
| **Mode** | `sync` |
| **Why this mode** | Infrastructure fix with immediate fleet impact |
| **Files authorized to read** | Taskfile, kustomize base manifests, cloud:deploy target |
| **File(s) agent must produce** | Updated Taskfile with rollout restart commands (commits e57d5f0, 1a989f2) |
| **Outcome** | ✅ Completed — rollout restart added to cloud:deploy post-apply. NAMESPACE hoisted to Task var (commit 1a989f2). Resolves stale-bundle trap where `:latest` pods don't pick up new images. |

---

## Changes Summary

- **Commit e57d5f0:** Added `kubectl rollout restart deployment/<svc>` for each rebuilt service inside `cloud:deploy`
- **Commit 1a989f2:** Hoisted `NAMESPACE` to Task-level variable (eliminates duplicate hardcoding)
- **Impact:** Eliminates the footgun where `task cloud:deploy` appears to succeed but pods stay on old `:latest` digest
- **Related:** Fixes the root cause of Linus's registration smoke timeout (stale-bundle trap)
