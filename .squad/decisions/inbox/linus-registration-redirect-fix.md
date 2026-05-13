# Decision Drop: Registration Smoke Fix — Stale `:latest` Bundle

**Author:** Linus (Frontend Dev)
**Date:** 2026-05-13
**Branch:** squad/p2-wave-3
**Related commit:** b565fd5 (the *source* fix; this drop covers the *deploy* fix)
**Status:** Fixed, smoke green (21/21)

## What Was Broken

The Registration smoke test (`tests/e2e/specs/smoke/smoke.spec.ts:78`) timed out waiting for `**/login` after submitting the registration form against the live AKS deployment.

## Root Cause

**Two layers:**

1. **Browser symptom:** the deployed JS bundle's registration POST payload contained `{username: <raw-email>, email: <raw-email>}` — identical values. Backend rejected with `400 "Email field is not a valid e-mail address"` because `username = email.split('@')[0]` was being skipped (the *email* slot got the local-part instead of the full address). The page rendered "Registration failed. Please try again." and never navigated.

2. **Real cause:** the deployed bundle was the **pre-b565fd5 code**. ACR had a newer `ui-app:latest` digest, but the running pod was created *before* that push and never restarted to pull it.

   The Taskfile pins `ui-app:latest` in `deploy/kustomize/base/kustomization.yaml`. `task cloud:deploy` does `kubectl apply -k`, which is a **no-op** when no manifest field changes. With `:latest`, the Deployment spec is byte-identical run over run, so the pods never roll. `imagePullPolicy: Always` only fires on pod creation — there is no creation event without a manifest delta.

## Fix Applied

Operational only — no source code changed:

```bash
task cloud:build:ui-app                                       # rebuild & push :latest
task cloud:deploy                                             # apply manifests
kubectl -n banking-demo rollout restart deployment/ui-app     # FORCE pod recreate to pull new :latest
```

Verified: live bundle (`main.8a4036f7.js`) now contains `post("/users/register",{username:t,firstName:e,lastName:n,email:a,password:l})` — distinct variables for username and email. Registration smoke passes in 2.2s.

## Recommendation (For Danny / Whoever Owns the Taskfile)

This trap will recur on every UI deploy. Two reasonable fixes — pick one:

**Option A (simplest):** Add `kubectl rollout restart deployment/<svc> -n banking-demo` for each rebuilt service inside `task cloud:deploy` (or a dedicated `cloud:rollout` task). Cheap and guarantees pods pick up new `:latest`.

**Option B (cleaner, more cost):** Drop `:latest` and tag each build with the short git SHA (`{{.GIT_SHA}}`). Kustomize then rewrites `newTag` per deploy, the manifest changes, and Apply triggers a normal rolling update. Bonus: rollback is trivial (re-deploy with prior SHA). This is the standard pattern.

Either way, **`task cloud:deploy` should never silently no-op while the user thinks they shipped new code.** That is the actual bug; the symptom just happened to land in my domain this time.

## Frontend-Side Defense

I also added a note in `.squad/agents/linus/history.md`: when a frontend smoke fails post-deploy, the first diagnostic should be `curl` the bundle from `asset-manifest.json` and grep for a known string from the latest source. Confirms in 30s whether the deployed code matches HEAD before chasing test or app bugs.

## Files Touched

- `.squad/agents/linus/history.md` — appended learnings.
- `.squad/decisions/inbox/linus-registration-redirect-fix.md` — this file.

No source code changes. The b565fd5 frontend fix was correct all along; it just wasn't running.
