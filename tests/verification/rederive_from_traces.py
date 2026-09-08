"""Check 4.2 — re-derive every recorded run from its trace, trusting no status field.

Why this exists
---------------
On the build the 2026-09-08 measurement was taken against, ``run.done.status`` is UNRELIABLE.
The planner opened with ``status = "completed"`` and only lowered it where a path remembered
to. The tool-failure path remembered; the **propose** path did not. So a run whose proposal was
REFUSED — no approval produced, nothing for a human to sign — still reports
``run.done {"status": "completed"}``, and emits ``step.completed`` on the step that just
errored. ``start_run``'s ``finally`` block also hardcoded ``completed``, so a planner that
RAISED was recorded as completed too. That is the field ``GET /api/copilot/runs/{id}`` hands
back to a harness.

This script re-derives the outcome of every recorded run from its TRACE FRAMES alone and diffs
that against what the probe originally recorded. It re-reads; it does not re-run. Run ids are
taken from the committed results files, so the same runs are re-graded rather than resampled.

The derivation rule — positive signals only
-------------------------------------------
A run is a data point only if its trace carries ALL THREE of:

    approval.required   with requiredRung == "L2"
    subagent.spawned    with role == "supervisor"
    subagent.completed

and carries NO ``run.error`` frame anywhere. ``run.done.status`` is not consulted for ANY
admitting decision. It is read only to report disagreement between the field and the frames,
which is direct evidence of the defect.

Four buckets, never two
-----------------------
    agree           supervisor said proceed
    disagree        supervisor said hold/decline — a real model verdict
    unavailable     FAILED SUPERVISOR CALL: keyFactors == ["supervisor_unavailable"] AND
                    confidence == 0.0. FoundryDecider fails closed, so this is
                    indistinguishable from a real hold on the verdict token alone.
    instrument      THE MEASUREMENT DID NOT HAPPEN: a run.error frame, or a missing fan-out
                    signal. A defect in the rig, not an opinion about banking. Separate from
                    `unavailable`, which is the supervisor failing, not the instrument.

Only ``agree`` and ``disagree`` enter the agreement-rate denominator.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from e2e_supervisor_probe import _request, login  # noqa: E402

UNAVAILABLE_MARKER = "supervisor_unavailable"
PRIMARY_RECOMMENDATION = "proceed"


def derive(frames: list[dict]) -> dict:
    """Outcome from frames alone. `run.done.status` is never consulted to admit a run."""
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for f in frames:
        by_kind[f.get("kind")].append(f)

    done = by_kind.get("run.done", [])
    claimed = (done[-1].get("payload") or {}).get("status") if done else None
    errors = by_kind.get("run.error", [])

    out: dict = {
        "claimedStatus": claimed,
        "hasRunError": bool(errors),
        # The defect, made visible: a run that says completed while carrying an error frame.
        "statusFieldLied": bool(errors) and claimed == "completed",
    }
    if errors:
        out["outcome"] = "instrument"
        out["instrumentReason"] = "run.error frame present"
        out["error"] = json.dumps(errors[0].get("payload"))[:400]
        return out

    required = [f for f in by_kind.get("approval.required", [])
                if ((f.get("payload") or {}).get("approval") or {}).get("requiredRung") == "L2"]
    spawned = [f for f in by_kind.get("subagent.spawned", [])
               if (f.get("payload") or {}).get("role") == "supervisor"]
    completed = by_kind.get("subagent.completed", [])

    out["reachedL2"] = bool(required)
    out["supervisorSpawned"] = bool(spawned)
    out["supervisorCompleted"] = bool(completed)
    if not (required and spawned and completed):
        out["outcome"] = "instrument"
        out["instrumentReason"] = (f"reachedL2={bool(required)} spawned={bool(spawned)} "
                                   f"completed={bool(completed)}")
        # A run missing the fan-out while claiming completed is the same defect.
        out["statusFieldLied"] = claimed == "completed"
        return out

    updated = by_kind.get("approval.updated", [])
    if not updated:
        out["outcome"] = "instrument"
        out["instrumentReason"] = "no approval.updated frame carried the opinion"
        out["statusFieldLied"] = claimed == "completed"
        return out

    sup = (((updated[-1].get("payload") or {}).get("approval") or {})
           .get("agentAssessment") or {}).get("supervisor") or {}
    factors = [f.get("label") if isinstance(f, dict) else f for f in sup.get("keyFactors") or []]
    verdict = str(sup.get("verdict") or "").strip()
    confidence = sup.get("confidence")

    out.update({"supervisorVerdict": verdict, "confidence": confidence, "keyFactors": factors,
                "strongestCounterArgument": sup.get("rationale")})

    if factors == [UNAVAILABLE_MARKER] and confidence == 0.0:
        out["outcome"] = "unavailable"
        return out

    out["outcome"] = "agree" if verdict.casefold() == PRIMARY_RECOMMENDATION else "disagree"
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="https://onlinebankingdemo.bjdazure.tech")
    p.add_argument("--user", default="banker")
    p.add_argument("--password", default=os.environ.get("BANKER_PASSWORD", ""))
    p.add_argument("--inputs", nargs="+", required=True, help="Recorded .jsonl result files.")
    p.add_argument("--out", default="rederived.jsonl")
    args = p.parse_args()

    if not args.password:
        print("REFUSING: no password (--password or $BANKER_PASSWORD).", file=sys.stderr)
        return 2
    token = login(args.base, args.user, args.password)

    recorded: list[dict] = []
    for path in args.inputs:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    recorded.append(json.loads(line))

    print(f"re-deriving {len(recorded)} recorded runs from traces (read-only)", file=sys.stderr)

    rows, mismatches, liars = [], [], []
    with open(args.out, "w", encoding="utf-8") as fh:
        for rec in recorded:
            run_id = rec.get("runId")
            if not run_id:
                continue
            status, body = _request("GET", f"{args.base}/api/copilot/runs/{run_id}/trace", token)
            if status != 200 or not isinstance(body, dict):
                row = {"caseId": rec["caseId"], "runId": run_id, "outcome": "instrument",
                       "instrumentReason": f"trace unreadable HTTP {status}"}
            else:
                row = {"caseId": rec["caseId"], "rep": rec.get("rep", 0), "runId": run_id,
                       "expectation": rec.get("expectation"), "polarity": rec.get("polarity"),
                       "grounded": rec.get("grounded"),
                       "originalOutcome": rec.get("outcome"),
                       "frameCount": body.get("frameCount"),
                       "traceDegraded": body.get("traceDegraded")}
                row.update(derive(body.get("frames") or []))

            # The original probe recorded `no_fanout`/`run_failed`; both re-derive to `instrument`.
            orig = rec.get("outcome")
            norm = "instrument" if orig in ("no_fanout", "run_failed") else orig
            row["classificationChanged"] = norm != row["outcome"]
            if row["classificationChanged"]:
                mismatches.append(row)
            if row.get("statusFieldLied"):
                liars.append(row)

            rows.append(row)
            fh.write(json.dumps(row) + "\n")

    out = sys.stderr
    counts = Counter(r["outcome"] for r in rows)
    agree, disagree = counts["agree"], counts["disagree"]
    verdicts = agree + disagree

    print("\n" + "=" * 74, file=out)
    print("RE-DERIVED FROM TRACE FRAMES ONLY — run.done.status not consulted", file=out)
    print("-" * 74, file=out)
    print(f"runs re-graded            {len(rows)}", file=out)
    print(f"  agreed                  {agree}", file=out)
    print(f"  disagreed               {disagree}", file=out)
    print(f"  supervisor-unavailable  {counts['unavailable']}   failed SUPERVISOR call", file=out)
    print(f"  instrument failures     {counts['instrument']}   measurement did not happen", file=out)
    if verdicts:
        print(f"AGREEMENT RATE  {agree}/{verdicts} = {agree / verdicts:.1%}", file=out)
    print("-" * 74, file=out)
    print(f"classification changes vs original probe: {len(mismatches)}", file=out)
    for m in mismatches:
        print(f"  {m['caseId']:<42} {m.get('originalOutcome')} -> {m['outcome']}", file=out)
    print(f"runs claiming 'completed' while carrying run.error or missing fan-out: {len(liars)}",
          file=out)
    for m in liars:
        print(f"  {m['caseId']:<42} {m['runId']} claimed={m.get('claimedStatus')} "
              f"reason={m.get('instrumentReason')}", file=out)
    print("=" * 74, file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
