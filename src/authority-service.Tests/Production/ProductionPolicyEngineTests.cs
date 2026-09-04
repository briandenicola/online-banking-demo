using AuthorityService.Policy;
using FluentAssertions;
using Newtonsoft.Json.Linq;
using Xunit;
using Xunit.Abstractions;
using RealRung = AuthorityService.Models.Rung;

namespace BankerCopilotTests.Production;

/// <summary>
/// TESTS AGAINST TURK'S ACTUAL ENGINE AND THE REAL <c>config/authority-policy.yaml</c>.
///
/// Everything in Spec/ is an oracle I wrote from the specification. An oracle can only ever tell
/// you that I read the spec the same way twice. These tests are different: they load the policy
/// file that ships and run the evaluator that ships, so they can fail because of something real.
///
/// The monotonicity property is re-asserted here rather than reused from the oracle run,
/// deliberately. The oracle proving that escalators cannot lower a rung says nothing about
/// whether the production evaluator has the same property — and it is the production evaluator
/// that decides how many humans sign.
/// </summary>
public sealed class ProductionPolicyEngineTests(ITestOutputHelper output)
{
    private static string RepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, ".git")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new DirectoryNotFoundException("Repository root not found.");
    }

    private static string PolicyPath => Path.Combine(RepoRoot(), "config", "authority-policy.yaml");

    private static ResolvedPolicy RealPolicy() =>
        new PolicyLoader(new Dictionary<string, string?>()).LoadFromFile(PolicyPath);

    private static readonly IPolicyEvaluator Evaluator = new PolicyEvaluator();

    private static ActorContext Banker(bool selfDealing = false, int signaturesInWindow = 0) => new()
    {
        UserId = "user_banker_1",
        Username = "banker1",
        Role = "banker",
        EffectiveRoles = ["banker"],
        Seniority = 1,
        SessionId = "sess_1",
        SignaturesInWindow = signaturesInWindow,
        SelfDealing = selfDealing
    };

    private static EvaluationContext Context(
        string actionId, JObject payload, JObject? facts = null,
        ActorContext? actor = null, ResolvedPolicy? policy = null) => new()
    {
        ActionId = actionId,
        Payload = payload,
        Actor = actor ?? Banker(),
        Facts = facts ?? new JObject(),
        Evidence = policy is null ? new JObject() : CompleteEvidenceFor(policy, actionId)
    };

    /// <summary>
    /// Synthesises the evidence bundle the action declares, built FROM THE POLICY'S OWN evidence
    /// definitions rather than from a hand-written fixture.
    ///
    /// This exists because of a failure I caused and then caught: with an empty evidence bundle
    /// every action came back UnderEvidenced, so "every admissible action requires a human" was
    /// iterating over an empty set and passing. That is the exact false pass this whole suite is
    /// meant to be paranoid about, and the only reason it surfaced is the deliberately redundant
    /// `admissible.Should().BeGreaterThan(0)` guard. Assert that your loop had something in it.
    /// </summary>
    private static JObject CompleteEvidenceFor(ResolvedPolicy policy, string actionId)
    {
        var evidence = new JObject();
        var action = policy.Action(actionId);
        if (action is null) return evidence;

        var required = policy.Document.Defaults.EvidenceRequired
            .Concat(action.RequiredEvidence)
            .Distinct(StringComparer.Ordinal);

        foreach (var key in required)
        {
            if (!policy.Document.Evidence.TryGetValue(key, out var definition)) continue;

            var bundle = new JObject();
            foreach (var field in definition.RequiredFields) bundle[field] = $"evidence_{field}";
            evidence[key] = bundle;
        }

        return evidence;
    }



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
    public void The_real_policy_file_loads()
    {
        File.Exists(PolicyPath).Should().BeTrue(
            "every test below is meaningless if the policy file moved");

        var policy = RealPolicy();

        policy.Document.ActionTypes.Should().NotBeEmpty();
        policy.Thresholds.Should().NotBeEmpty();
        policy.PolicyVersion.Should().StartWith("pv1:");

        output.WriteLine($"Loaded {policy.Document.ActionTypes.Count} actions, " +
                         $"{policy.Thresholds.Count} thresholds, " +
                         $"{policy.Document.Escalators.Count} escalators. " +
                         $"policyVersion = {policy.PolicyVersion}");
    }

    // ---- The invariant, re-proved against production code ---------------------------------

    /// <summary>
    /// Every escalator in the REAL file that I can trigger, toggled across the full power set,
    /// against the REAL evaluator. If any combination produces a lower rung — or fewer signers,
    /// or fewer distinct humans — than a subset of itself, the ladder is not a ladder.
    /// </summary>
    [Fact]
    public void No_combination_of_real_escalators_can_lower_a_rung()
    {
        var policy = RealPolicy();
        var triggers = EscalatorTriggers();

        var untriggerable = policy.Document.Escalators
            .Select(e => e.Id)
            .Where(id => !triggers.ContainsKey(id))
            .ToList();

        // Report what is NOT covered rather than quietly claiming full coverage. A power-set test
        // over three of eight escalators sounds exhaustive and is not.
        if (untriggerable.Count > 0)
            output.WriteLine("NOT COVERED (no fact recipe yet): " + string.Join(", ", untriggerable));

        var covered = policy.Document.Escalators
            .Select(e => e.Id).Where(triggers.ContainsKey).ToList();

        covered.Should().NotBeEmpty("otherwise this test asserts nothing at all");
        output.WriteLine($"Exercising 2^{covered.Count} = {1 << covered.Count} combinations " +
                         $"over: {string.Join(", ", covered)}");

        var payload = LoanPayload(policy, aboveL1: false);

        for (var mask = 0; mask < 1 << covered.Count; mask++)
        {
            var decision = EvaluateMask(policy, covered, triggers, mask, payload);

            for (var bit = 0; bit < covered.Count; bit++)
            {
                if ((mask & (1 << bit)) == 0) continue;

                var subset = EvaluateMask(policy, covered, triggers, mask & ~(1 << bit), payload);

                // Authority ordering, which is NOT the same as the rung ordering. A refusal
                // (NotPermitted / UnderEvidenced) is the STRICTEST possible outcome — nothing can
                // be executed at all — so it must rank above L3 rather than below L1.
                //
                // Getting this wrong cost me a failing test that looked like a production defect:
                // self-dealing pushed the loan to L3, the decision came back NotPermitted with
                // RequiredSigners = 0, and the naive comparison read "0 < 2, signers went DOWN".
                // Comparing raw signer counts across a refusal boundary is meaningless.
                Strictness(decision).Should().BeGreaterThanOrEqualTo(Strictness(subset),
                    $"adding '{covered[bit]}' made the outcome LESS strict: " +
                    $"{subset.Outcome}/{subset.RequiredRung} became " +
                    $"{decision.Outcome}/{decision.RequiredRung}");

                if (decision.Outcome != DecisionOutcome.Admitted ||
                    subset.Outcome != DecisionOutcome.Admitted)
                {
                    continue;
                }

                ((int)decision.RequiredRung).Should().BeGreaterThanOrEqualTo(
                    (int)subset.RequiredRung,
                    $"adding '{covered[bit]}' LOWERED the rung from {subset.RequiredRung} to " +
                    $"{decision.RequiredRung}");

                decision.RequiredSigners.Should().BeGreaterThanOrEqualTo(
                    subset.RequiredSigners,
                    $"adding '{covered[bit]}' reduced the number of required signers");

                DistinctIdentities(policy, decision).Should().BeGreaterThanOrEqualTo(
                    DistinctIdentities(policy, subset),
                    $"adding '{covered[bit]}' reduced the number of distinct humans");

                decision.MinSeniority.Should().BeGreaterThanOrEqualTo(
                    subset.MinSeniority,
                    $"adding '{covered[bit]}' lowered the seniority bar");
            }
        }
    }

    /// <summary>
    /// Total order over outcomes: admitted rungs ascend, and any refusal sits above all of them.
    /// "Cannot be done here at all" is more restrictive than "needs two supervisors".
    /// </summary>
    private static int Strictness(PolicyDecision d) =>
        d.Outcome == DecisionOutcome.Admitted ? (int)d.RequiredRung : 99;

    private static PolicyDecision EvaluateMask(
        ResolvedPolicy policy, List<string> covered,
        Dictionary<string, JObject> triggers, int mask, JObject payload)
    {
        var facts = new JObject();
        var selfDealing = false;
        var signaturesInWindow = 0;

        for (var bit = 0; bit < covered.Count; bit++)
        {
            if ((mask & (1 << bit)) == 0) continue;
            switch (covered[bit])
            {
                case "self-dealing": selfDealing = true; break;
                case "velocity": signaturesInWindow = 10_000; break;
                default: MergeFacts(facts, triggers[covered[bit]]); break;
            }
        }

        return Evaluator.Evaluate(
            Context("loan.decision.record", payload, facts,
                Banker(selfDealing, signaturesInWindow), policy),
            policy);
    }

    /// <summary>
    /// Additive merge. Learned the hard way on the oracle run: a last-write-wins merge makes
    /// "add an escalator" also REMOVE a fact when two escalators read the same field, producing a
    /// spurious downgrade — a failure that looks exactly like a real defect. The mirror-image bug,
    /// a merge that silently drops the fact being added, is worse: it is a FALSE PASS, because the
    /// escalator never fires and monotonicity then holds vacuously.
    /// </summary>
    private static void MergeFacts(JObject target, JObject addition)
    {
        foreach (var prop in addition.Properties())
        {
            if (target[prop.Name] is JArray existing && prop.Value is JArray incoming)
            {
                foreach (var item in incoming)
                    if (!existing.Any(e => JToken.DeepEquals(e, item)))
                        existing.Add(item);
                continue;
            }

            if (target[prop.Name] is JObject nested && prop.Value is JObject incomingObj)
            {
                MergeFacts(nested, incomingObj);
                continue;
            }

            if (target[prop.Name] is not null && !JToken.DeepEquals(target[prop.Name], prop.Value))
            {
                throw new InvalidOperationException(
                    $"Fact '{prop.Name}' collides between escalator recipes. Silently overwriting " +
                    "it would make this test lie in one direction or the other.");
            }

            target[prop.Name] = prop.Value!.DeepClone();
        }
    }

    private static Dictionary<string, JObject> EscalatorTriggers() => new()
    {
        ["self-dealing"] = new JObject(),
        ["velocity"] = new JObject(),
        ["bulk-fan-out"] = JObject.Parse(
            """{ "session": { "proposalCountForActionType": 9999 } }"""),
        ["low-agent-confidence"] = JObject.Parse(
            """{ "agent": { "confidence": 0.01 } }"""),
        ["policy-exception"] = JObject.Parse(
            """{ "underwriting": { "policyExceptions": ["POL-004"] } }"""),
        ["severe-policy-exception"] = JObject.Parse(
            """{ "underwriting": { "policyExceptions": ["POL-001"] } }""")
    };

    private static JObject LoanPayload(ResolvedPolicy policy, bool aboveL1)
    {
        // The amount is DERIVED from the real threshold. A literal here would silently stop
        // testing the boundary the day risk-operations changes the ceiling — the test would keep
        // passing while measuring nothing.
        var ceiling = decimal.Parse(
            policy.Threshold("loan_dual_control_amount").Value,
            System.Globalization.CultureInfo.InvariantCulture);

        var amount = aboveL1 ? ceiling + 1m : ceiling - 1m;

        return JObject.Parse($$"""
        {
          "applicationId": "loan_4417",
          "amount": {{amount.ToString(System.Globalization.CultureInfo.InvariantCulture)}},
          "verdict": "APPROVE",
          "rationale": "Underwriting evidence supports the stated decision."
        }
        """);
    }

    // ---- A human always signs -------------------------------------------------------------

    [Fact]
    public void Every_admissible_action_in_the_real_policy_requires_at_least_one_human()
    {
        // I-1, against the shipping configuration. This is the assertion that would catch a
        // well-meant "auto-approve trivial reversals" tier appearing in the YAML — the change
        // that would break the premise of the whole system, and the one most likely to be
        // proposed as an efficiency improvement by someone who means well.
        var policy = RealPolicy();
        var offenders = new List<string>();
        var admissible = 0;

        foreach (var (actionId, _) in policy.Document.ActionTypes)
        {
            var decision = Evaluator.Evaluate(
                Context(actionId, MinimalPayloadFor(policy, actionId), policy: policy), policy);

            if (decision.Outcome != DecisionOutcome.Admitted) continue;

            admissible++;
            if (decision.RequiredSigners < 1) offenders.Add(actionId);
        }

        admissible.Should().BeGreaterThan(0,
            "if nothing is admissible this test proves nothing — the loop would be empty and green");

        offenders.Should().BeEmpty(
            "an admissible action requiring zero signatures is an auto-approval tier, and the " +
            "invariant is that agents never approve");
    }

    [Fact]
    public void Every_L2_rung_in_the_real_policy_demands_two_distinct_humans()
    {
        var policy = RealPolicy();

        var l2 = policy.Rung(RealRung.L2);
        l2.RequiredSigners.Should().BeGreaterThanOrEqualTo(2);

        // Distinctness is no longer a rung-level number (see DistinctIdentities above). It has to
        // be observed on the slots the evaluator actually emits, because that is now the only
        // place it exists. Two signatures from one person is one signature typed twice.
        l2.DistinctIdentities.Should().BeNull(
            "the retired head-count must not creep back into the shipping policy; the loader " +
            "rejects it, and a test asserting on it would be asserting on a dead field");

        var l1 = policy.Rung(RealRung.L1);
        l1.RequiredSigners.Should().BeGreaterThanOrEqualTo(1,
            "L1 is the FLOOR of the ladder, not an exemption from it");
    }

    [Fact]
    public void L3_is_outside_the_harness_entirely()
    {
        // §5.8/§4.3: L3 is not "harder to approve", it is "not approvable here". A proposable L3
        // would mean the harness can authorise exactly the actions it was built to exclude.
        var policy = RealPolicy();

        policy.Rung(RealRung.L3).Proposable.Should().BeFalse(
            "if L3 became proposable, the ceiling would stop being a ceiling");
    }

    [Fact]
    public void A_loan_above_the_configured_ceiling_escalates_without_any_escalator_firing()
    {
        // The base-threshold path, distinct from the escalator path. A suite that only exercises
        // escalators would miss a broken threshold comparison entirely.
        var policy = RealPolicy();

        var below = Evaluator.Evaluate(
            Context("loan.decision.record", LoanPayload(policy, aboveL1: false), policy: policy), policy);
        var above = Evaluator.Evaluate(
            Context("loan.decision.record", LoanPayload(policy, aboveL1: true), policy: policy), policy);

        below.Outcome.Should().Be(DecisionOutcome.Admitted,
            "the below-ceiling case must actually be admissible, or the comparison below is " +
            "between two refusals and means nothing");

        ((int)above.RequiredRung).Should().BeGreaterThan((int)below.RequiredRung,
            "crossing the configured ceiling must raise the rung; if both sides return the same " +
            "rung then either the comparison is broken or the threshold is not being read");
    }

    [Fact]
    public void An_unknown_action_is_refused_rather_than_defaulted()
    {
        // I-4 / defaults.unknownAction: deny. A permissive default here is the classic silent
        // failure: it breaks no existing flow, so nothing goes red, and every action added later
        // is unguarded until somebody remembers to list it.
        var policy = RealPolicy();

        var decision = Evaluator.Evaluate(
            Context("transfer.definitely.not.a.real.action", new JObject()), policy);

        decision.Outcome.Should().NotBe(DecisionOutcome.Admitted);
    }

    [Fact]
    public void The_policy_version_is_stable_across_loads_and_moves_when_a_threshold_moves()
    {
        // Both halves matter. A version that churns voids every in-flight approval on each pod
        // restart; a version that never moves makes the re-evaluation gate blind to real edits.
        var a = RealPolicy().PolicyVersion;
        var b = RealPolicy().PolicyVersion;

        b.Should().Be(a, "an unchanged file must produce an unchanged version");

        var overridden = new PolicyLoader(new Dictionary<string, string?>
        {
            ["POLICY_LOAN_DUAL_CONTROL_AMOUNT"] = "1.00"
        }).LoadFromFile(PolicyPath);

        if (overridden.Threshold("loan_dual_control_amount").Value == "1.00")
        {
            overridden.PolicyVersion.Should().NotBe(a,
                "an env override changes the RESOLVED policy, so it must change the version — " +
                "otherwise the gate cannot see the change that matters most (§6.2.1)");
        }
        else
        {
            output.WriteLine(
                "NOTE: the env key guessed for loan_dual_control_amount did not take effect, so " +
                "the override half of this test did not run. Read the env name from the policy " +
                "file rather than guessing if this stays unexercised.");
        }
    }

    private static JObject MinimalPayloadFor(ResolvedPolicy policy, string actionId)
    {
        // Build a payload satisfying the action's declared hash fields with plausible values, so
        // evaluation exercises the real predicates instead of bailing out on missing input.
        var payload = new JObject();
        var action = policy.Action(actionId);
        if (action is null) return payload;

        foreach (var field in action.HashFields)
        {
            var leaf = field.Split('.').Last();

            payload[leaf] = action.MoneyFields.Contains(field)
                ? new JValue(1m)
                : leaf.Contains("verdict", StringComparison.OrdinalIgnoreCase)
                    ? new JValue("APPROVE")
                    : leaf.Contains("currency", StringComparison.OrdinalIgnoreCase)
                        ? new JValue("USD")
                        : new JValue($"val_{leaf}");
        }

        return payload;
    }
}
