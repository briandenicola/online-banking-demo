using AuthorityService.Models;
using AuthorityService.Policy;
using FluentAssertions;
using Xunit;

namespace AuthorityService.UnitTests;

public class PolicyLoaderTests
{
    [Fact]
    public void The_shipped_policy_file_loads_and_validates()
    {
        var policy = TestHarness.LoadPolicy();

        policy.PolicyId.Should().Be("banker-copilot-authority");
        policy.PolicyVersion.Should().StartWith("pv1:");
        policy.Document.ActionTypes.Should().ContainKey("transaction.flag.review");
        policy.Thresholds.Should().NotBeEmpty();
    }

    [Fact]
    public void A_missing_policy_file_refuses_to_load()
    {
        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        var act = () => loader.LoadFromFile("/nonexistent/authority-policy.yaml");

        act.Should().Throw<PolicyValidationException>()
            .WithMessage("*policy file*");
    }

    [Fact]
    public void An_unset_policy_path_refuses_to_load()
    {
        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        var act = () => loader.LoadFromFile("");

        act.Should().Throw<PolicyValidationException>();
    }

    [Fact]
    public void PolicyVersion_is_derived_from_the_RESOLVED_policy_not_the_file_bytes()
    {
        // Same file, different env override → different policyVersion. This is the whole point
        // of §5.3.1: two pods with different env vars are running different rulesets, and a
        // file hash would call them identical.
        var baseline = TestHarness.LoadPolicy();
        var overridden = TestHarness.LoadPolicy(("POLICY_FLAGGED_TXN_DUAL_CONTROL_AMOUNT", "500.00"));

        overridden.PolicyVersion.Should().NotBe(baseline.PolicyVersion);
        overridden.Threshold("flagged_transaction_dual_control_amount").Value.Should().Be("500.00");
        overridden.Threshold("flagged_transaction_dual_control_amount").OverriddenByEnv.Should().BeTrue();
    }

    [Fact]
    public void PolicyVersion_is_stable_across_loads_of_the_same_resolved_policy()
    {
        TestHarness.LoadPolicy().PolicyVersion.Should().Be(TestHarness.LoadPolicy().PolicyVersion);
    }

    [Fact]
    public void PolicyVersion_ignores_provenance_metadata()
    {
        // effectiveFrom and owner are provenance, not rules. Re-stamping a date must not
        // invalidate every outstanding approval.
        var restamped = TestHarness
            .MutatedPolicyYaml("2026-01-01T00:00:00Z", "2027-06-30T12:00:00Z")
            .Replace("owner: risk-operations", "owner: somebody-else");

        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        loader.LoadFromYaml(restamped).PolicyVersion
            .Should().Be(loader.LoadFromFile(TestHarness.PolicyPath).PolicyVersion);
    }

    [Theory]
    [InlineData("unknownAction: deny", "unknownAction: allow")]
    [InlineData("ttlExpiryOutcome: denied", "ttlExpiryOutcome: approved")]
    [InlineData("maxRung: L1", "maxRung: L2")]
    public void Invariant_violating_policies_fail_closed(string original, string replacement)
    {
        var yaml = TestHarness.MutatedPolicyYaml(original, replacement);
        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        var act = () => loader.LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>();
    }

    [Fact]
    public void A_numeric_literal_in_a_predicate_is_rejected()
    {
        // The "no magic numbers" rule, enforced structurally. A magnitude comparison must
        // reference a NAMED threshold; a bare number in the policy file is as bad as one in code.
        var yaml = TestHarness.MutatedPolicyYaml(
            "when: { field: amount, op: gte, threshold: flagged_transaction_dual_control_amount }",
            "when: { field: amount, op: gte, value: 25000 }");

        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        var act = () => loader.LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>()
            .WithMessage("*threshold*");
    }

    [Fact]
    public void A_negative_raiseBy_is_rejected()
    {
        var yaml = TestHarness.MutatedPolicyYaml(
            """
              - id: self-dealing
                description: The approval touches an account or user related to the acting banker.
                when: { field: context.selfDealing, op: isTrue }
                raiseBy: 1
            """,
            """
              - id: self-dealing
                description: The approval touches an account or user related to the acting banker.
                when: { field: context.selfDealing, op: isTrue }
                raiseBy: -1
            """);

        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        var act = () => loader.LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>();
    }

    [Fact]
    public void L2_cannot_be_configured_below_dual_control()
    {
        var yaml = TestHarness.MutatedPolicyYaml(
            """
              L2:
                requiredSigners: 2
            """,
            """
              L2:
                requiredSigners: 1
            """);

        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        var act = () => loader.LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>();
    }

    [Fact]
    public void L3_cannot_be_made_proposable()
    {
        var yaml = TestHarness.MutatedPolicyYaml(
            "proposable: false              # the agent may not even ask", "proposable: true");

        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        var act = () => loader.LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>();
    }

    [Fact]
    public void Malformed_yaml_fails_closed()
    {
        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        var act = () => loader.LoadFromYaml("apiVersion: [unclosed");

        act.Should().Throw<PolicyValidationException>();
    }

    [Fact]
    public void Every_threshold_carries_an_env_override()
    {
        var policy = TestHarness.LoadPolicy();

        policy.Thresholds.Values.Should().OnlyContain(t => !string.IsNullOrWhiteSpace(t.Env));
    }

    [Fact]
    public void A_retired_distinctIdentities_knob_is_rejected_rather_than_ignored()
    {
        // Separation of duties now lives in the signature slots. If the policy file could still
        // declare `distinctIdentities` and have it quietly ignored, an operator would write
        // `distinctIdentities: 1`, read it back, and believe dual control was off. A dead knob
        // that looks live is worse than no knob, so the loader refuses to start.
        var yaml = TestHarness.MutatedPolicyYaml(
            """
              L2:
                requiredSigners: 2
            """,
            """
              L2:
                requiredSigners: 2
                distinctIdentities: 1
            """);

        var loader = PolicyLoader.FromConfiguration(TestHarness.Configuration());

        var act = () => loader.LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>().WithMessage("*distinctIdentities*");
    }

    [Fact]
    public void The_mutation_helper_itself_fails_when_it_matches_nothing()
    {
        // Guards the guard: every negative policy test depends on this throwing.
        var act = () => TestHarness.MutatedPolicyYaml("nothing-like-this-is-in-the-policy", "x");

        act.Should().Throw<InvalidOperationException>();
    }
}
