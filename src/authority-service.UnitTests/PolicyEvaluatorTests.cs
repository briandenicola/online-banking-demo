using AuthorityService.Models;
using AuthorityService.Policy;
using FluentAssertions;
using Newtonsoft.Json.Linq;
using Xunit;

namespace AuthorityService.UnitTests;

public class PolicyEvaluatorTests
{
    private static readonly ResolvedPolicy Policy = TestHarness.LoadPolicy();
    private static readonly PolicyEvaluator Evaluator = new();

    // =====================================================================================
    // The property that matters: NO combination of escalators can lower a rung.
    // =====================================================================================

    /// <summary>
    /// Each fragment is an independent escalation trigger. None of them mentions a rung
    /// directly — they set facts, and the policy decides.
    /// </summary>
    private static readonly (string Name, Action<JObject, MutableActor> Apply)[] Fragments =
    [
        ("self-dealing", (_, actor) => actor.SelfDealing = true),
        ("bulk-fan-out", (facts, _) => Set(facts, "session", "proposalCountForActionType", 500)),
        ("velocity", (_, actor) => actor.SignaturesInWindow = 500),
        ("low-agent-confidence", (facts, _) => Set(facts, "agent", "confidence", 0.01)),
        ("policy-exception", (facts, _) =>
            Set(facts, "underwriting", "policyExceptions", new JArray("POL-900"))),
        ("high-risk-customer", (facts, _) => Set(facts, "customer", "riskTier", "high")),
        ("anomalous-session", (facts, _) => Set(facts, "session", "anomalyScore", 0.99))
    ];

    [Fact]
    public void No_combination_of_escalators_can_ever_lower_a_rung()
    {
        var total = 1 << Fragments.Length;   // exhaustive over 2^7 = 128 subsets

        for (var mask = 0; mask < total; mask++)
        {
            var subset = Evaluate(mask);

            // 1. Every subset is at or above the empty-set baseline.
            ((int)subset.RequiredRung).Should().BeGreaterThanOrEqualTo(
                (int)Evaluate(0).RequiredRung,
                "adding escalators to the empty set can only raise the rung (mask {0})", mask);

            for (var bit = 0; bit < Fragments.Length; bit++)
            {
                if ((mask & (1 << bit)) != 0) continue;

                var superset = Evaluate(mask | (1 << bit));

                // 2. Adding ONE more escalator to ANY subset never lowers the rung.
                ((int)superset.RequiredRung).Should().BeGreaterThanOrEqualTo(
                    (int)subset.RequiredRung,
                    "adding '{0}' to subset {1} must not lower the rung",
                    Fragments[bit].Name, mask);

                // 3. Nor the signer count, wherever both remain admissible. (Once the ladder
                //    escalates out of the Copilot the decision is a refusal, which has no
                //    signer count to compare.)
                if (subset.Admissible && superset.Admissible)
                {
                    superset.RequiredSigners.Should().BeGreaterThanOrEqualTo(subset.RequiredSigners);

                    // 4. Nor separation of duties: a co-signer slot that excluded the requester
                    //    cannot come back excluding nobody. There is no verb in the grammar that
                    //    empties `mustDifferFrom`, and this asserts the absence structurally.
                    foreach (var slot in subset.SignerSlots.Where(s => s.MustDifferFrom.Count > 0))
                    {
                        superset.SignerSlots.Should().Contain(
                            s => s.Ordinal == slot.Ordinal &&
                                 slot.MustDifferFrom.All(id => s.MustDifferFrom.Contains(id)),
                            "escalation may add exclusions, never drop them (mask {0})", mask);
                    }
                }

            }
        }
    }

    [Fact]
    public void Supersede_floor_uses_min_rung_not_raise_by()
    {
        var supersede = Policy.Document.Escalators.Single(e => e.Id == "superseding-proposal");

        supersede.MinRung.Should().Be("L2");
        supersede.RaiseBy.Should().BeNull("an L2 counter-proposal must stay L2, not become L3");
        supersede.RaiseTo.Should().BeNull();
    }

    [Fact]
    public void Every_fired_escalator_records_a_rung_at_or_above_the_base()
    {
        var decision = Evaluate((1 << Fragments.Length) - 1);

        decision.FiredEscalators.Should().NotBeEmpty();
        decision.FiredEscalators.Should().OnlyContain(e => (int)e.RaisedTo >= (int)Rung.L1);
        decision.FiredEscalators.Should().OnlyContain(e => !string.IsNullOrWhiteSpace(e.Reason));
    }

