---
date: 2026-09-10T23:19:23Z
session: Free-text planner architecture completion + xfail rulings + facts-map bug discovery
branch: 332-beta
epic: 332 (Banker Copilot agentic harness)
---

# Session Log — Free-text outcomes, xfail rulings, facts-map critical bug

## Summary
Three agents completed architecture work and decision rulings. One critical bug discovered in multi-subject run facts handling; one facts-map cross-subject data-boundary breach. Merge readiness conditional on deployment + browser verification.

## Linus (Frontend) — Complete
- Two-outcome UI (read-only answers + named refusals)
- Subject non-disclosure enforced client-side
- Session stream closure proposal (deferred to server)
- Test coverage: 527 → 541 passed
- Status: Pushed; awaiting merge

## Danny (Architect/Lead) — Complete
- Epic #332 merge readiness: Work done, proof needed. Deploy + 3 browser runs (1h).
- Xfail Prompt A (two-customer comparison): BUILD IT. Canonicalization risk is zero. Facts-map bug is real and critical.
- Xfail Prompt B ("lower its risk score"): CUT UTTERANCE. Keep capability (already demonstrated). Determinism > feature coverage.
- Subject resolution: Add lookup tools, bounded directory endpoint, terminal refusals.
- Risk-score override: Model proposes, both signers see it, hash-bound. No human edit at sign time.
- Found: Evidence key boundary, redaction safety, citation scope, payload domain constraints gap.

## Turk (Backend) — In Flight
- Free-text planner design complete: intent → resolve → read/propose/refuse paths
- Env-gated live-model mode: foundry mode vs deterministic fallback
- Facts-map fix critical: First-writer-wins merge across subjects is a data-boundary breach carrying wrong customer into approval record
- Three required tests: bundle shape, already_gathered refusal, facts carry no cross-subject merge

## Blockers
- **Deploy + browser runs:** Unblock merge
- **Facts-map fix:** Unblock Linus, required before merge
- **Env-gated model mode:** Gate live-model availability, fail loud

## Next
1. Turk completes facts-map fix (one change, two files affected)
2. Deploy both services from `332-beta`
3. Run three prompts in browser
4. Merge if verified
