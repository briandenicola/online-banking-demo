using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;
using Xunit.Abstractions;

namespace BankerCopilotTests.Engine;

/// <summary>
/// I-4 as an executable invariant: "for all policies and payloads, adding an escalator match
/// never lowers the returned rung."
///
/// EXHAUSTIVE, not random. The escalator set is small enough (8 escalators ⇒ 256 subsets) that
/// the full power set is cheaper than a property-based library and strictly stronger than
/// sampling. Randomised fuzz runs alongside it for the payload dimension.
///
/// ⚠️ WHAT A GREEN RUN HERE PROVES: that the SPECIFIED algorithm is monotonic. It does NOT yet
/// prove authority-service is, because authority-service does not exist. See the Phase 1 test
/// plan §"False passes" — this becomes a differential test the moment Turk's evaluator is
/// wired in behind IPolicyEvaluator.
/// </summary>
public sealed class MonotonicityPropertyTests(ITestOutputHelper output)
{
    private readonly IPolicyEvaluator _evaluator = new SpecReferenceEvaluator();

    /// <summary>Every fact combination that can make an escalator fire, one flag per escalator.</summary>
    private static IReadOnlyList<(string Key, KeyValuePair<string, object?>[] Facts)> EscalatorTriggers(Policy p) =>
    [
        ("self-dealing", [new("context.selfDealing", true)]),
        ("bulk-fan-out", [new("session.proposalCountForActionType",
            decimal.Parse(p.Thresholds["bulk_fanout_count"]) + 1)]),
        ("velocity", [new("actor.signaturesInWindow",
            decimal.Parse(p.Thresholds["velocity_signatures_in_window"]) + 1)]),
        ("low-agent-confidence", [new("agent.confidence",
            decimal.Parse(p.Thresholds["low_agent_confidence_floor"]) - 0.01m)]),
        ("policy-exception", [new("underwriting.policyExceptions", new List<object?> { "POL-004" })]),
        ("severe-policy-exception", [new("underwriting.policyExceptions", new List<object?> { "POL-001" })]),
        ("high-risk-customer", [new("customer.riskTier", "high")]),
        ("anomalous-session", [new("session.anomalyScore",
            decimal.Parse(p.Thresholds["session_anomaly_score"]))])
    ];

    [Fact]
    public void No_escalator_subset_lowers_the_rung_below_the_base_rung()
    {
        var policy = TestData.Baseline();
        var triggers = EscalatorTriggers(policy);
        var checkedCombos = 0;

        foreach (var actionId in ProposableActions(policy))
        {
            var baseRung = RungOrder.Parse(policy.Actions[actionId].BaseRung);

            foreach (var subset in PowerSet(triggers))
            {
                var ctx = ContextFor(policy, actionId, Merge(subset));
                var decision = _evaluator.Evaluate(ctx, policy);
                checkedCombos++;

                // An L3 outcome is INADMISSIBLE, not a lowered rung — it is the top of the order.
                var effective = decision.Admissible ? decision.RequiredRung : Rung.L3;

                ((int)effective).Should().BeGreaterThanOrEqualTo((int)baseRung,
                    $"escalator subset [{string.Join(",", subset.Select(s => s.Key))}] on " +
                    $"'{actionId}' produced {effective}, below its base rung {baseRung}. " +
                    "I-4: nothing in the system may lower a rung.");
            }
        }

        output.WriteLine($"Exhaustively checked {checkedCombos} (action × escalator-subset) combinations.");
        checkedCombos.Should().BeGreaterThan(0, "a vacuous pass is the failure mode this test exists to avoid");
    }

    [Fact]
    public void Adding_any_escalator_to_any_subset_never_lowers_the_result()
    {
        // The stronger statement: max(S ∪ {r}) >= max(S) for EVERY S and EVERY r, not just
        // versus the base. This is the one that catches a "last rule wins" implementation.
        var policy = TestData.Baseline();
        var triggers = EscalatorTriggers(policy);
        var comparisons = 0;

        foreach (var actionId in ProposableActions(policy))
        {
            foreach (var subset in PowerSet(triggers))
            {
                var withoutRung = EffectiveRung(policy, actionId, Merge(subset));

                foreach (var extra in triggers.Where(t => subset.All(s => s.Key != t.Key)))
                {
                    var augmented = subset.Append(extra).ToList();
                    var withRung = EffectiveRung(policy, actionId, Merge(augmented));
                    comparisons++;

                    ((int)withRung).Should().BeGreaterThanOrEqualTo((int)withoutRung,
                        $"adding escalator '{extra.Key}' to " +
                        $"[{string.Join(",", subset.Select(s => s.Key))}] on '{actionId}' " +
                        $"moved the rung DOWN from {withoutRung} to {withRung}. " +
                        "Escalators are monotonic (I-4).");
                }
            }
        }

        output.WriteLine($"Checked {comparisons} add-one-escalator monotonicity comparisons.");
        comparisons.Should().BeGreaterThan(0);
    }

