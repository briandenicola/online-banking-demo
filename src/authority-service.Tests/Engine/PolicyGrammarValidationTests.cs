using System.Text.Json;
using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;
using Xunit.Abstractions;

namespace BankerCopilotTests.Engine;

/// <summary>
/// Load-time grammar validation: a policy that can EXPRESS a downgrade must fail to load.
///
/// WRITTEN BECAUSE OF A GAP A TAMPER TEST EXPOSED. I disabled the negative-raiseBy check in the
/// reference model and the whole 184-test suite stayed green — because every test fed it a
/// well-formed policy. The guard existed, was correct, and was completely unobserved.
///
/// That matters more than it looks. §3.4's monotonicity proof has a precondition: that no rule
/// can carry a negative adjustment. The runtime combinator (`max`) and the load-time grammar are
/// two independent halves of the same guarantee, and a suite that only exercises the first is
/// asserting the theorem while ignoring its hypothesis. If lowering ever becomes REPRESENTABLE,
/// every monotonicity test in this project is testing a policy language that no longer has the
/// property they claim to check.
///
/// I-4: "escalators are monotonic and must be structurally incapable of downgrade" — structurally
/// incapable means it does not parse, not that it is ignored at runtime.
/// </summary>
public sealed class PolicyGrammarValidationTests(ITestOutputHelper output)
{
    private static string BaselineJson() =>
        File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "TestPolicies", "baseline.json"));

    private static Policy LoadMutated(Func<JsonNodeEditor, JsonNodeEditor> mutate)
    {
        var edited = mutate(new JsonNodeEditor(BaselineJson())).ToJson();
        var temp = Path.Combine(Path.GetTempPath(), $"policy-{Guid.NewGuid():N}.json");

        try
        {
            File.WriteAllText(temp, edited);
            return PolicyLoader.Load(temp);
        }
        finally
        {
            if (File.Exists(temp)) File.Delete(temp);
        }
    }

    [Fact]
    public void The_unmutated_baseline_still_loads()
    {
        // Positive control. Every rejection test below is meaningless if the loader has simply
        // become unable to load anything.
        var policy = LoadMutated(e => e);

        policy.Actions.Should().NotBeEmpty();
        policy.Escalators.Should().NotBeEmpty();
    }

    [Theory]
    [InlineData("raiseBy")]
    [InlineData("minSigners")]
    [InlineData("minSeniority")]
    public void A_negative_adjustment_on_a_global_escalator_is_rejected_at_load_time(string field)
    {
        var act = () => LoadMutated(e => e.SetOnFirstEscalator(field, -1));

        act.Should().Throw<InvalidOperationException>()
            .WithMessage($"*negative {field}*",
                $"a policy expressing a negative {field} must not load at all; a downgrade that " +
                "merely fails to apply at runtime is one refactor away from applying");
    }

    [Theory]
    [InlineData("raiseBy")]
    [InlineData("minSigners")]
    [InlineData("minSeniority")]
    public void A_negative_adjustment_on_an_action_rule_is_rejected_at_load_time(string field)
    {
        // Action-local rules are the easier half to forget: they live under each action rather
        // than in one list, so a validator written against `escalators` alone would miss them
        // entirely while looking complete.
        var act = () => LoadMutated(e => e.SetOnFirstActionRule(field, -1));

        act.Should().Throw<InvalidOperationException>()
            .WithMessage($"*negative {field}*");
    }

    [Fact]
    public void The_rejection_message_names_the_offending_rule()
    {
        // An operator editing a 400-line policy file needs to know WHICH rule, or the guard just
        // means "something, somewhere, is wrong".
        var act = () => LoadMutated(e => e.SetOnFirstEscalator("raiseBy", -3));

        var message = act.Should().Throw<InvalidOperationException>().Which.Message;

        output.WriteLine(message);
        message.Should().MatchRegex(@"Rule '[^']+'");
        message.Should().Contain("I-4", "the message should point at the invariant it defends");
    }

    [Fact]
    public void Zero_is_allowed_because_a_no_op_rule_is_not_a_downgrade()
    {
        // The boundary. Rejecting 0 as well would be over-strict and would tempt someone to
        // relax the check to `< -1` or to delete it. The line is at "can it ever lower?".
        var act = () => LoadMutated(e => e.SetOnFirstEscalator("raiseBy", 0));

        act.Should().NotThrow();
    }

    [Fact]
    public void The_runtime_combinator_refuses_a_negative_step_even_if_a_policy_slipped_past()
    {
        // Defence in depth, asserted directly rather than through a policy file. The load-time
        // grammar is the first line; RungOrder.RaiseBy is the second, and it is the one that
        // would hold if a policy were ever constructed in code rather than parsed.
        var act = () => RungOrder.RaiseBy(Rung.L2, -1);

        act.Should().Throw<InvalidOperationException>()
            .WithMessage("*must be >= 0*");
    }

    [Fact]
    public void Raising_saturates_at_the_top_rung_rather_than_wrapping()
    {
        // Integer overflow or a modulo would turn "escalate above L3" into "drop to L1", which is
        // the same catastrophe as a downgrade, reached by arithmetic instead of by policy.
        RungOrder.RaiseBy(Rung.L3, 1).Should().Be(Rung.L3);
        RungOrder.RaiseBy(Rung.L3, 99).Should().Be(Rung.L3);
        RungOrder.RaiseBy(Rung.L1, int.MaxValue).Should().Be(Rung.L3);
    }

    /// <summary>Minimal JSON editor so the mutations above read as intent, not as plumbing.</summary>
    private sealed class JsonNodeEditor(string json)
    {
        private readonly Dictionary<string, object?> _doc =
            JsonSerializer.Deserialize<Dictionary<string, object?>>(json)!;

        private JsonElement Root => JsonSerializer.SerializeToElement(_doc);

        public JsonNodeEditor SetOnFirstEscalator(string field, int value)
        {
            var escalators = JsonSerializer.Deserialize<List<Dictionary<string, JsonElement>>>(
                _doc["escalators"]!.ToString()!)!;

            escalators[0][field] = JsonSerializer.SerializeToElement(value);
            _doc["escalators"] = JsonSerializer.SerializeToElement(escalators);
            return this;
        }

        public JsonNodeEditor SetOnFirstActionRule(string field, int value)
        {
            var actions = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(
                _doc["actions"]!.ToString()!)!;

            var key = actions.Keys.First(k =>
                actions[k].TryGetProperty("thresholds", out var t) &&
                t.EnumerateArray().Any());

            var action = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(
                actions[key].GetRawText())!;

            var rules = JsonSerializer.Deserialize<List<Dictionary<string, JsonElement>>>(
                action["thresholds"].GetRawText())!;

            rules[0][field] = JsonSerializer.SerializeToElement(value);
            action["thresholds"] = JsonSerializer.SerializeToElement(rules);
            actions[key] = JsonSerializer.SerializeToElement(action);
            _doc["actions"] = JsonSerializer.SerializeToElement(actions);
            return this;
        }

        public string ToJson() => JsonSerializer.Serialize(Root);
    }
}
