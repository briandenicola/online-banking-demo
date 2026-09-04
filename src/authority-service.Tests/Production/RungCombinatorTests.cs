using AuthorityService.Models;
using AuthorityService.Policy;
using FluentAssertions;
using Newtonsoft.Json.Linq;
using Xunit;
using Xunit.Abstractions;

namespace BankerCopilotTests.Production;

/// <summary>
/// The rung combinator, tested in isolation from the shipping policy's data.
///
/// THIS FILE EXISTS BECAUSE OF A TAMPER TEST THAT FAILED TO FAIL.
///
/// I replaced <c>rung = RungOrder.Max(rung, raised)</c> with <c>rung = raised</c> in the real
/// evaluator — a straight last-writer-wins bug, the single most likely way for an escalator to
/// lower a rung — and the property test over the real policy stayed green. The reason is that
/// every escalator in config/authority-policy.yaml uses the relative form <c>raiseBy: 1</c>.
/// Under an always-ascending rule set, "take the max" and "take the last" produce identical
/// numbers, so no input the generator could produce would separate them.
///
/// A property test is only as strong as the inputs it can reach. Monotonicity is a property of
/// the COMBINATOR, not of today's configuration, and the grammar permits absolute
/// <c>raiseTo</c> escalators — so the day someone adds one, the safety of the whole ladder rests
/// on a `Math.Max` that nothing was checking. These tests check it.
/// </summary>
public sealed class RungCombinatorTests(ITestOutputHelper output)
{
    private static readonly PolicyEvaluator Evaluator = new();

    private static ResolvedPolicy FixturePolicy() =>
        new PolicyLoader(new Dictionary<string, string?>())
            .LoadFromFile(Path.Combine(
                AppContext.BaseDirectory, "TestPolicies", "descending-escalators.yaml"));

    private static ActorContext Actor(bool selfDealing) => new()
    {
        UserId = "u_banker_1",
        Username = "banker.one",
        Role = "banker",
        EffectiveRoles = ["banker"],
        Seniority = 1,
        SessionId = "s_1",
        SelfDealing = selfDealing
    };

    private static EvaluationContext Context(string decision, bool selfDealing, string riskTier) => new()
    {
        ActionId = "fixture.action",
        Payload = new JObject { ["subject"] = "acct_1", ["decision"] = decision },
        Actor = Actor(selfDealing),
        Evidence = new JObject(),
        Facts = new JObject
        {
            ["customer"] = new JObject { ["riskTier"] = riskTier },
            ["context"] = new JObject { ["selfDealing"] = selfDealing }
        }
    };



    /// <summary>
    /// How many DISTINCT humans a decision actually requires.
    ///
    /// Separation of duties was refactored mid-flight (Danny, 2026-09-04): the rung-level
    /// `distinctIdentities` head-count is retired, and the loader now REJECTS a policy that still
    /// declares it, rather than ignoring it. That is the right call — a dead knob an operator can
    /// still set to 1 and believe they have relaxed dual control is worse than no knob — but it
    /// means "two distinct humans" is no longer a number anywhere. It is a property of the slots:
    /// each co-signer slot carries `mustDifferFrom`, which names the identity it excludes.
    ///
    /// So the honest count is: one signer, plus every later slot that excludes somebody. If a
    /// co-signer slot ever came back with an EMPTY mustDifferFrom, this returns 1 and every
    /// caller below fails — which is exactly the failure that matters, and which a head-count
    /// read from config could no longer detect.
    /// </summary>
    private static int DistinctIdentities(ResolvedPolicy policy, PolicyDecision decision)
    {
        if (decision.SignerSlots.Count == 0) return 0;

        return 1 + decision.SignerSlots.Count(s => s.Ordinal > 0 && s.MustDifferFrom.Count > 0);
    }

    [Fact]
    public void The_fixture_policy_loads_and_both_traps_are_actually_armed()
    {
        // Anti-vacuous guard for the whole file. If the fixture stopped parsing, or the rules
        // stopped firing, every test below would pass by doing nothing.
        var policy = FixturePolicy();
        var action = policy.Action("fixture.action");

        action.Should().NotBeNull();
        action!.Rules.Should().HaveCount(2, "the descending RULE pair is the first trap");
        policy.Document.Escalators.Should().HaveCount(2, "the descending ESCALATOR pair is the second");

        var both = Evaluator.Evaluate(Context("severe", selfDealing: true, riskTier: "high"), policy);

        both.FiredEscalators.Select(f => f.Key).Should().Contain(
            ["strong-rule-first", "weak-rule-second", "zz-strong-first", "zz-weak-second"],
            "all four must fire, or the descending order is never exercised");

        output.WriteLine("fired: " + string.Join(", ", both.FiredEscalators.Select(f => f.Key)));
    }

    [Fact]
    public void A_weaker_action_rule_declared_after_a_stronger_one_cannot_lower_the_rung()
    {
        // strong-rule-first raises to L3; weak-rule-second then asks for L2 on the same input.
        // Correct: L3. Last-writer-wins: L2 — and an out-of-harness action becomes signable by
        // two bankers.
        var policy = FixturePolicy();

        var decision = Evaluator.Evaluate(
            Context("severe", selfDealing: false, riskTier: "low"), policy);

        decision.RequiredRung.Should().Be(Rung.L3,
            "a rule that fires later must not be able to undo a stronger rule that fired earlier");
    }

