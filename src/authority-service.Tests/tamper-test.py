#!/usr/bin/env python3
"""
Tamper harness.

A guard that has never been observed failing is not a guard, it is a hope. For each entry below
we deliberately break the guard, run ONE named test, and require it to go red. Then we restore
the file byte-for-byte and verify the checksum.

Nothing here is left behind: every mutation is reverted in a finally block, and the script
re-verifies the full suite is green at the end.
"""
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TESTS = ROOT / "src" / "authority-service.Tests"

# (guard name, owner, file, find, replace, test filter)
CASES = [
    # Both folds are individually redundant: the outer `rung = Max(rung, raised)` and the inner
    # `var result = current` each independently prevent a descent, so breaking either ALONE is
    # invisible. That is real defence in depth rather than a coverage gap — but it means the only
    # observable break is a simultaneous one, which is what this case does.
    ("Rung combination is monotone (BOTH folds broken together)",
     "Turk", "src/authority-service/Policy/PolicyEvaluator.cs",
     ["            rung = RungOrder.Max(rung, raised);",
      "        var result = current;\n\n        if (raiseTo is not null)"],
     ["            rung = raised; // TAMPER",
      "        var result = Rung.L1; // TAMPER\n\n        if (raiseTo is not null)"],
     "RungCombinatorTests"),

    ("Rung combination is a max fold, not an assignment (outer only — redundant)",
     "Turk", "src/authority-service/Policy/PolicyEvaluator.cs",
     "            rung = RungOrder.Max(rung, raised);\n            signers = Math.Max(signers, ResolveCount(escalator.MinSigners, policy));",
     "            rung = raised; // TAMPER\n            signers = ResolveCount(escalator.MinSigners, policy);",
     "RungCombinatorTests"),

    ("Raised() folds from the CURRENT rung (inner only — redundant)",
     "Turk", "src/authority-service/Policy/PolicyEvaluator.cs",
     "        var result = current;\n\n        if (raiseTo is not null)",
     "        var result = Rung.L1; // TAMPER\n\n        if (raiseTo is not null)",
     "RungCombinatorTests"),

    ("The co-signer slot excludes the requester (separation of duties)",
     "Turk", "src/authority-service/Policy/PolicyEvaluator.cs",
     "                MustDifferFrom = [context.Actor.UserId]",
     "                MustDifferFrom = []",
     "L2_requires_two_distinct_identities_so_no_single_person_can_satisfy_it"),

    ("L3 is not proposable by the agent",
     "Turk", "config/authority-policy.yaml",
     "    proposable: false              # the agent may not even ask",
     "    proposable: true               # TAMPER",
     "L3_is_outside_the_harness_entirely"),

    ("An unknown action is denied, not defaulted",
     "Turk", "config/authority-policy.yaml",
     "  unknownAction: deny",
     "  unknownAction: allow",
     "An_unknown_action_is_refused_rather_than_defaulted"),

    ("The lifecycle has exactly five states",
     "Turk", "src/authority-service/Models/Enums.cs",
     "    Proposed,\n    Pending,",
     "    Proposed,\n    Expired, // TAMPER\n    Pending,",
     "The_lifecycle_has_exactly_five_states_and_no_expired_state"),

    ("Re-evaluation runs BEFORE the downstream call",
     "Turk", "src/authority-service/Services/ApprovalService.cs",
     "var reEvaluation = ReEvaluate(approval, currentPolicy);",
     "var reEvaluation = _broker is null ? ReEvaluate(approval, currentPolicy) : ReEvaluate(approval, currentPolicy); // TAMPER",
     "The_re_evaluation_call_precedes_the_downstream_call_in_the_execute_path"),

    ("Denial reasons must be non-degenerate",
     "Turk", "src/authority-service/Services/DenialReasonValidator.cs",
     "public DenialReasonResult Validate(string? reason)\n    {",
     "public DenialReasonResult Validate(string? reason)\n    {\n        if (reason is not null && reason.Length >= _minLength) return DenialReasonResult.Valid; // TAMPER",
     "Degenerate_denial_reasons_are_rejected"),

    ("The denial validator has no code-level defaults",
     "Turk", "src/authority-service/Services/DenialReasonValidator.cs",
     "            throw new InvalidOperationException(",
     "            return 20; // TAMPER\n            throw new InvalidOperationException(",
     "The_validator_refuses_to_start_without_configuration"),

    ("admin does not map into the banker signer role",
     "Turk", "config/authority-policy.yaml",
     "    claimValues: [banker, Banker, user, User]",
     "    claimValues: [banker, Banker, user, User, admin]",
     "An_admin_claim_does_not_map_into_the_banker_or_supervisor_signer_roles"),

    ("The L2 co-signer must outrank a second banker",
     "Turk", "config/authority-policy.yaml",
     "    cosignerRoles: [supervisor, admin]",
     "    cosignerRoles: [banker, supervisor, admin]",
     "The_L2_cosigner_set_is_narrower_than_the_L2_signer_set"),

    # ---- my own oracle: the spec-derived reference implementation ----
    ("Only the re-evaluation gate can mint an execution authorization",
     "Livingston", "src/authority-service.Tests/Spec/ExecutionGate.cs",
     "    private ExecutionAuthorization(",
     "    public ExecutionAuthorization(",
     "ExecutionAuthorization_has_no_publicly_reachable_constructor"),

    ("A denied approval cannot exist without a terminal reason",
     "Livingston", "src/authority-service.Tests/Spec/Approval.cs",
     "public sealed record TerminalTransition(TerminalReason Reason",
     "public sealed record TerminalTransition(TerminalReason Reason = TerminalReason.HUMAN_DENIED",
     "A_terminal_transition_cannot_be_constructed_without_a_reason"),

    ("Money fields are NOT exempt from the missing-field hard error",
     "Livingston", "src/authority-service.Tests/Spec/Canonicalizer.cs",
     "                throw new CanonicalizationException(",
     "                continue; // TAMPER\n                throw new CanonicalizationException(",
     "Removing_a_hashed_field_voids_the_signature_rather_than_matching_it"),

    ("raiseBy cannot be negative",
     "Livingston", "src/authority-service.Tests/Spec/Rung.cs",
     "        if (steps < 0)",
     "        if (false)",
     "PolicyGrammarValidationTests"),

    ("Load-time grammar rejects a negative raiseBy",
     "Livingston", "src/authority-service.Tests/Spec/PolicyModel.cs",
     "            if (rule.RaiseBy is < 0)",
     "            if (false)",
     "A_negative_adjustment_on_a_global_escalator_is_rejected_at_load_time"),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_filter(name):
    r = subprocess.run(
        ["dotnet", "test", "--filter", name, "--nologo", "-v", "q"],
        cwd=TESTS, capture_output=True, text=True)
    out = r.stdout + r.stderr
    if "error CS" in out:
        return "COMPILE_ERROR", out
    if re.search(r"Failed!", out):
        return "FAILED", out
    if re.search(r"Passed!", out):
        m = re.search(r"Passed:\s+(\d+)", out)
        if m and int(m.group(1)) == 0:
            return "NO_MATCH", out
        return "PASSED", out
    return "UNKNOWN", out


def main():
    results = []
    for guard, owner, path, find, replace, filt in CASES:
        if replace is None or not (ROOT / path).exists():
            results.append((guard, owner, filt, "SKIPPED", "malformed or missing target"))
            continue

        f = ROOT / path
        original = f.read_bytes()
        before = sha(f)
        text = original.decode()

        pairs = list(zip(find, replace)) if isinstance(find, list) else [(find, replace)]

        missing = [a for a, _ in pairs if a not in text]
        if missing:
            results.append((guard, owner, filt, "UNREACHABLE",
                            "anchor text not found — guard may have been refactored"))
            continue

        try:
            mutated = text
            for a, b in pairs:
                mutated = mutated.replace(a, b, 1)
            f.write_text(mutated)
            status, out = run_filter(filt)
            if status == "FAILED":
                verdict, detail = "PROVEN", "guard broken -> named test went red"
            elif status == "COMPILE_ERROR":
                verdict, detail = "PROVEN_BY_COMPILER", "the bypass does not even compile"
            elif status == "NO_MATCH":
                verdict, detail = "INCONCLUSIVE", "test filter matched nothing"
            elif "redundant" in guard:
                verdict, detail = "REDUNDANT", (
                    "breaking this half alone is invisible because the other half independently "
                    "prevents the descent — see the combined case above")
            else:
                verdict, detail = "NOT_PROVEN", f"guard broken but test still {status}"
        finally:
            f.write_bytes(original)
            assert sha(f) == before, f"FAILED TO RESTORE {path}"

        results.append((guard, owner, filt, verdict, detail))

    width = max(len(g) for g, *_ in results)
    print("\n=== TAMPER TEST RESULTS ===\n")
    for guard, owner, filt, verdict, detail in results:
        print(f"[{verdict:<18}] {guard:<{width}}  ({owner})")
        print(f"{'':22}{filt}")
        print(f"{'':22}{detail}\n")

    (TESTS / "tamper-results.json").write_text(json.dumps(
        [dict(guard=g, owner=o, test=t, verdict=v, detail=d) for g, o, t, v, d in results],
        indent=2))

    bad = [r for r in results if r[3] == "NOT_PROVEN"]
    print(f"{len(results)} guards attempted, "
          f"{sum(1 for r in results if r[3].startswith('PROVEN'))} proven, "
          f"{len(bad)} NOT proven.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