    // =====================================================================================
    // Baseline behaviour
    // =====================================================================================

    [Fact]
    public void A_routine_review_below_every_threshold_stays_at_L1_with_one_signer()
    {
        var decision = Evaluate(0);

        decision.Outcome.Should().Be(DecisionOutcome.Admitted);
        decision.RequiredRung.Should().Be(Rung.L1);
        decision.RequiredSigners.Should().Be(1);
        decision.FiredEscalators.Should().BeEmpty();
    }

    [Fact]
    public void Crossing_the_money_threshold_raises_to_L2_with_two_distinct_signers()
    {
        var threshold = Policy.Threshold("flagged_transaction_dual_control_amount").AsDecimal();

        var decision = Evaluate(0, payload =>
            payload["amount"] = (threshold + 1).ToString("F2"));

        decision.RequiredRung.Should().Be(Rung.L2);
        decision.RequiredSigners.Should().Be(2);

        // Separation of duties is a set-membership test on the slot, not a head count: the
        // second slot names the identity it must differ from (Danny, 2026-09-04).
        decision.SignerSlots.Should().HaveCount(2);
        decision.SignerSlots[1].MustDifferFrom.Should().NotBeEmpty();
        decision.FiredEscalators.Should().Contain(e => e.Key == "large-flagged-amount");
    }

    [Fact]
    public void Threshold_reason_templates_render_actual_and_threshold_without_trailing_newline()
    {
        var threshold = Policy.Threshold("flagged_transaction_dual_control_amount").AsDecimal();
        var amount = (threshold + 1).ToString("F2");

        var decision = Evaluate(0, payload => payload["amount"] = amount);

        var escalator = decision.FiredEscalators.Single(e => e.Key == "large-flagged-amount");
        escalator.ThresholdName.Should().Be("flagged_transaction_dual_control_amount");
        escalator.ThresholdValue.Should().Be(Policy.Threshold("flagged_transaction_dual_control_amount").Value);
        escalator.Reason.Should().Contain(amount);
        escalator.Reason.Should().Contain(escalator.ThresholdValue);
        escalator.Reason.Should().NotContain("{");
        escalator.Reason.Should().NotEndWith("\n");
    }

    [Fact]
    public void Categorical_reason_templates_render_the_actual_matched_value()
    {
        var decision = Evaluate(0, (_, actor) => { }, facts =>
            Set(facts, "customer", "riskTier", "high"));

        var escalator = decision.FiredEscalators.Single(e => e.Key == "high-risk-customer");
        escalator.ThresholdName.Should().BeNull();
        escalator.ThresholdValue.Should().BeNull();
        escalator.Reason.Should().Be("The customer's risk tier is high.");
    }

    [Fact]
    public void Unresolved_reason_placeholders_are_never_emitted_to_signers()
    {
        var yaml = TestHarness.MutatedPolicyYaml(
            "The customer's risk tier is {actual}.",
            "The customer's risk tier is {actual}. Internal placeholder {missing.value}.");
        var policy = PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        var decision = Evaluate(policy, 0, facts => Set(facts, "customer", "riskTier", "high"));

        var escalator = decision.FiredEscalators.Single(e => e.Key == "high-risk-customer");
        escalator.Reason.Should().Be("The customer's risk tier is high.");
        escalator.Reason.Should().NotContain("{");
    }

    [Fact]
    public void Just_below_the_money_threshold_stays_at_L1()
    {
        var threshold = Policy.Threshold("flagged_transaction_dual_control_amount").AsDecimal();

        var decision = Evaluate(0, payload =>
            payload["amount"] = (threshold - 1).ToString("F2"));

        decision.RequiredRung.Should().Be(Rung.L1);
    }

    [Fact]
    public void The_second_slot_can_never_be_filled_by_the_requester()
    {
        var threshold = Policy.Threshold("flagged_transaction_dual_control_amount").AsDecimal();

        var decision = Evaluate(0, payload => payload["amount"] = (threshold + 1).ToString("F2"));

        decision.SignerSlots.Should().HaveCount(2);
        decision.SignerSlots[1].MustDifferFrom.Should().Contain("banker-1");
    }

    [Fact]
    public void An_unknown_action_is_refused()
    {
        var decision = Evaluator.Evaluate(new EvaluationContext
        {
            ActionId = "totally.made.up",
            Payload = new JObject(),
            Actor = TestHarness.Banker()
        }, Policy);

        decision.Outcome.Should().Be(DecisionOutcome.NotPermitted);
        decision.RequiredRung.Should().Be(Rung.L3);
    }