    [Fact]
    public void A_weaker_escalator_declared_after_a_stronger_one_cannot_lower_the_rung()
    {
        // Same trap one layer up: zz-strong-first raises to L3, zz-weak-second to L2.
        var policy = FixturePolicy();

        var decision = Evaluator.Evaluate(
            Context("routine", selfDealing: true, riskTier: "high"), policy);

        decision.RequiredRung.Should().Be(Rung.L3,
            "escalator order must not affect the outcome; the combinator is a max, not an assignment");
    }

    [Fact]
    public void Escalator_declaration_order_is_irrelevant_to_the_outcome()
    {
        // Commutativity. If the outcome depended on order, "which escalators fired" would stop
        // being sufficient to explain a rung, and the trace frame shown to the human would be
        // an incomplete account of why they are being asked to sign.
        var policy = FixturePolicy();

        var strongOnly = Evaluator.Evaluate(Context("routine", true, "low"), policy);
        var weakOnly = Evaluator.Evaluate(Context("routine", false, "high"), policy);
        var both = Evaluator.Evaluate(Context("routine", true, "high"), policy);

        output.WriteLine($"strong={strongOnly.RequiredRung} weak={weakOnly.RequiredRung} both={both.RequiredRung}");

        ((int)both.RequiredRung).Should().Be(
            Math.Max((int)strongOnly.RequiredRung, (int)weakOnly.RequiredRung),
            "the combined rung must be the max of the parts, not the last part");
    }

    [Fact]
    public void Adding_the_weak_escalator_to_the_strong_one_never_reduces_signers_or_seniority()
    {
        var policy = FixturePolicy();

        var strongOnly = Evaluator.Evaluate(Context("routine", true, "low"), policy);
        var both = Evaluator.Evaluate(Context("routine", true, "high"), policy);

        both.RequiredSigners.Should().BeGreaterThanOrEqualTo(strongOnly.RequiredSigners);
        DistinctIdentities(policy, both).Should().BeGreaterThanOrEqualTo(DistinctIdentities(policy, strongOnly));
        both.MinSeniority.Should().BeGreaterThanOrEqualTo(strongOnly.MinSeniority);
    }

    [Fact]
    public void Every_reachable_combination_in_the_fixture_is_at_least_as_strict_as_its_subsets()
    {
        // The same power-set property as the production test, but over inputs that can actually
        // distinguish max from last-wins.
        var policy = FixturePolicy();
        var toggles = new[] { "severe", "selfDealing", "highRisk" };
        var seen = new Dictionary<int, PolicyDecision>();

        for (var mask = 0; mask < 1 << toggles.Length; mask++)
        {
            seen[mask] = Evaluator.Evaluate(Context(
                (mask & 1) != 0 ? "severe" : "routine",
                (mask & 2) != 0,
                (mask & 4) != 0 ? "high" : "low"), policy);
        }

        var comparisons = 0;

        foreach (var (mask, decision) in seen)
        {
            for (var bit = 0; bit < toggles.Length; bit++)
            {
                if ((mask & (1 << bit)) == 0) continue;

                var subset = seen[mask & ~(1 << bit)];
                comparisons++;

                ((int)decision.RequiredRung).Should().BeGreaterThanOrEqualTo(
                    (int)subset.RequiredRung,
                    $"turning on '{toggles[bit]}' lowered the rung from {subset.RequiredRung} " +
                    $"to {decision.RequiredRung}");
            }
        }

        comparisons.Should().Be(12, "the power-set comparison must actually have run");
    }

    [Fact]
    public void FINDING_F9_the_production_raise_operator_overflows_into_a_negative_rung()
    {
        // REPORTED, NOT FIXED — AuthorityService.Models.RungOrder is Turk's.
        //
        //     var target = (int)from + steps;
        //     return target >= (int)Rung.L3 ? Rung.L3 : (Rung)target;
        //
        // For a large `steps`, `(int)from + steps` overflows to a NEGATIVE number. The clamp only
        // tests the upper bound, so the negative value falls straight through the ternary and is
        // cast to a Rung below L1. An escalation becomes a downgrade by arithmetic — the one
        // outcome I-4 declares structurally impossible.
        //
        // How reachable is it? Only via a policy carrying an absurd `raiseBy`, and load-time
        // validation rejects NEGATIVE values but not enormous ones. So it is not an attack today;
        // it is an unguarded edge on the one function the monotonicity proof rests upon, and the
        // fix is one word: compute in `long`.
        //
        // This test asserts the CURRENT behaviour so the finding is demonstrated rather than
        // asserted. Invert it when the arithmetic is widened.
        var overflowed = AuthorityService.Models.RungOrder.RaiseBy(Rung.L1, int.MaxValue);

        output.WriteLine($"RaiseBy(L1, int.MaxValue) = {(int)overflowed}");

        if ((int)overflowed >= (int)Rung.L1)
        {
            output.WriteLine("F-9 appears FIXED — invert this test.");
            ((int)overflowed).Should().Be((int)Rung.L3);
            return;
        }

        ((int)overflowed).Should().BeLessThan((int)Rung.L1,
            "documenting the escape: the raise operator produced a rung below L1");

        // The realistic range must still be correct, or this would be a much larger problem.
        AuthorityService.Models.RungOrder.RaiseBy(Rung.L1, 1).Should().Be(Rung.L2);
        AuthorityService.Models.RungOrder.RaiseBy(Rung.L2, 1).Should().Be(Rung.L3);
        AuthorityService.Models.RungOrder.RaiseBy(Rung.L3, 1).Should().Be(Rung.L3);
        AuthorityService.Models.RungOrder.RaiseBy(Rung.L1, 5).Should().Be(Rung.L3);
    }
}
