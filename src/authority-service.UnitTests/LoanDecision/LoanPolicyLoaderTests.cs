using AuthorityService.LoanDecision.Policy;
using FluentAssertions;
using Xunit;

namespace AuthorityService.UnitTests.LoanDecision;

public sealed class LoanPolicyLoaderTests
{
    private static string PolicyPath
    {
        get
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);
            while (directory is not null)
            {
                var candidate = Path.Combine(directory.FullName, "config", "loan-underwriting-policy.yaml");
                if (File.Exists(candidate)) return candidate;
                directory = directory.Parent;
            }

            throw new FileNotFoundException("Could not locate config/loan-underwriting-policy.yaml.");
        }
    }

    private static string ShippedYaml() => File.ReadAllText(PolicyPath);

    private static string Mutate(string find, string replace)
    {
        var yaml = ShippedYaml();
        yaml.Should().Contain(find, "the mutation must be applied to the shipped policy");
        var mutated = yaml.Replace(find, replace, StringComparison.Ordinal);
        mutated.Should().NotBe(yaml, "a negative test must not run against the unmodified policy");
        return mutated;
    }

    [Fact]
    public void Shipped_inventory_is_exactly_POL_001_through_POL_010_and_all_are_provisional()
    {
        var policy = new LoanPolicyLoader().LoadFromFile(PolicyPath);
        var expected = Enumerable.Range(1, 10).Select(number => $"POL-{number:000}").ToArray();

        policy.Document.Rules.Select(rule => rule.Id).Should().BeEquivalentTo(expected);
        policy.Document.Rules.Should().OnlyContain(rule =>
            rule.Status == "PROVISIONAL" &&
            rule.Operator == "UNDEFINED" &&
            rule.Outcome == "BLOCKED");
        policy.Document.Rules.Select(rule => rule.ReasonCode).Should().OnlyHaveUniqueItems();
        policy.PolicyVersion.Should().StartWith("lpv1:");
        policy.IsExecutable.Should().BeFalse();
    }

    [Theory]
    [InlineData("  - id: POL-010", "  - id: POL-009", "Duplicate rule id")]
    [InlineData("  - id: POL-010", "  - id: POL-999", "Unknown rule id")]
    [InlineData("    reasonCode: POL_010_DEFINITION_UNRESOLVED", "    reasonCode: POL_009_DEFINITION_UNRESOLVED", "Duplicate reasonCode")]
    [InlineData("    status: PROVISIONAL", "    status: RATIFIED", "status must be")]
    [InlineData("    operator: UNDEFINED", "    operator: GTE", "operator must be")]
    [InlineData("    outcome: BLOCKED", "    outcome: ALLOW", "outcome must be")]
    public void Invalid_inventory_or_schema_fields_fail_closed(string find, string replace, string message)
    {
        var mutated = Mutate(find, replace);

        var act = () => new LoanPolicyLoader().LoadFromYaml(mutated);

        act.Should().Throw<LoanPolicyValidationException>().WithMessage($"*{message}*");
    }

    [Theory]
    [InlineData("APPROVE")]
    [InlineData("CONDITIONAL")]
    [InlineData("DECLINE")]
    public void A_provisional_rule_cannot_emit_a_loan_decision(string outcome)
    {
        var mutated = Mutate("    outcome: BLOCKED", $"    outcome: {outcome}");
        mutated.Should().Contain($"outcome: {outcome}");

        var act = () => new LoanPolicyLoader().LoadFromYaml(mutated);

        act.Should().Throw<LoanPolicyValidationException>()
            .WithMessage($"*provisional and cannot emit {outcome}*");
    }

    [Fact]
    public void Unknown_schema_fields_fail_closed()
    {
        var mutated = Mutate(
            "    reasonCode: POL_001_DEFINITION_UNRESOLVED",
            "    reasonCode: POL_001_DEFINITION_UNRESOLVED\n    predicate: applicant.score > 1");

        var act = () => new LoanPolicyLoader().LoadFromYaml(mutated);

        act.Should().Throw<LoanPolicyValidationException>().WithMessage("*could not be parsed*");
    }

    [Fact]
    public void Provider_refuses_to_make_the_valid_provisional_inventory_executable()
    {
        var policy = new LoanPolicyLoader().LoadFromFile(PolicyPath);
        var provider = new LoanPolicyProvider(policy);

        var act = provider.RequireExecutable;

        act.Should().Throw<LoanPolicyValidationException>()
            .WithMessage("*POLICY_DEFINITION_UNRESOLVED*");
    }
}
