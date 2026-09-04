using System.Text.RegularExpressions;
using FluentAssertions;
using Xunit;
using Xunit.Abstractions;

namespace BankerCopilotTests.Contracts;

/// <summary>
/// The §10 criteria that are phrased as "verified by a repo grep gate in CI".
///
/// There is no CI workflow in this repository that builds or tests any .NET project (see the
/// ci-workflow entry in pending-integration.manifest.json), so "a grep gate in CI" does not
/// currently exist. These tests are that gate, living where it can at least be executed. That is
/// a weaker position than CI — nothing forces them to run — and it should not be mistaken for
/// the criterion being met.
/// </summary>
public sealed class RepoGateTests(ITestOutputHelper output)
{
    private static readonly string RepoRoot = FindRepoRoot();

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, ".git")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new DirectoryNotFoundException("Repository root not found.");
    }

    private static IEnumerable<string> SourceFiles(string relativeDir, params string[] patterns)
    {
        var root = Path.Combine(RepoRoot, relativeDir);
        if (!Directory.Exists(root)) yield break;

        foreach (var pattern in patterns)
        {
            foreach (var file in Directory.EnumerateFiles(root, pattern, SearchOption.AllDirectories))
            {
                if (file.Contains($"{Path.DirectorySeparatorChar}obj{Path.DirectorySeparatorChar}") ||
                    file.Contains($"{Path.DirectorySeparatorChar}bin{Path.DirectorySeparatorChar}") ||
                    file.Contains($"{Path.DirectorySeparatorChar}node_modules{Path.DirectorySeparatorChar}"))
                {
                    continue;
                }

                yield return file;
            }
        }
    }

    [Fact]
    public void There_are_no_money_thresholds_hardcoded_in_the_authority_service()
    {
        // §10: "Zero thresholds in application code."
        //
        // The rule this looks for is a currency-shaped constant compared against something. It is
        // deliberately narrow: a broad "no numeric literals" scan would drown in array indexes and
        // HTTP status codes, get muted, and then catch nothing at all. A gate that is turned off
        // is worse than one with a stated blind spot.
        var offenders = new List<string>();
        var moneyLiteral = new Regex(@"[<>=]=?\s*\d{4,}(\.\d+)?m?\b|\b\d{4,}(\.\d+)?m\b");

        foreach (var file in SourceFiles("src/authority-service", "*.cs"))
        {
            var lines = File.ReadAllLines(file);

            for (var i = 0; i < lines.Length; i++)
            {
                var line = lines[i];
                var trimmed = line.TrimStart();

                if (trimmed.StartsWith("//") || trimmed.StartsWith("///") || trimmed.StartsWith("*"))
                    continue;

                // Time and size constants are not authority thresholds.
                if (Regex.IsMatch(line, @"Milliseconds|Seconds|TimeSpan|Timeout|Delay|Capacity|BufferSize|StatusCode|Port"))
                    continue;

                if (moneyLiteral.IsMatch(line))
                    offenders.Add($"{Path.GetRelativePath(RepoRoot, file)}:{i + 1}: {trimmed}");
            }
        }

        foreach (var o in offenders) output.WriteLine(o);

        offenders.Should().BeEmpty(
            "every authority threshold must be a named threshold resolved from policy config; a " +
            "literal in code cannot be overridden, cannot be shown on GET /api/authority/policy, " +
            "and silently disagrees with the file operators think is authoritative");
    }

    [Fact]
    public void No_field_or_index_routes_an_approval_to_a_named_co_signer()
    {
        // §10 / §5.2.2: "No named co-signer anywhere." The supervisor queue is keyed on required
        // seniority only, so a banker cannot choose — or learn — who reviews their work.
        //
        // Note what is NOT an offender: `mustDifferFrom` names an EXCLUDED identity. Excluding a
        // specific person narrows the reviewer pool without selecting from it, which is the
        // opposite operation and the one separation of duties requires.
        var forbidden = new Regex(
            @"\b(assignedTo|assignedSupervisor|targetSupervisor|routeTo|reviewerId|approverId|" +
            @"AssignedTo|AssignedSupervisor|TargetSupervisor|RouteTo|ReviewerId|ApproverId)\b");

        var offenders = new List<string>();

        foreach (var file in SourceFiles("src/authority-service", "*.cs")
                     .Concat(SourceFiles("infra/cloud", "*.tf")))
        {
            var lines = File.ReadAllLines(file);

            for (var i = 0; i < lines.Length; i++)
            {
                if (forbidden.IsMatch(lines[i]))
                    offenders.Add($"{Path.GetRelativePath(RepoRoot, file)}:{i + 1}: {lines[i].Trim()}");
            }
        }

        foreach (var o in offenders) output.WriteLine(o);

        offenders.Should().BeEmpty(
            "naming a co-signer lets the requester influence their own review; the queue must be " +
            "keyed on required seniority alone");
    }

    [Fact]
    public void The_mustDifferFrom_mechanism_is_an_exclusion_not_an_assignment()
    {
        // Anti-vacuous companion to the test above. If `mustDifferFrom` were ever populated with
        // the intended REVIEWER rather than the excluded requester, the previous test would still
        // pass — the field name is on neither list — while the property it protects was inverted.
        var evaluator = Path.Combine(RepoRoot, "src", "authority-service", "Policy", "PolicyEvaluator.cs");

        if (!File.Exists(evaluator))
        {
            output.WriteLine("PENDING: PolicyEvaluator.cs not found.");
            return;
        }

        var text = File.ReadAllText(evaluator);

        text.Should().Contain("MustDifferFrom = [context.Actor.UserId]",
            "the co-signer slot must exclude the ACTOR — the person proposing — and nothing else");
        text.Should().NotMatchRegex(@"MustDifferFrom\s*=\s*\[\s*[^\]]*[Ss]upervisor",
            "populating the exclusion list with a supervisor identity would turn an exclusion " +
            "into an assignment");
    }

    [Fact]
    public void No_expired_lifecycle_state_exists_anywhere_in_the_services()
    {
        // §10: "There is no `expired` state anywhere in the codebase; a grep gate enforces it."
        //
        // Scoped to lifecycle usage, not the word: `expiresAt`, `ApprovalExpired` (the audit
        // event, which §5.5 explicitly keeps) and `IsExpired` are all correct and required.
        var stateUsage = new Regex(
            @"ApprovalStatus\.Expired|""expired""|'expired'|Status\s*==\s*Expired|status:\s*expired");

        var offenders = new List<string>();

        foreach (var file in SourceFiles("src/authority-service", "*.cs")
                     .Concat(SourceFiles("src/event-processor", "*.go")))
        {
            var lines = File.ReadAllLines(file);

            for (var i = 0; i < lines.Length; i++)
            {
                var trimmed = lines[i].TrimStart();
                if (trimmed.StartsWith("//") || trimmed.StartsWith("///")) continue;

                // An error message that TELLS the caller there is no 'expired' state is the gate
                // working, not a violation. Narrowed after a false positive on
                // ApprovalsController's own validation message — a gate that flags the code
                // explaining the rule is a gate people delete.
                if (lines[i].Contains("there is no", StringComparison.OrdinalIgnoreCase) ||
                    lines[i].Contains("no longer", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                if (stateUsage.IsMatch(lines[i]))
                    offenders.Add($"{Path.GetRelativePath(RepoRoot, file)}:{i + 1}: {trimmed}");
            }
        }

        foreach (var o in offenders) output.WriteLine(o);

        offenders.Should().BeEmpty(
            "expiry collapsed into denied + TTL_EXPIRED; a resurrected `expired` state would " +
            "make a timed-out approval stop counting as a denial");
    }

    [Fact]
    public void The_audit_event_for_expiry_still_exists_because_states_collapsed_but_events_did_not()
    {
        // The positive control for the gate above, and the distinction §5.1.1 turns on: collapse
        // the state machine, never collapse the explanation. A gate that also removed
        // ApprovalExpired would be over-broad in a way that destroys auditability, and it would
        // look identical in a green build.
        var found = SourceFiles("src/authority-service", "*.cs")
            .Any(f => File.ReadAllText(f).Contains("ApprovalExpired"));

        found.Should().BeTrue(
            "expiry must remain a differentiated audit event even though it is no longer a state");
    }

    [Fact]
    public void The_approval_document_body_is_defined_in_exactly_one_artifact()
    {
        // §10 / §5.2: a CI check fails if a copilot-approvals document body reappears in the epic.
        // Two copies of a schema is one copy and one lie, and the second one is always the one
        // somebody implements from.
        var epic = Path.Combine(RepoRoot, "docs", "epics", "banker-copilot.md");
        if (!File.Exists(epic)) return;

        var text = File.ReadAllText(epic);
        var offenders = new List<string>();

        foreach (Match block in Regex.Matches(text, "```(?:json|jsonc)\\s*(.*?)```", RegexOptions.Singleline))
        {
            var body = block.Groups[1].Value;

            // A document BODY is recognisable by carrying several of the approval's own fields —
            // not by mentioning the container name, which prose legitimately does.
            var markers = new[] { "payloadHash", "policyVersion", "terminalReason", "signatures", "requiredRung" };
            var hits = markers.Count(m => body.Contains(m, StringComparison.Ordinal));

            if (hits >= 4) offenders.Add(body.Trim()[..Math.Min(160, body.Trim().Length)]);
        }

        foreach (var o in offenders) output.WriteLine("DUPLICATE SCHEMA BLOCK:\n" + o + "\n");

        offenders.Should().BeEmpty(
            "the approval schema lives in docs/design/banker-copilot-policy-engine.md §5.3 only");
    }

    [Fact]
    public void The_denial_reason_bounds_are_not_literals_in_the_validator()
    {
        // Q3's rule set is config-driven. A literal 20 in the validator would mean the deployed
        // bound cannot be known from configuration, and could not be tightened without a release.
        var validator = Path.Combine(
            RepoRoot, "src", "authority-service", "Services", "DenialReasonValidator.cs");

        if (!File.Exists(validator)) return;

        var lines = File.ReadAllLines(validator);
        var offenders = new List<string>();

        for (var i = 0; i < lines.Length; i++)
        {
            var trimmed = lines[i].TrimStart();
            if (trimmed.StartsWith("//") || trimmed.StartsWith("///")) continue;
            if (trimmed.Contains("Denial:Reason")) continue;

            // `words.Length >= 3` guards whether a heuristic APPLIES; it is not a bound on the
            // reason itself. Flagging it was over-breadth on my part. Recording the exemption
            // rather than widening it silently: if a real bound is ever written as a comparison
            // against a local named `words`, this gate will miss it.
            if (trimmed.Contains("words", StringComparison.Ordinal)) continue;

            if (Regex.IsMatch(lines[i], @"(Length|Count|Distinct|Repeat|Letters)\s*[<>]=?\s*\d+"))
                offenders.Add($"{i + 1}: {trimmed}");
        }

        foreach (var o in offenders) output.WriteLine(o);

        offenders.Should().BeEmpty("denial-reason bounds must come from configuration only");
    }
}
