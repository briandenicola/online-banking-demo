"""Check 4.2 — harness for measuring the supervisor's real agreement rate.

STATUS: CHECK 4.2 IS BLOCKED AND UNMEASURED. Read ``README.md`` in this directory before
quoting any number this file produces. Two independent server-side gaps stop every copilot
run before the fan-out, so the end-to-end agreement rate does not exist yet:

  Gate A  six read tools point at admin-only or owner-scoped upstreams, and the copilot
          calls upstream with the acting BANKER's token (live proof: run_bc66286148fc465c).
  Gate B  the evidence field names ``authority-policy.yaml`` demands are not the names the
          tools return, and three tools return bare JSON ARRAYS, which can never satisfy
          ``PolicyEvaluator.EvidenceComplete``'s JObject requirement. Gate B is downstream
          of and independent of Gate A: fixing the authorization gap alone unblocks nothing
          (live proof: run_5855e85caad34c12 — both reads returned HTTP 200 with real data
          and the proposal was still rejected ``evidence_incomplete``).

Until both are fixed, this file runs in COMPONENT mode: it calls ``FoundryDecider`` directly
with pre-built evidence and STUBS THE ENTIRE FAN-OUT SEAM. Its output answers "can this model
produce a reasoned disagreement at all" and NOT "what is the co-signature's agreement rate".
Never quote it as the latter.

The question
------------
Epic #332 Phase 3 gives L2 banking actions a blind second opinion. Until commit ``87a0ee4`` that
opinion came from ``deterministic_decider``, which returns ``proceed`` whenever its own reads
succeed — so agreement with the primary (which PROPOSED the action, and therefore always says
``proceed``) was 100% by construction. ``FoundryDecider`` replaced it with a real model call.
Check 4.2 asks one thing: **is disagreement now genuinely reachable?**

How this measures it
--------------------
Run it INSIDE the live ``banker-copilot-service`` pod::

    kubectl cp tests/verification banking-demo/$POD:/tmp/verification -c banker-copilot-service
    kubectl exec -n banking-demo $POD -c banker-copilot-service -- \
        python /tmp/verification/supervisor_agreement_probe.py --out /tmp/results.jsonl
    kubectl cp banking-demo/$POD:/tmp/results.jsonl ./results.jsonl -c banker-copilot-service

In-pod is not a convenience. It is the only place the measurement is honest: the pod holds the
workload identity, the private-endpoint route to Foundry, the deployed ``FOUNDRY_MODEL``, and the
exact ``supervisor_model.py`` that is serving traffic. Anything reconstructed outside it measures
a copy.

What it deliberately does NOT exercise
--------------------------------------
It calls ``FoundryDecider`` directly with pre-built evidence rather than driving a copilot run
through ``POST /api/copilot/sessions/{id}/runs``. That is not the preferred path — the end-to-end
one is — but the end-to-end path is currently CLOSED for every action in the policy: the evidence
field names ``authority-policy.yaml`` demands (``accountId``, ``userId``, ``count``, ``status``…)
are not the field names the read tools return (``id``, ``isActive``, a bare JSON array…), so
``PolicyEvaluator.EvidenceComplete`` rejects every proposal with ``evidence_incomplete`` and the
propose step never admits an approval. No approval means ``requiredRung`` is never read, and the
mandatory L2 fan-out in ``loop.py`` never fires. See finding F-4.2-B.

So this probe measures the decider, not the plumbing. The prompt, the model, the parse path and
the fail-closed behaviour are the real deployed ones; the fan-out seam around them is stubbed.
Say that plainly in any report built from these numbers.

Three outcomes, never two
-------------------------
``FoundryDecider`` fails CLOSED: a timeout, a throttle, a content-filter refusal or unparseable
output all return ``hold`` / ``confidence 0.0`` / ``keyFactors == ("supervisor_unavailable",)``.
That is a FAILED MODEL CALL, not a disagreement. Counting it as disagreement would manufacture
exactly the false signal this exercise exists to delete, so it is classified separately and
reported separately.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.planner.fanout import BankerIntent, build_supervisor_input  # noqa: E402
from app.planner.supervisor_model import FoundryDecider, supervisor_mode  # noqa: E402
from app.config import env_with_legacy  # noqa: E402

from supervisor_cases import CASES  # noqa: E402

# The primary PROPOSED the action, so its position is always to proceed. ``fanout._primary_recommendation``
# reads it from the approval and falls back to exactly this. Agreement is computed the same way
# the production seam computes it — by comparison, after the fact.
PRIMARY_RECOMMENDATION = "proceed"

UNAVAILABLE_MARKER = "supervisor_unavailable"


def classify(opinion) -> str:
    """agree | disagree | unavailable. The third bucket is the whole point."""
    if UNAVAILABLE_MARKER in tuple(opinion.key_factors) and opinion.confidence == 0.0:
        return "unavailable"
    if opinion.recommendation.strip().casefold() == PRIMARY_RECOMMENDATION:
        return "agree"
    return "disagree"


async def run_case(decider: FoundryDecider, case: dict) -> dict:
    spawn = build_supervisor_input(
        BankerIntent(task_framing=case["framing"], entity_ids=tuple(case["entity_ids"]))
    )
    started = time.monotonic()
    opinion = await decider(spawn, case["evidence"])
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "caseId": case["id"],
        "action": case["action"],
        "expectation": case["expectation"],
        "caseRationale": case["rationale"],
        "primaryRecommendation": PRIMARY_RECOMMENDATION,
        "recommendation": opinion.recommendation,
        "confidence": opinion.confidence,
        "keyFactors": list(opinion.key_factors),
        "strongestCounterArgument": opinion.strongest_counter_argument,
        "outcome": classify(opinion),
        "elapsedMs": elapsed_ms,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/supervisor_agreement.jsonl")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Run the whole corpus N times. Sample size is len(CASES) * repeat.")
    parser.add_argument("--only", default="", help="Comma-separated case ids to run.")
    args = parser.parse_args()

    mode = supervisor_mode()
    if mode != "foundry":
        # Refuse rather than degrade. A run against the scripted decider would produce a
        # 100%-agreement number that looks exactly like a passing measurement.
        print(f"REFUSING: supervisor_mode() is {mode!r}, not 'foundry'. "
              "This probe would measure the script it exists to replace.", file=sys.stderr)
        return 2

    endpoint = env_with_legacy("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "").strip()
    model = env_with_legacy("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT", "").strip()
    decider = FoundryDecider(endpoint=endpoint, model=model)

    wanted = {c.strip() for c in args.only.split(",") if c.strip()}
    cases = [c for c in CASES if not wanted or c["id"] in wanted]

    print(f"supervisor_mode=foundry model={model} cases={len(cases)} repeat={args.repeat}",
          file=sys.stderr)

    results: list[dict] = []
    with open(args.out, "w", encoding="utf-8") as fh:
        for rep in range(args.repeat):
            for case in cases:
                try:
                    row = await run_case(decider, case)
                except Exception as exc:  # noqa: BLE001 - a harness crash must not read as a verdict
                    row = {
                        "caseId": case["id"], "action": case["action"],
                        "expectation": case["expectation"], "outcome": "harness_error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                row["rep"] = rep
                results.append(row)
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                print(f"  {row['caseId']:<32} rep{rep} -> {row['outcome']:<12} "
                      f"{row.get('recommendation','-'):<8} conf={row.get('confidence','-')}",
                      file=sys.stderr)

    await decider.aclose()
    summarise(results)
    return 0


def summarise(results: list[dict]) -> None:
    counts = Counter(r["outcome"] for r in results)
    n = len(results)
    agree, disagree = counts["agree"], counts["disagree"]
    unavailable, errors = counts["unavailable"], counts["harness_error"]
    verdicts = agree + disagree

    print("\n" + "=" * 72, file=sys.stderr)
    print("COMPONENT-MODE RESULT — this is NOT a check 4.2 agreement rate.", file=sys.stderr)
    print("The fan-out seam is stubbed; see README.md, gates A and B.", file=sys.stderr)
    print("-" * 72, file=sys.stderr)
    print(f"SAMPLE SIZE {n}", file=sys.stderr)
    print(f"  agreed                 {agree}", file=sys.stderr)
    print(f"  disagreed              {disagree}", file=sys.stderr)
    print(f"  supervisor-unavailable {unavailable}   (failed model calls, NOT disagreement)",
          file=sys.stderr)
    if errors:
        print(f"  harness errors         {errors}", file=sys.stderr)
    if verdicts:
        print(f"  agreement rate over real verdicts: {agree}/{verdicts} = {agree / verdicts:.1%}",
              file=sys.stderr)
    print("=" * 72, file=sys.stderr)

    # The measurement that matters most is per-expectation: a supervisor that agrees on the
    # cases built to be stopped is rubber-stamping regardless of its headline rate.
    for expectation in ("proceed", "stop"):
        subset = [r for r in results if r.get("expectation") == expectation and r["outcome"] in ("agree", "disagree")]
        if not subset:
            continue
        stopped = sum(1 for r in subset if r["outcome"] == "disagree")
        print(f"cases built as '{expectation}': {len(subset)}; supervisor withheld on {stopped}",
              file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