    [Fact]
    public void Evaluation_order_does_not_change_the_result()
    {
        // max is commutative and associative (§3.4 point 2), so there must be no "last rule
        // wins" hazard. Shuffle the escalator list and re-evaluate.
        var policy = TestData.Baseline();
        var triggers = EscalatorTriggers(policy);
        var rng = new Random(20260904);   // seeded: a flaky property test is worse than none

        foreach (var subset in PowerSet(triggers))
        {
            var facts = Merge(subset);
            var expected = EffectiveRung(policy, "loan.decision.record", facts);

            for (var i = 0; i < 5; i++)
            {
                var shuffled = policy with
                {
                    Escalators = policy.Escalators.OrderBy(_ => rng.Next()).ToList()
                };

                EffectiveRung(shuffled, "loan.decision.record", facts).Should().Be(expected,
                    "evaluation order must be irrelevant — max is commutative and associative");
            }
        }
    }

    [Fact]
    public void Randomised_payload_fuzz_never_produces_a_rung_below_base()
    {
        var policy = TestData.Baseline();
        var rng = new Random(1729);
        var l1Max = decimal.Parse(policy.Thresholds["loan_l1_max"]);
        var l2Max = decimal.Parse(policy.Thresholds["loan_l2_max"]);
        var verdicts = new[] { "APPROVE", "CONDITIONAL", "DECLINE" };
        var tiers = new[] { "low", "medium", "high", "pep", "sanctions_hit" };

        for (var i = 0; i < 2_000; i++)
        {
            var amount = Math.Round((decimal)(rng.NextDouble() * (double)(l2Max * 1.5m)), 2);
            var ctx = TestData.LoanDecision(
                policy,
                amount,
                verdicts[rng.Next(verdicts.Length)],
                facts: new Dictionary<string, object?>
                {
                    ["customer.riskTier"] = tiers[rng.Next(tiers.Length)],
                    ["agent.confidence"] = Math.Round((decimal)rng.NextDouble(), 2),
                    ["context.selfDealing"] = rng.Next(2) == 0,
                    ["session.anomalyScore"] = Math.Round((decimal)rng.NextDouble(), 2)
                });

            var decision = _evaluator.Evaluate(ctx, policy);
            var effective = decision.Admissible ? decision.RequiredRung : Rung.L3;

            ((int)effective).Should().BeGreaterThanOrEqualTo((int)Rung.L1);

            // A loan at or above the L1 ceiling must never come back single-signature.
            if (amount >= l1Max)
            {
                ((int)effective).Should().BeGreaterThanOrEqualTo((int)Rung.L2,
                    $"a loan of {amount} is at or above the configured L1 ceiling {l1Max}");
            }
        }
    }

    [Fact]
    public void Required_signers_and_distinct_identities_are_also_monotonic()
    {
        // §3.4 point 4: the same argument applies pointwise to required_signers and
        // min_seniority, which are folded with max over ℕ. A rung that rose while the signer
        // count fell would be a downgrade wearing a disguise.
        var policy = TestData.Baseline();
        var triggers = EscalatorTriggers(policy);

        foreach (var subset in PowerSet(triggers))
        {
            var baseDecision = _evaluator.Evaluate(
                ContextFor(policy, "transfer.reverse", Merge(subset)), policy);
            if (!baseDecision.Admissible) continue;

            foreach (var extra in triggers.Where(t => subset.All(s => s.Key != t.Key)))
            {
                var augmented = _evaluator.Evaluate(
                    ContextFor(policy, "transfer.reverse", Merge(subset.Append(extra).ToList())),
                    policy);
                if (!augmented.Admissible) continue;

                augmented.RequiredSigners.Should().BeGreaterThanOrEqualTo(baseDecision.RequiredSigners,
                    $"adding '{extra.Key}' reduced the required signer count");
                augmented.DistinctIdentitiesRequired.Should()
                    .BeGreaterThanOrEqualTo(baseDecision.DistinctIdentitiesRequired,
                        $"adding '{extra.Key}' reduced the distinct-identity requirement");
            }
        }
    }