    [Fact]
    public void An_L3_action_is_refused_before_anything_else_happens()
    {
        var decision = Evaluator.Evaluate(new EvaluationContext
        {
            ActionId = "user.role.promote",
            Payload = new JObject { ["userId"] = "u-1", ["role"] = "admin" },
            Actor = TestHarness.Banker()
        }, Policy);

        decision.Outcome.Should().Be(DecisionOutcome.NotPermitted);
        decision.RejectionReason.Should().Contain("outside the Copilot's authority");
    }

    [Fact]
    public void Missing_evidence_refuses_before_any_policy_math()
    {
        var decision = Evaluator.Evaluate(new EvaluationContext
        {
            ActionId = "transaction.flag.review",
            Payload = new JObject { ["transactionId"] = "txn-1", ["decision"] = "cleared" },
            Evidence = new JObject(),
            Actor = TestHarness.Banker()
        }, Policy);

        decision.Outcome.Should().Be(DecisionOutcome.UnderEvidenced);
        decision.EvidenceGaps.Should().Contain("get_flagged_transaction");
    }

    [Fact]
    public void An_action_whose_base_rung_is_L2_never_evaluates_below_L2()
    {
        var decision = Evaluator.Evaluate(new EvaluationContext
        {
            ActionId = "user.unlock",
            Payload = new JObject { ["userId"] = "u-1", ["reason"] = "Verified by phone." },
            Evidence = new JObject
            {
                ["get_user"] = new JObject { ["userId"] = "u-1", ["status"] = "locked" },
                ["list_login_audits"] = new JObject { ["userId"] = "u-1", ["count"] = 3 }
            },
            Actor = TestHarness.Banker()
        }, Policy);

        decision.RequiredRung.Should().Be(Rung.L2);
        decision.RequiredSigners.Should().BeGreaterThanOrEqualTo(2);
    }

    // =====================================================================================

    private static PolicyDecision Evaluate(int mask, Action<JObject>? mutatePayload = null)
    {
        return Evaluate(Policy, mask, mutatePayload);
    }

    private static PolicyDecision Evaluate(
        int mask,
        Action<JObject, MutableActor> mutateActor,
        Action<JObject> mutateFacts)
    {
        return Evaluate(Policy, mask, null, mutateActor, mutateFacts);
    }

    private static PolicyDecision Evaluate(
        ResolvedPolicy policy,
        int mask,
        Action<JObject>? mutateFacts)
    {
        return Evaluate(policy, mask, null, (_, _) => { }, mutateFacts ?? (_ => { }));
    }

    private static PolicyDecision Evaluate(
        ResolvedPolicy policy,
        int mask,
        Action<JObject>? mutatePayload = null,
        Action<JObject, MutableActor>? mutateActor = null,
        Action<JObject>? mutateFacts = null)
    {
        var request = TestHarness.FlagReview("100.00");
        var facts = new JObject();
        var actor = new MutableActor();

        for (var bit = 0; bit < Fragments.Length; bit++)
        {
            if ((mask & (1 << bit)) != 0) Fragments[bit].Apply(facts, actor);
        }

        mutatePayload?.Invoke(request.Payload);
        mutateActor?.Invoke(facts, actor);
        mutateFacts?.Invoke(facts);

        return Evaluator.Evaluate(new EvaluationContext
        {
            ActionId = request.ActionId,
            Payload = request.Payload,
            Evidence = request.Evidence,
            Facts = facts,
            Actor = new ActorContext
            {
                UserId = "banker-1",
                Username = "banker-1",
                Role = "banker",
                EffectiveRoles = ["banker"],
                Seniority = 1,
                SessionId = "sess-1",
                SignaturesInWindow = actor.SignaturesInWindow,
                MutatingProposalsInWindow = actor.MutatingProposalsInWindow,
                SelfDealing = actor.SelfDealing
            }
        }, policy);
    }

    private static void Set(JObject facts, string group, string field, JToken value)
    {
        if (facts[group] is not JObject node)
        {
            node = new JObject();
            facts[group] = node;
        }

        node[field] = value;
    }

    private class MutableActor
    {
        public bool SelfDealing { get; set; }
        public int SignaturesInWindow { get; set; }
        public int MutatingProposalsInWindow { get; set; }
    }
}
