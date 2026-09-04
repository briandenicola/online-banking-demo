using AuthorityService.Models;
using AuthorityService.Policy;
using FluentAssertions;
using Xunit;

namespace AuthorityService.UnitTests;

/// <summary>
/// Cover for two defects Livingston found by reading for the failure mode rather than the happy
/// path: an escalation step that overflows into a downgrade, and a policy grammar that accepts
/// misspelled rules in silence.
/// </summary>
public class EscalationSafetyTests
{
    [Theory]
    [InlineData(int.MaxValue)]
    [InlineData(int.MaxValue - 1)]
    [InlineData(1_000_000)]
    [InlineData(3)]
    public void A_huge_raiseBy_saturates_at_L3_rather_than_wrapping_below_L1(int steps)
    {
        // `(int)from + steps` overflows to a NEGATIVE number, and a clamp that only tests the
        // upper bound lets it through to cast into a rung beneath L1 — an escalation arriving as
        // a downgrade, which invariant I-4 says is structurally impossible.
        foreach (var from in new[] { Rung.L1, Rung.L2, Rung.L3 })
        {
            RungOrder.RaiseBy(from, steps).Should().Be(Rung.L3);
            ((int)RungOrder.RaiseBy(from, steps)).Should().BeGreaterThanOrEqualTo((int)from);
        }
    }

    [Fact]
    public void RaiseBy_never_returns_a_rung_below_where_it_started()
    {
        var steps = new[] { 0, 1, 2, 7, 1023, int.MaxValue / 2, int.MaxValue };

        foreach (var from in new[] { Rung.L1, Rung.L2, Rung.L3 })
        foreach (var step in steps)
        {
            ((int)RungOrder.RaiseBy(from, step)).Should().BeGreaterThanOrEqualTo((int)from,
                $"raising {from} by {step} must never lower it");
        }
    }

    [Fact]
    public void A_misspelled_escalator_key_is_a_startup_failure_not_a_silent_no_op()
    {
        // The dangerous outcome is not the typo; it is the service starting anyway, presenting a
        // policy that reads as though a rule is in force when the deserializer dropped it.
        var yaml = TestHarness.MutatedPolicyYaml("    raiseTo: L2", "    raise_to: L2");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>();
    }

    [Fact]
    public void An_unknown_top_level_block_is_a_startup_failure()
    {
        var yaml = TestHarness.MutatedPolicyYaml("capabilityScopes:", "capabilityScopez:");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>();
    }

    [Fact]
    public void Every_money_field_is_inside_the_signed_projection()
    {
        var policy = TestHarness.LoadPolicy();

        foreach (var (id, action) in policy.Document.ActionTypes)
        {
            action.MoneyFields.Should().BeSubsetOf(action.HashFields,
                $"a money field outside '{id}'.hashFields is a figure nobody signed");
        }
    }
}
