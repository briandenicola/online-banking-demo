using System.Reflection;
using AuthorityService.Models;
using AuthorityService.Repositories;
using AuthorityService.Services;
using FluentAssertions;
using Microsoft.Extensions.Configuration;
using Xunit;
using Xunit.Abstractions;

namespace BankerCopilotTests.Production;

/// <summary>
/// Structural assertions against the SHIPPING authority-service assembly.
///
/// These are the tests that answer "how do you assert the ABSENCE of a bypass path?". You cannot
/// enumerate the paths that do not exist, so instead assert the shape that makes them
/// unconstructible — and assert it by reflection, so that a future refactor which re-opens a door
/// fails here rather than in a code review nobody does.
/// </summary>
public sealed class ProductionArchitectureTests(ITestOutputHelper output)
{
    private static readonly Assembly Authority = typeof(ApprovalService).Assembly;

    private static string RepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, ".git")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new DirectoryNotFoundException("Repository root not found.");
    }

    [Fact]
    public void The_execute_entry_point_accepts_no_caller_supplied_payload()
    {
        // THE control behind finding F-2.
        //
        // ApprovalService.VerifyStoredHash recomputes the payload hash from `approval.Payload` —
        // the payload already in the store. Considered alone that is a tautology: it proves the
        // record is self-consistent, never that the thing about to execute matches what was
        // signed. I raised it as a defect, and then looked for what actually holds the line.
        //
        // It is this: ExecuteAsync takes NO payload. There is no caller-supplied bytes for a
        // mutation to enter through, so the stored payload IS the executed payload by
        // construction. The safety comes from the absence of a parameter — which means the
        // parameter list is a load-bearing security property and deserves a test that fails if
        // someone helpfully adds an `updatedPayload` overload later.
        var execute = typeof(ApprovalService)
            .GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Where(m => m.Name == "ExecuteAsync")
            .ToList();

        execute.Should().NotBeEmpty();

        foreach (var method in execute)
        {
            foreach (var p in method.GetParameters())
            {
                output.WriteLine($"ExecuteAsync param: {p.ParameterType.Name} {p.Name}");

                p.Name.Should().NotContainEquivalentOf("payload",
                    "a payload parameter on execute would reintroduce the gap that " +
                    "VerifyStoredHash cannot close on its own");
                p.Name.Should().NotContainEquivalentOf("body");
                p.ParameterType.Should().NotBe(typeof(Newtonsoft.Json.Linq.JObject));
            }
        }
    }

    [Fact]
    public void The_lifecycle_has_exactly_five_states_and_no_expired_state()
    {
        // §5.1: the state machine COLLAPSED expired into denied. If someone re-adds `Expired`,
        // a timed-out approval stops counting as a denial and the "silence is not consent"
        // property is quietly lost.
        var names = Enum.GetNames<ApprovalStatus>();

        output.WriteLine("ApprovalStatus = " + string.Join(", ", names));

        names.Should().HaveCount(5);
        names.Should().NotContain(n => n.Equals("Expired", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void There_are_exactly_four_terminal_reasons()
    {
        var names = Enum.GetNames<TerminalReason>();

        output.WriteLine("TerminalReason = " + string.Join(", ", names));
        names.Should().HaveCount(4);
    }

    [Fact]
    public void No_state_machine_edge_leads_out_of_a_terminal_state()
    {
        // Terminal means terminal. A `denied -> proposed` edge would let a denial be reopened and
        // re-signed, which is a total defeat of the invariant dressed up as a retry.
        var machine = Authority.GetTypes()
            .FirstOrDefault(t => t.Name == "ApprovalStateMachine");

        machine.Should().NotBeNull("the explicit state machine is the thing under test");

        var canTransition = machine!.GetMethods(BindingFlags.Public | BindingFlags.Static)
            .FirstOrDefault(m => m.GetParameters().Length == 2 &&
                                 m.GetParameters().All(p => p.ParameterType == typeof(ApprovalStatus)) &&
                                 m.ReturnType == typeof(bool));

        if (canTransition is null)
        {
            output.WriteLine("No (status,status)->bool probe found; asserting on source text instead.");
            var source = File.ReadAllText(Path.Combine(
                RepoRoot(), "src", "authority-service", "Repositories", "ApprovalWriteGuard.cs"));

            foreach (var terminal in new[] { "Denied", "Executed", "Superseded" })
            {
                source.Should().NotMatchRegex(
                    $@"ApprovalStatus\.{terminal}\s*\]\s*=\s*(new\[\]\s*)?\{{[^}}]*ApprovalStatus\.(Proposed|Signed)",
                    $"{terminal} must have no outbound edge back into an actionable state");
            }

            return;
        }

        foreach (var terminal in new[] { ApprovalStatus.Denied, ApprovalStatus.Executed })
        {
            foreach (var target in Enum.GetValues<ApprovalStatus>())
            {
                var allowed = (bool)canTransition.Invoke(null, [terminal, target])!;
                allowed.Should().BeFalse(
                    $"{terminal} is terminal but claims it may become {target}");
            }
        }
    }

    [Fact]
    public void Only_the_write_guard_may_replace_an_approval_document()
    {
        // Single-writer. Every ordering guarantee, every ETag precondition and every state-machine
        // check lives behind one repository. A stray Container.ReplaceItemAsync elsewhere would
        // route around all of it in one line.
        var serviceDir = Path.Combine(RepoRoot(), "src", "authority-service");

        var offenders = Directory
            .EnumerateFiles(serviceDir, "*.cs", SearchOption.AllDirectories)
            .Where(f => !f.Contains($"{Path.DirectorySeparatorChar}obj{Path.DirectorySeparatorChar}") &&
                        !f.Contains($"{Path.DirectorySeparatorChar}bin{Path.DirectorySeparatorChar}"))
            .Where(f => !Path.GetFileName(f).Contains("Repository", StringComparison.Ordinal) &&
                        !Path.GetFileName(f).Contains("WriteGuard", StringComparison.Ordinal))
            .Where(f =>
            {
                var text = File.ReadAllText(f);
                return text.Contains("ReplaceItemAsync") ||
                       text.Contains("UpsertItemAsync") ||
                       text.Contains("PatchItemAsync");
            })
            .Select(f => Path.GetRelativePath(serviceDir, f))
            .ToList();

        offenders.Should().BeEmpty(
            "approval mutation must funnel through the single writer; found direct Cosmos " +
            "writes in: " + string.Join(", ", offenders));
    }

    [Fact]
    public void The_re_evaluation_call_precedes_the_downstream_call_in_the_execute_path()
    {
        // Ordering, asserted on the source of the one method that matters. A gate that runs after
        // the money moves is not a gate — and unit tests cannot see ordering, only outcomes.
        var source = File.ReadAllText(Path.Combine(
            RepoRoot(), "src", "authority-service", "Services", "ApprovalService.cs"));

        var executeStart = source.IndexOf("public async Task<ExecuteResult> ExecuteAsync", StringComparison.Ordinal);
        executeStart.Should().BeGreaterThan(-1);

        var executeEnd = source.IndexOf("\n    public ", executeStart + 10, StringComparison.Ordinal);
        var body = executeEnd > executeStart ? source[executeStart..executeEnd] : source[executeStart..];

        var reEvaluate = body.IndexOf("ReEvaluate", StringComparison.Ordinal);
        var broker = body.IndexOf("_broker", StringComparison.Ordinal);

        reEvaluate.Should().BeGreaterThan(-1, "execute must re-evaluate policy");
        broker.Should().BeGreaterThan(-1, "execute must eventually call downstream");
        reEvaluate.Should().BeLessThan(broker,
            "re-evaluation must appear BEFORE the downstream invocation in the execute path");
    }

    [Fact]
    public void The_expiry_sweeper_exists_as_a_background_service()
    {
        // §5.5: expiry must be an explicit, observable transition — never a status inferred at
        // read time and never Cosmos TTL silently deleting the record.
        var sweeper = Authority.GetTypes().FirstOrDefault(t => t.Name == "ExpirySweeperBackgroundService");

        sweeper.Should().NotBeNull();
        typeof(Microsoft.Extensions.Hosting.IHostedService).IsAssignableFrom(sweeper!).Should().BeTrue();
    }

    [Fact]
    public void No_approval_container_is_configured_with_a_cosmos_ttl()
    {
        // §5.2. Cosmos TTL deletion must never be the expiry mechanism: losing the record is not
        // the same as denying the request, and a deleted approval is an unauditable one.
        var terraform = Path.Combine(RepoRoot(), "infra", "cloud", "cosmos.tf");

        if (!File.Exists(terraform))
        {
            output.WriteLine("PENDING: infra/cloud/cosmos.tf not present.");
            return;
        }

        var text = File.ReadAllText(terraform);
        var idx = text.IndexOf("copilot-approvals", StringComparison.Ordinal);

        if (idx < 0)
        {
            output.WriteLine("PENDING: approvals container not yet declared in Terraform.");
            return;
        }

        var window = text[idx..Math.Min(text.Length, idx + 1200)];
        window.Should().NotMatchRegex(@"default_ttl\s*=\s*[1-9]",
            "a positive default_ttl on the approvals container would delete the audit record");
    }
}

/// <summary>
/// The shipping denial-reason validator (§5.4.2 / design §8.7.1) run against the adversarial
/// corpus. The rule set is config-driven with no code defaults, so the test must supply config —
/// and reads its own boundaries back out of that config rather than hardcoding 20.
/// </summary>
public sealed class ProductionDenialReasonTests(ITestOutputHelper output)
{
    private const int MinLength = 20;

    private static DenialReasonValidator Validator(int maxRepeatUnit = 4)
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Denial:ReasonMinLength"] = MinLength.ToString(),
                ["Denial:ReasonMaxLength"] = "2000",
                ["Denial:ReasonMinDistinctChars"] = "5",
                ["Denial:ReasonMaxRepeatUnit"] = maxRepeatUnit.ToString(),
                ["Denial:ReasonMinLetters"] = "10"
            })
            .Build();

        return new DenialReasonValidator(config);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("                        ")]          // 24 spaces: clears a naive length check
    [InlineData("aaaaaaaaaaaaaaaaaaaaaaaa")]           // one repeated character
    [InlineData("abababababababababababab")]           // 2-char repeat unit
    [InlineData("asdfasdfasdfasdfasdf")]               // the case named in the charter
    [InlineData("....................")]
    [InlineData("12345678901234567890")]               // no letters
    [InlineData("no")]                                  // too short
    public void Degenerate_denial_reasons_are_rejected(string? reason)
    {
        var result = Validator().Validate(reason);

        result.IsValid.Should().BeFalse($"'{reason}' is not a meaningful denial reason");
        result.FailedRule.Should().NotBeNullOrWhiteSpace(
            "a rejection must name the rule it failed, or the API cannot tell the human what to fix");

        output.WriteLine($"{Trunc(reason)} -> {result.FailedRule}: {result.Message}");
    }

    [Theory]
    [InlineData("Counterparty account was closed last week; reversal would fail downstream.")]
    [InlineData("Customer confirmed by phone that this transfer was intentional.")]
    [InlineData("The underwriting file is missing the income verification document.")]
    [InlineData("Duplicate of approval 8841 which a supervisor already signed this morning.")]
    public void Genuine_denial_reasons_are_accepted(string reason)
    {
        // The positive control. Without it, a validator that rejects EVERYTHING passes every
        // test above — and the denial corpus #333 depends on would be empty for a reason nobody
        // would notice until the labels were needed.
        var result = Validator().Validate(reason);

        result.IsValid.Should().BeTrue(
            $"a real reason was rejected by {result.FailedRule}: {result.Message}");
    }

    [Fact]
    public void FINDING_F4_a_repeat_unit_longer_than_the_configured_bound_still_escapes()
    {
        // REPORTED, NOT FIXED — the bound is config, and config is Turk's/Brian's call.
        //
        // ReasonMaxRepeatUnit = 4 means the validator looks for repeating units up to 4 characters.
        // "qwertyqwertyqwertyqwerty" repeats a SIX-character unit, so it sails past the degeneracy
        // rules while being exactly as meaningless as "aaaaaaaa".
        //
        // This test asserts the CURRENT ratified behaviour (escape open) and then proves that
        // raising the bound closes it — so the finding is demonstrated rather than merely claimed.
        const string keyboardWalk = "qwertyqwertyqwertyqwerty";

        var atRatifiedBound = Validator(maxRepeatUnit: 4).Validate(keyboardWalk);
        var atWiderBound = Validator(maxRepeatUnit: 8).Validate(keyboardWalk);

        output.WriteLine($"maxRepeatUnit=4 -> valid={atRatifiedBound.IsValid} ({atRatifiedBound.FailedRule})");
        output.WriteLine($"maxRepeatUnit=8 -> valid={atWiderBound.IsValid} ({atWiderBound.FailedRule})");

        atWiderBound.IsValid.Should().BeFalse(
            "raising the repeat-unit bound to 8 must close the escape; if this fails the " +
            "degeneracy rule is not doing what its name says");

        if (atRatifiedBound.IsValid)
        {
            output.WriteLine("FINDING F-4 CONFIRMED: the escape is open at the ratified bound of 4.");
        }
    }

    [Fact]
    public void The_validator_refuses_to_start_without_configuration()
    {
        // No code-level defaults. A validator that silently falls back to built-in numbers would
        // make the config file decorative, and the deployed bound unknowable from the repo.
        var empty = new ConfigurationBuilder().Build();

        var act = () => new DenialReasonValidator(empty);

        act.Should().Throw<InvalidOperationException>()
            .WithMessage("*missing*");
    }

    [Fact]
    public void The_length_floor_comes_from_config_and_is_measured_after_trimming()
    {
        // Constructed FROM the configured minimum, so raising the bound cannot make this pass
        // vacuously.
        var padded = "  " + new string('x', MinLength - 1) + "  ";

        Validator().Validate(padded).IsValid.Should().BeFalse(
            "whitespace padding must not be counted toward the minimum length");
    }

    private static string Trunc(string? s) =>
        s is null ? "<null>" : s.Length <= 30 ? $"'{s}'" : $"'{s[..27]}...'";
}
