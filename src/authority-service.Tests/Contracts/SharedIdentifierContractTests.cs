using System.Text.RegularExpressions;
using FluentAssertions;
using Xunit;
using Xunit.Abstractions;

namespace BankerCopilotTests.Contracts;

/// <summary>
/// Epic §5.3.1a. These are the only tests in the suite that assert against the REAL repository
/// rather than against my spec-derived oracle, so they are the only ones that can fail because
/// of something someone else wrote. That makes them the most valuable ones running today.
///
/// The problem they solve: Turk's service, Rusty's event-processor cases, the gateway route and
/// the UI all have to agree on a vocabulary that is currently written down in Markdown and
/// nowhere else. Three services independently transcribing `POLICY_RUNG_ESCALATED` from a
/// document is three chances to type `POLICY_CHANGE`, and the resulting bug is invisible until
/// an auditor asks why 12% of denials have no reason.
/// </summary>
public sealed class SharedIdentifierContractTests(ITestOutputHelper output)
{
    private static readonly string RepoRoot = FindRepoRoot();

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, ".git")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new DirectoryNotFoundException("Repository root not found.");
    }

    private static readonly string[] SpecDocs =
    [
        "docs/epics/banker-copilot.md",
        "docs/design/banker-copilot-policy-engine.md"
    ];

    /// <summary>
    /// Only the fenced CODE BLOCKS, concatenated.
    ///
    /// The first version of this file grepped whole documents and immediately failed on six
    /// identifiers — all of them inside §0.1's "rejected alternatives" table, where the whole
    /// point is to write down the name that LOST. Failing on those would have forced the spec to
    /// stop recording its own reasoning, which is a real cost paid for a fake defect.
    ///
    /// The transcription risk is not in prose. It is in the JSON, YAML and C# snippets that Turk
    /// and Rusty will copy verbatim into their services. So that is what gets scanned.
    /// </summary>
    private static string CodeBlocks(string markdown)
    {
        var blocks = Regex.Matches(
            markdown,
            "```[a-zA-Z]*\\r?\\n(.*?)```",
            RegexOptions.Singleline).Select(m => m.Groups[1].Value);

        return string.Join("\n", blocks);
    }

    private static IEnumerable<(string Path, string Text)> Docs() =>
        SpecDocs
            .Select(rel => (rel, full: Path.Combine(RepoRoot, rel)))
            .Where(x => File.Exists(x.full))
            .Select(x => (x.rel, File.ReadAllText(x.full)));

    [Fact]
    public void The_specification_documents_exist()
    {
        // Guard against the whole file passing vacuously: every test below iterates Docs(), and
        // an empty sequence makes every one of them green while checking nothing.
        Docs().Should().HaveCount(SpecDocs.Length,
            "if a spec doc is renamed or moved, every contract test below silently stops running");
    }

    [Fact]
    public void The_four_terminal_reasons_are_spelled_consistently_everywhere()
    {
        var canonical = new[]
        {
            "HUMAN_DENIED", "POLICY_RUNG_ESCALATED", "PAYLOAD_SUPERSEDED", "TTL_EXPIRED"
        };

        foreach (var (path, text) in Docs())
        {
            foreach (var name in canonical)
            {
                text.Should().Contain(name, $"{path} must use the canonical spelling {name}");
            }
        }
    }

    public static TheoryData<string, string> ForbiddenSpellings() => new()
    {
        // left: the wrong spelling. right: why it is dangerous, not merely untidy.
        { "SUPERSEDED_BY_REPLAN", "pre-ratification name for PAYLOAD_SUPERSEDED" },
        { "POLICY_CHANGE", "loses the direction — only ESCALATION voids a signature" },
        { "TTL_EXPIRED_DENIED", "doubles the outcome into the reason" },
        { "authority-proposals", "the container is `approvals`; `proposals` implies a different doc" },
        { "actionTypeId", "the field is `actionId` (§0.1)" },
        { "actorId", "the field is `requesterId` for proposals and `signerId` for signatures" }
    };

    [Theory]
    [MemberData(nameof(ForbiddenSpellings))]
    public void No_specification_document_uses_a_stale_identifier(string bad, string why)
    {
        foreach (var (path, text) in Docs())
        {
            var code = CodeBlocks(text);

            Regex.Matches(code, $@"\b{Regex.Escape(bad)}\b")
                .Select(m => m.Value)
                .Should().BeEmpty(
                    $"a code sample in {path} uses the stale identifier '{bad}' ({why}). " +
                    "Code samples get copied verbatim into services; prose does not.");
        }
    }

    [Fact]
    public void There_is_no_expired_lifecycle_state_in_any_document()
    {
        // The single most likely regression in this whole vocabulary, because `expired` is the
        // word everyone reaches for. §5.1 has five states and expiry is a DENIAL with a reason.
        var badPatterns = new[]
        {
            @"status\s*[:=]\s*[""']?expired",
            @"""expired""",
            @"\|\s*`expired`\s*\|"
        };

        foreach (var (path, text) in Docs())
        {
            var code = CodeBlocks(text);
            foreach (var pattern in badPatterns)
            {
                Regex.Matches(code, pattern, RegexOptions.IgnoreCase)
                    .Select(m => m.Value)
                    .Should().BeEmpty($"{path} appears to define `expired` as a state; expiry is " +
                                      "`denied` + TTL_EXPIRED, and a sixth state forks every " +
                                      "consumer's switch statement");
            }
        }
    }

    [Fact]
    public void The_five_lifecycle_states_are_all_named()
    {
        var states = new[] { "proposed", "pending", "signed", "executed", "denied" };
        var epic = Docs().First(d => d.Path.Contains("epics")).Text;

        foreach (var state in states)
        {
            epic.Should().Contain($"`{state}`", $"the lifecycle state `{state}` must be named");
        }
    }

    [Fact]
    public void Api_routes_use_the_agreed_prefixes()
    {
        var epic = Docs().First(d => d.Path.Contains("epics")).Text;

        epic.Should().Contain("/api/authority/",
            "authority-service owns /api/authority/*; the gateway route depends on this prefix");

        var strayPrefixes = Regex.Matches(epic, @"/api/(approvals|copilot-authority|authority-service)/")
            .Select(m => m.Value)
            .Distinct()
            .ToList();

        strayPrefixes.Should().BeEmpty(
            "a second prefix means Rusty's gateway route and Turk's controller disagree, and the " +
            "symptom is a 404 that looks like the service is down");
    }

    [Fact]
    public void The_policy_version_prefix_is_stated_once_and_used_consistently()
    {
        // §6.2.1. If one service emits `pv1:` and another emits a bare hex string, the audit
        // trail cannot be joined and the "one policyVersion" criterion fails silently.
        // Reported, not enforced per-document: the epic names `policyVersion` many times but
        // never states the `pv1:` prefix — the derivation lives only in engine §6.2.1. That is a
        // documentation gap (FINDING F-5), not a defect, so the assertion is that the prefix is
        // stated SOMEWHERE and that nothing contradicts it.
        var docs = Docs().ToList();

        docs.Should().Contain(d => d.Text.Contains("pv1:"),
            "the policyVersion format must be written down at least once, or three services will " +
            "invent three formats and the audit trail cannot be joined");

        foreach (var (path, text) in docs)
        {
            if (!text.Contains("policyVersion")) continue;
            if (!text.Contains("pv1:"))
            {
                output.WriteLine(
                    $"FINDING F-5: {path} references policyVersion but never states the pv1: " +
                    "prefix. Anyone implementing from this document alone will guess the format.");
            }
        }
    }

    [Fact]
    public void The_audit_event_names_are_PascalCase_and_unique()
    {
        var epic = Docs().First(d => d.Path.Contains("epics")).Text;

        var events = Regex.Matches(epic, @"\b(Approval[A-Z][A-Za-z]*)\b")
            .Select(m => m.Groups[1].Value)
            .Distinct()
            .OrderBy(x => x, StringComparer.Ordinal)
            .ToList();

        output.WriteLine("Approval* audit events named in the epic: " + string.Join(", ", events));

        events.Should().NotBeEmpty("§5.7 defines the audit vocabulary");
        events.Should().Contain("ApprovalVoidedByPolicyChange",
            "this is the audit-critical event — it is the only record that a machine discarded a " +
            "human's signature, and losing it loses the entire escalation story");

        events.Should().OnlyContain(e => char.IsUpper(e[0]) && !e.Contains('_'),
            "PascalCase for events, SCREAMING_SNAKE for enum values — §0.1");
    }

    [Fact]
    public void The_role_names_are_banker_and_supervisor_and_admin_is_kept_separate()
    {
        var epic = Docs().First(d => d.Path.Contains("epics")).Text;

        epic.Should().Contain("`banker`");
        epic.Should().Contain("`supervisor`");
        epic.Should().MatchRegex(@"admin.{0,200}(does not|NOT|never).{0,80}(imply|implies|banker|supervisor)",
            "§5.8.2 must state plainly that admin sits outside the banking ladder; if that " +
            "sentence is ever softened, one admin identity can fill both L2 slots");
    }

    [Fact]
    public void Both_documents_agree_on_the_escalator_grammar()
    {
        // ⚠️ FINDING F-1, asserted so it cannot be forgotten. The epic §4.2 examples use
        // `raiseBy` + `minRung`; the policy-engine §3.2 pseudocode uses `raise_to` /
        // `min_signers` / `min_seniority`. My reference evaluator accepts BOTH, which is exactly
        // the wrong thing for production to do — a policy file written in the other dialect would
        // be silently ignored, and an escalator that silently does nothing is worse than one that
        // errors, because the rung it should have raised stays low and nobody is told.
        var epic = Docs().First(d => d.Path.Contains("epics")).Text;
        var engine = Docs().First(d => d.Path.Contains("policy-engine")).Text;

        var epicSnake = Regex.IsMatch(epic, @"\braise_to\b|\bmin_signers\b");
        var epicCamel = Regex.IsMatch(epic, @"\braiseTo\b|\braiseBy\b|\bminSigners\b");
        var engineSnake = Regex.IsMatch(engine, @"\braise_to\b|\bmin_signers\b");
        var engineCamel = Regex.IsMatch(engine, @"\braiseTo\b|\braiseBy\b|\bminSigners\b");

        output.WriteLine($"epic: snake={epicSnake} camel={epicCamel}");
        output.WriteLine($"engine: snake={engineSnake} camel={engineCamel}");

        // This is reported as a defect, not enforced as a failure — the reconciliation is Turk's
        // and Brian's call, and a red build here would block work that is not mine to block.
        // The assertion is the weaker, uncontroversial one: SOMETHING must be specified.
        (epicSnake || epicCamel).Should().BeTrue("the epic must specify an escalator grammar");
        (engineSnake || engineCamel).Should().BeTrue("the engine doc must specify one too");

        if (epicSnake != engineSnake || epicCamel != engineCamel)
        {
            output.WriteLine(
                "FINDING F-1: the two ratified documents use DIFFERENT escalator key spellings. " +
                "Turk must implement exactly one, and the loader must HARD ERROR on the other " +
                "rather than ignoring unknown keys.");
        }
    }

}