    [Fact]
    public void A_human_always_signs_regardless_of_how_permissive_the_config_is()
    {
        // §3.4 corollary: the worst config-driven outcome is "one banker signed something that
        // should have needed two", never "no human signed". signers >= 1 is a CODE-level floor
        // outside the config surface. Prove it by handing the engine a maximally permissive rung
        // spec — requiredSigners 0 — and confirming the floor still holds.
        var policy = TestData.Baseline();
        var neutered = policy with
        {
            Rungs = new Dictionary<string, RungSpec>(policy.Rungs)
            {
                ["L1"] = policy.Rungs["L1"] with { RequiredSigners = 0, DistinctIdentities = 0 }
            }
        };

        var decision = _evaluator.Evaluate(TestData.TransferReversal(neutered), neutered);

        decision.Admissible.Should().BeTrue();
        decision.RequiredSigners.Should().BeGreaterThanOrEqualTo(1,
            "I-1: there is no auto-execute tier. A config value can never drive the signer " +
            "count below one.");
        decision.SignerRequirements.Should().NotBeEmpty();
    }

    // ---- helpers ----------------------------------------------------------------------

    private Rung EffectiveRung(Policy policy, string actionId, IDictionary<string, object?> facts)
    {
        var decision = _evaluator.Evaluate(ContextFor(policy, actionId, facts), policy);
        return decision.Admissible ? decision.RequiredRung : Rung.L3;
    }

    private static IEnumerable<string> ProposableActions(Policy policy) =>
        policy.Actions.Where(kv => kv.Value.AgentMayPropose && kv.Value.BaseRung != "L3")
                      .Select(kv => kv.Key);

    private static EvaluationContext ContextFor(
        Policy policy, string actionId, IDictionary<string, object?> facts) =>
        actionId switch
        {
            "loan.decision.record" => TestData.LoanDecision(policy, facts: facts),
            "transfer.reverse" => TestData.TransferReversal(policy, facts: facts),
            _ => new EvaluationContext
            {
                ActionId = actionId,
                RequesterId = TestData.Banker,
                Payload = MinimalPayload(policy.Actions[actionId]),
                Facts = new Dictionary<string, object?>(facts),
                EvidenceProvided = policy.Actions[actionId].RequiredEvidence
            }
        };

    private static Dictionary<string, object?> MinimalPayload(ActionSpec action)
    {
        var payload = new Dictionary<string, object?>();
        foreach (var f in action.HashFields)
            payload[f] = action.MoneyFields.Contains(f) ? 1m : "x";
        payload["transferAgeHours"] = 0;
        return payload;
    }

    /// <summary>
    /// Merging must be ADDITIVE, not last-write-wins.
    ///
    /// The first version of this harness overwrote shared fact keys, so "add the policy-exception
    /// escalator to a set already containing severe-policy-exception" actually REPLACED
    /// underwriting.policyExceptions = ["POL-001"] with ["POL-004"] — removing the severe code
    /// and legitimately lowering the rung. That produced a monotonicity failure that was a bug in
    /// the test, not in the algorithm.
    ///
    /// It is worth keeping the note: a monotonicity harness whose "add one" operation can also
    /// remove a fact is not testing monotonicity at all, and the failure mode in the other
    /// direction — a merge that silently drops the new fact — would have been a FALSE PASS.
    /// List-valued facts are unioned; scalar facts are asserted not to collide.
    /// </summary>
    private static Dictionary<string, object?> Merge(
        IEnumerable<(string Key, KeyValuePair<string, object?>[] Facts)> subset)
    {
        var merged = new Dictionary<string, object?>();

        foreach (var (_, facts) in subset)
        {
            foreach (var kv in facts)
            {
                if (merged.TryGetValue(kv.Key, out var existing)
                    && existing is List<object?> existingList
                    && kv.Value is List<object?> incoming)
                {
                    merged[kv.Key] = existingList.Union(incoming).ToList();
                    continue;
                }

                if (merged.ContainsKey(kv.Key))
                {
                    throw new InvalidOperationException(
                        $"Two escalator triggers write the scalar fact '{kv.Key}'. Adding an " +
                        "escalator must never overwrite another's precondition, or this harness " +
                        "is testing fact substitution rather than monotonicity.");
                }

                merged[kv.Key] = kv.Value;
            }
        }

        return merged;
    }

    private static IEnumerable<List<T>> PowerSet<T>(IReadOnlyList<T> items)
    {
        var total = 1 << items.Count;
        for (var mask = 0; mask < total; mask++)
        {
            var subset = new List<T>();
            for (var i = 0; i < items.Count; i++)
                if ((mask & (1 << i)) != 0) subset.Add(items[i]);
            yield return subset;
        }
    }
}
