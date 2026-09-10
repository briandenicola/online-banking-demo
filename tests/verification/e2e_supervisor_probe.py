"""Check 4.2 — the END-TO-END agreement probe.

Drives real copilot runs against the live deployment and measures whether the supervisor's
blind second opinion genuinely diverges from the primary's.

This is the path the README asks for and the component probe could not take: every run goes
through ``POST /api/copilot/sessions/{id}/runs``, the copilot gathers its own evidence, the
authority policy admits an L2 approval, and the supervisor re-reads the account itself. Nothing
is stubbed. The verdict is read out of the ``approval.updated`` trace frame at
``payload.approval.agentAssessment.supervisor`` — the same bytes the approval card renders.

It PROPOSES only. Every run leaves a pending approval and signs nothing.

Success is a positive signal, never an absence of errors
--------------------------------------------------------
A run counts only if its trace carries ALL THREE of an ``approval.required`` frame with
``requiredRung == "L2"``, a ``subagent.spawned`` frame with ``role == "supervisor"``, and a
``subagent.completed`` frame.

**``run.done.status`` is NEVER consulted to admit a run, because on the build this was first
measured against it lies.** The planner opened with ``status = "completed"`` and only lowered it
where a path remembered to. The tool-failure path remembered; the **propose** path did not. So a
run whose proposal was REFUSED — no approval produced, nothing for a human to sign — reports
``run.done {"status": "completed"}`` and even emits ``step.completed`` on the step that just
errored. ``start_run``'s ``finally`` block also hardcoded ``completed``, so a planner that RAISED
was recorded as completed too, and that is the field ``GET /api/copilot/runs/{id}`` returns.

Reproduced live as ``run_9291617d3bc44032``: ``run.error payload_not_canonicalizable`` at seq 15,
``step.completed`` on the failed step at seq 16, ``run.done status=completed`` at seq 17, and the
summary endpoint reporting ``"status":"completed"``. The field is read here only to flag the
contradiction (``statusFieldLied``), never to grade.

Four outcomes, never two
------------------------
``agree``        supervisor said proceed; the primary proposed, so its position is proceed
``disagree``     supervisor said hold or decline — a real model verdict against the action
``unavailable``  ``keyFactors == ["supervisor_unavailable"]`` AND ``confidence == 0.0``.
                 ``FoundryDecider`` fails CLOSED, so a timeout, a throttle, a content-filter
                 refusal and unparseable output ALL surface as ``hold`` at 0.0. That is a
                 FAILED SUPERVISOR CALL. Counting it as disagreement manufactures the exact
                 false signal this exercise exists to delete, sign flipped.
``instrument``   THE MEASUREMENT DID NOT HAPPEN: a ``run.error`` frame anywhere, a missing
                 fan-out signal, or a transport failure. A defect in the rig, not an opinion
                 about banking — and deliberately distinct from ``unavailable``, which is the
                 supervisor failing rather than the instrument.

Only ``agree`` and ``disagree`` enter the agreement-rate denominator.

Both halves of the marker are checked. Testing the marker alone would misclassify a genuine
model verdict that happened to name that factor; testing confidence alone would swallow any
real 0.0-confidence opinion.

Subjects are resolved, never pinned
-----------------------------------
The corpus names its accounts by stable handle (``owner:accountType``), and this probe turns
those into live ids at startup via ``seed_subjects.resolve_subjects`` — logging in as each
OWNING customer and reading ``GET /api/accounts``, the same convention ``scripts/demo/demo.sh``
uses. Resolution happens BEFORE any run is driven and a failure is fatal, so a run can never
be driven against an account id left over from a previous seed.

Usage
-----
    python e2e_supervisor_probe.py --base https://host --user banker --password '...' \
        --out results.jsonl [--only CASE_ID,...] [--stability]

    # READ-ONLY. Resolves every subject, checks the corpus against the live dual-control
    # threshold, prints the plan and exits. Drives nothing, creates no approvals.
    python e2e_supervisor_probe.py --base https://host --user banker --password '...' \
        --resolve-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from e2e_cases import (  # noqa: E402
    CASES, STABILITY_CASE_IDS, STABILITY_REPEATS,
    assert_amounts_reach_dual_control, required_handles, resolve_cases,
)
from seed_subjects import resolve_subjects, seed_password, verify_ledgers  # noqa: E402

ACTION_ID = "account.balance.adjust"
PRIMARY_RECOMMENDATION = "proceed"
UNAVAILABLE_MARKER = "supervisor_unavailable"
POLL_TIMEOUT_S = 90
POLL_INTERVAL_S = 2.0


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def _request(method: str, url: str, token: str | None = None, body: dict | None = None,
             timeout: int = 60) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:500]}


def login(base: str, username: str, password: str) -> str:
    status, body = _request("POST", f"{base}/api/auth/login",
                            body={"username": username, "password": password})
    if status != 200 or not isinstance(body, dict) or "token" not in body:
        raise SystemExit(f"login failed: HTTP {status} {str(body)[:300]}")
    return body["token"]


# ---------------------------------------------------------------------------
# one run
# ---------------------------------------------------------------------------

def drive_case(base: str, token: str, case: dict, rep: int = 0) -> dict:
    row: dict = {
        "caseId": case["id"], "rep": rep, "action": ACTION_ID,
        "expectation": case["expectation"], "polarity": case["polarity"],
        "grounded": case["grounded"], "amount": case["amount"],
        "direction": case["direction"], "account": case["account"],
        "subject": case["subject"], "subjectOwner": case.get("subjectOwner"),
        "subjectAccountType": case.get("subjectAccountType"),
        "objective": case["objective"], "primaryRecommendation": PRIMARY_RECOMMENDATION,
    }

    status, body = _request("POST", f"{base}/api/copilot/sessions", token,
                            {"objective": case["objective"]})
    if status not in (200, 201) or not isinstance(body, dict) or "sessionId" not in body:
        row["outcome"] = "instrument"
        row["instrumentReason"] = f"session create HTTP {status}: {str(body)[:300]}"
        return row
    row["sessionId"] = body["sessionId"]

    started = time.monotonic()
    status, body = _request("POST", f"{base}/api/copilot/sessions/{row['sessionId']}/runs", token,
                            {"actionId": ACTION_ID,
                             "payload": {"accountId": case["account"],
                                         "amount": case["amount"],
                                         "direction": case["direction"],
                                         "reason": case["reason"]}})
    if status not in (200, 201, 202) or not isinstance(body, dict) or "runId" not in body:
        row["outcome"] = "instrument"
        row["instrumentReason"] = f"run create HTTP {status}: {str(body)[:300]}"
        return row
    row["runId"] = body["runId"]

    frames = _poll_trace(base, token, row["runId"])
    row["elapsedMs"] = int((time.monotonic() - started) * 1000)
    if frames is None:
        row["outcome"] = "instrument"
        row["instrumentReason"] = "trace did not reach a terminal frame within the poll timeout"
        return row

    return _grade(row, frames)


def _poll_trace(base: str, token: str, run_id: str) -> list[dict] | None:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        status, body = _request("GET", f"{base}/api/copilot/runs/{run_id}/trace", token)
        if status == 200 and isinstance(body, dict):
            frames = body.get("frames") or []
            kinds = {f.get("kind") for f in frames}
            if "run.done" in kinds or "run.error" in kinds:
                return frames
        time.sleep(POLL_INTERVAL_S)
    return None


def _grade(row: dict, frames: list[dict]) -> dict:
    by_kind = defaultdict(list)
    for f in frames:
        by_kind[f.get("kind")].append(f)

    # `run.done.status` is NOT consulted to admit a run. On the build this was first measured
    # against it is a LIE: the planner opened with "completed" and only lowered it where a path
    # remembered to, and the PROPOSE path did not. A run whose proposal was refused — no
    # approval, nothing to sign — reports `run.done {"status": "completed"}` and even emits
    # `step.completed` on the step that just errored. Reproduced live: run_9291617d3bc44032.
    # It is recorded here only as evidence of that defect, never as grounds for admitting.
    done = by_kind.get("run.done", [])
    row["claimedStatus"] = (done[-1].get("payload") or {}).get("status") if done else None

    errors = by_kind.get("run.error", [])
    row["statusFieldLied"] = bool(errors) and row["claimedStatus"] == "completed"
    if errors:
        row["outcome"] = "instrument"
        row["instrumentReason"] = "run.error frame present"
        row["error"] = json.dumps(errors[0].get("payload"))[:400]
        return row

    # POSITIVE success signal. All three required; absence of errors proves nothing.
    required = [f for f in by_kind.get("approval.required", [])
                if ((f.get("payload") or {}).get("approval") or {}).get("requiredRung") == "L2"]
    spawned = [f for f in by_kind.get("subagent.spawned", [])
               if (f.get("payload") or {}).get("role") == "supervisor"]
    supervisor_done = by_kind.get("subagent.completed", [])
    row["reachedL2"] = bool(required)
    row["supervisorSpawned"] = bool(spawned)
    row["supervisorCompleted"] = bool(supervisor_done)
    if not (required and spawned and supervisor_done):
        row["outcome"] = "instrument"
        row["instrumentReason"] = (f"reachedL2={bool(required)} spawned={bool(spawned)} "
                                   f"completed={bool(supervisor_done)}")
        row["statusFieldLied"] = row["claimedStatus"] == "completed"
        return row

    if required:
        appr = (required[-1].get("payload") or {}).get("approval") or {}
        row["approvalId"] = appr.get("id")
        row["firedEscalators"] = [e.get("key") for e in appr.get("firedEscalators") or []]

    updated = by_kind.get("approval.updated", [])
    if not updated:
        row["outcome"] = "instrument"
        row["instrumentReason"] = "supervisor spawned but no approval.updated carried its opinion"
        return row

    approval = (updated[-1].get("payload") or {}).get("approval") or {}
    assessment = approval.get("agentAssessment") or {}
    sup = assessment.get("supervisor") or {}
    pri = assessment.get("primary") or {}

    factors = [f.get("label") if isinstance(f, dict) else f for f in sup.get("keyFactors") or []]
    verdict = str(sup.get("verdict") or "").strip()
    confidence = sup.get("confidence")

    row.update({
        "supervisorVerdict": verdict,
        "confidence": confidence,
        "keyFactors": factors,
        # The wire's supervisor `rationale` IS `opinion.strongest_counter_argument`
        # (fanout.py passes it positionally into supervisor_wire_assessment).
        "strongestCounterArgument": sup.get("rationale"),
        "supervisorCitedEvidence": sup.get("citedEvidenceIds"),
        "primaryVerdict": pri.get("verdict"),
        "primaryRationale": pri.get("rationale"),
        "primaryConfidence": pri.get("confidence"),
        "primaryKeyFactors": pri.get("keyFactors"),
    })

    # Failed model call before anything else: FoundryDecider fails closed as `hold`/0.0,
    # which is indistinguishable from a real hold on the verdict token alone.
    if factors == [UNAVAILABLE_MARKER] and confidence == 0.0:
        row["outcome"] = "unavailable"
        return row

    row["outcome"] = "agree" if verdict.casefold() == PRIMARY_RECOMMENDATION else "disagree"
    return row


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def summarise(results: list[dict], label: str) -> None:
    out = sys.stderr
    counts = Counter(r["outcome"] for r in results)
    agree, disagree = counts["agree"], counts["disagree"]
    unavailable = counts["unavailable"]
    instrument = counts["instrument"]
    liars = sum(1 for r in results if r.get("statusFieldLied"))
    verdicts = agree + disagree

    print("\n" + "=" * 74, file=out)
    print(f"CHECK 4.2 — END-TO-END SUPERVISOR AGREEMENT ({label})", file=out)
    print("-" * 74, file=out)
    print(f"runs driven                {len(results)}", file=out)
    print(f"  agreed (proceed)         {agree}", file=out)
    print(f"  disagreed (hold/decline) {disagree}", file=out)
    print(f"  supervisor-unavailable   {unavailable}   FAILED MODEL CALLS, not disagreement",
          file=out)
    print(f"  instrument failures      {instrument}   the measurement did not happen", file=out)
    if liars:
        print(f"    of which claimed run.done status='completed' while carrying a", file=out)
        print(f"    run.error or missing the fan-out: {liars}  <-- planner status defect", file=out)
    print("-" * 74, file=out)
    if verdicts:
        print(f"AGREEMENT RATE  {agree}/{verdicts} = {agree / verdicts:.1%}", file=out)
        print(f"  denominator = real model verdicts only; excludes {unavailable} failed "
              f"supervisor call(s) and {instrument} instrument failure(s)", file=out)
    else:
        print("AGREEMENT RATE  undefined — no real model verdicts", file=out)
    print("=" * 74, file=out)

    graded = [r for r in results if r["outcome"] in ("agree", "disagree")]

    print("\nBy expectation (what a competent reviewer should conclude):", file=out)
    for exp in ("proceed", "stop", "ambiguous"):
        sub = [r for r in graded if r.get("expectation") == exp]
        if not sub:
            continue
        withheld = sum(1 for r in sub if r["outcome"] == "disagree")
        print(f"  {exp:<10} n={len(sub):<3} supervisor withheld on {withheld}"
              f"  ({withheld / len(sub):.0%})", file=out)

    print("\nBy polarity (adverse = the action takes money AWAY from the customer):", file=out)
    for pol in ("adverse", "permissive"):
        sub = [r for r in graded if r.get("polarity") == pol]
        if not sub:
            continue
        withheld = sum(1 for r in sub if r["outcome"] == "disagree")
        print(f"  {pol:<10} n={len(sub):<3} supervisor withheld on {withheld}"
              f"  ({withheld / len(sub):.0%})", file=out)

    print("\nADVERSE + expectation=proceed — the polarity regression slice.", file=out)
    print("  Under the pre-ef61d7b bug the supervisor judged a verb it inferred from prose,", file=out)
    print("  so it declined adverse actions that were correct. Withholding here is the tell:", file=out)
    slice_ = [r for r in graded if r.get("polarity") == "adverse" and r.get("expectation") == "proceed"]
    for r in slice_:
        print(f"    {r['caseId']:<42} {r['supervisorVerdict']:<8} conf={r.get('confidence')}", file=out)
    if slice_:
        ok = sum(1 for r in slice_ if r["outcome"] == "agree")
        print(f"    -> proceeded on {ok}/{len(slice_)} correct adverse actions", file=out)

    print("\nBy grounding (are the framing's factual claims TRUE against the live ledger?):",
          file=out)
    for g in (True, False):
        sub = [r for r in graded if r.get("grounded") is g]
        if not sub:
            continue
        withheld = sum(1 for r in sub if r["outcome"] == "disagree")
        print(f"  grounded={str(g):<5} n={len(sub):<3} supervisor withheld on {withheld}"
              f"  ({withheld / len(sub):.0%})", file=out)

    confs = sorted(r["confidence"] for r in graded if isinstance(r.get("confidence"), (int, float)))
    if confs:
        mid = len(confs) // 2
        median = confs[mid] if len(confs) % 2 else (confs[mid - 1] + confs[mid]) / 2
        print(f"\nConfidence over {len(confs)} real verdicts: "
              f"min={confs[0]} median={median} max={confs[-1]} "
              f"mean={sum(confs) / len(confs):.3f}", file=out)
        print("  distribution: " + json.dumps(dict(sorted(Counter(confs).items()))), file=out)

    counters = [r.get("strongestCounterArgument") for r in graded
                if r.get("strongestCounterArgument")]
    if counters:
        print(f"\nCounter-arguments: {len(set(counters))} distinct of {len(counters)}",
              file=out)


def summarise_stability(results: list[dict]) -> None:
    out = sys.stderr
    print("\n" + "=" * 74, file=out)
    print("BYTE-IDENTICAL REPEATS — determinism", file=out)
    print("-" * 74, file=out)
    for case_id in sorted({r["caseId"] for r in results}):
        sub = [r for r in results if r["caseId"] == case_id]
        verdicts = Counter(r.get("supervisorVerdict") or r["outcome"] for r in sub)
        confs = [r.get("confidence") for r in sub if isinstance(r.get("confidence"), (int, float))]
        stable = "STABLE" if len(verdicts) == 1 else "*** FLIPPED ***"
        print(f"  {case_id}", file=out)
        print(f"    n={len(sub)}  {dict(verdicts)}  {stable}", file=out)
        if confs:
            print(f"    confidence: {confs}", file=out)
    print("=" * 74, file=out)


# ---------------------------------------------------------------------------

def dual_control_threshold(base: str, token: str) -> float | None:
    """The LIVE ``balance_adjustment_dual_control_amount``, or None if it cannot be read.

    Read rather than restated. A case below this line settles at L1, never fans out, and
    produces an instrument failure that reads like a service defect instead of a corpus defect.
    """
    status, body = _request("GET", f"{base}/api/authority/policy", token)
    if status != 200 or not isinstance(body, dict):
        return None
    thresholds = body.get("thresholds")
    if isinstance(thresholds, list):
        for entry in thresholds:
            if isinstance(entry, dict) and entry.get("name") == "balance_adjustment_dual_control_amount":
                try:
                    return float(entry.get("value"))
                except (TypeError, ValueError):
                    return None
    elif isinstance(thresholds, dict):
        try:
            return float(thresholds.get("balance_adjustment_dual_control_amount"))
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="https://onlinebankingdemo.bjdazure.tech")
    p.add_argument("--user", default="banker")
    p.add_argument("--password", default=os.environ.get("BANKER_PASSWORD", ""))
    p.add_argument("--seed-password", default="",
                   help="Password for the seeded CUSTOMER logins used to resolve subject "
                        "accounts. Defaults to the demo dataset's credentials block.")
    p.add_argument("--out", default="e2e-results.jsonl")
    p.add_argument("--only", default="")
    p.add_argument("--stability", action="store_true",
                   help="Run STABILITY_CASE_IDS x STABILITY_REPEATS on byte-identical input.")
    p.add_argument("--resolve-only", action="store_true",
                   help="READ-ONLY. Resolve every subject handle against the live deployment, "
                        "check the corpus against the live dual-control threshold, print the "
                        "plan and exit WITHOUT driving any run. Creates no approvals and "
                        "writes nothing to the environment.")
    args = p.parse_args()

    if not args.password:
        print("REFUSING: no password (--password or $BANKER_PASSWORD).", file=sys.stderr)
        return 2

    # Subjects are resolved BEFORE anything is driven, and a failure here is fatal. Every id in
    # a payload below is one this run just read back from the live deployment under the owning
    # customer's own token; nothing in the corpus is pinned to a previous seed.
    resolved_subjects = resolve_subjects(args.base,
                                         args.seed_password or seed_password(),
                                         required_handles())
    print("resolved subjects (owner:accountType -> live id):", file=sys.stderr)
    for handle in required_handles():
        subject = resolved_subjects[handle]
        print(f"  {handle:<22} {subject.account_id}  "
              f"balance={subject.balance}  txns={subject.transaction_count}", file=sys.stderr)

    token = login(args.base, args.user, args.password)

    threshold = dual_control_threshold(args.base, token)
    if threshold is None:
        print("WARNING: could not read balance_adjustment_dual_control_amount from the live "
              "policy; corpus amounts were NOT checked against it.", file=sys.stderr)
    else:
        assert_amounts_reach_dual_control(threshold)
        print(f"live balance_adjustment_dual_control_amount={threshold}; all "
              f"{len(CASES)} case amounts clear it", file=sys.stderr)

    cases = resolve_cases(resolved_subjects)

    if args.stability:
        plan = [(c, rep) for c in cases if c["id"] in STABILITY_CASE_IDS
                for rep in range(STABILITY_REPEATS)]
        label = "stability"
    else:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        plan = [(c, 0) for c in cases if not wanted or c["id"] in wanted]
        label = f"{len(plan)} distinct cases"

    if args.resolve_only:
        problems = verify_ledgers(args.base, args.seed_password or seed_password(),
                                  resolved_subjects)
        print("\nledger grounding check (live ledger vs config/demo-dataset.json):",
              file=sys.stderr)
        if problems:
            for problem in problems:
                print(f"  MISMATCH  {problem}", file=sys.stderr)
            print(f"  -> {len(problems)} discrepancy(ies). Every 'grounded' flag in the corpus "
                  "is suspect until these are resolved.", file=sys.stderr)
        else:
            print(f"  OK — all {len(resolved_subjects)} subject ledgers match the contract "
                  "exactly (balances and transaction sets).", file=sys.stderr)

        print(f"\n--resolve-only: {len(plan)} case(s) would be driven. Nothing was sent.",
              file=sys.stderr)
        for case, rep in plan:
            print(f"  {case['id']:<44} {case['subject']:<20} {case['direction']:<6} "
                  f"{case['amount']:>10}  -> {case['account']}", file=sys.stderr)
        return 1 if problems else 0

    print(f"base={args.base} runs={len(plan)}  PROPOSE-ONLY, signs nothing", file=sys.stderr)

    results: list[dict] = []
    with open(args.out, "w", encoding="utf-8") as fh:
        for case, rep in plan:
            try:
                row = drive_case(args.base, token, case, rep)
            except Exception as exc:  # noqa: BLE001 — a harness crash must never read as a verdict
                row = {"caseId": case["id"], "rep": rep, "outcome": "instrument",
                       "instrumentReason": f"{type(exc).__name__}: {exc}"}
            results.append(row)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"  {row['caseId']:<42} r{row.get('rep', 0)} "
                  f"{row['outcome']:<12} {row.get('supervisorVerdict', '-'):<8} "
                  f"conf={row.get('confidence', '-')}", file=sys.stderr)

    if args.stability:
        summarise_stability(results)
    summarise(results, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
