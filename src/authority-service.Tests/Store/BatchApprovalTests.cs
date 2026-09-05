using AuthorityService.Policy;
using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;
using SpecPolicy = BankerCopilotTests.Spec.Policy;
using SpecLoader = BankerCopilotTests.Spec.PolicyLoader;
using ProdLoader = AuthorityService.Policy.PolicyLoader;

namespace BankerCopilotTests.Store;

/// <summary>
/// Invariant I-10 — a batch is L1-only, within one action type. Epic Phase 3 milestone bullet
/// ("Batch approval within one action type, L1 only") and the policy file's
/// <c>defaults.batchApproval</c> block (<c>maxRung: L1</c>, <c>sameActionTypeOnly: true</c>).
///
/// The requirement is that L2 batching is IMPOSSIBLE, not merely absent. Absence is a fact about
/// today's config; impossibility is a property of the guard. So this file attacks the guard from
/// two sides: the resolved-rung batch operation must refuse an escalated item (Spec oracle), and
/// the shipping loader must refuse a config that raises the cap (production).
/// </summary>
public sealed class BatchApprovalTests
{
    // ---- Spec oracle: the batch keys on the RESOLVED rung ----------------------------------

    private static (ApprovalStore Store, SpecPolicy Policy) BatchOfTwo(
        decimal firstAmount, decimal secondAmount)
    {
        var policy = TestData.Baseline();
        var version = SpecLoader.DerivePolicyVersion(policy);
        var store = new ApprovalStore();
        var evaluator = new SpecReferenceEvaluator();

        foreach (var (amount, i) in new[] { firstAmount, secondAmount }.Select((a, i) => (a, i)))
        {
            var ctx = TestData.LoanDecision(policy, amount);
            var decision = evaluator.Evaluate(ctx, policy);
            store.Propose($"apr_batch_{i}", ctx, decision, policy, version, TestData.T0);
        }

        return (store, policy);
    }

    [Fact]
    public void A_batch_of_two_L1_items_of_one_action_type_signs()
    {
        // The positive control. A guard that refused every batch would pass every negative case
        // below and break the feature — the same false-pass shape as a validator that rejects all.
        var (store, policy) = BatchOfTwo(1_000m, 2_000m);
        store.Get("apr_batch_0").RequiredRung.Should().Be(Rung.L1);
        store.Get("apr_batch_1").RequiredRung.Should().Be(Rung.L1);

        var signer = TestData.Principal(TestData.Banker, "banker", seniority: 1);
        var results = BatchSigner.SignBatch(
            store, ["apr_batch_0", "apr_batch_1"], signer, TestData.Hierarchy(), policy, TestData.T0);

        results.Should().OnlyContain(r => r.Accepted);
    }

    [Fact]
    public void A_batch_containing_an_L1_base_action_that_ESCALATED_to_L2_is_refused_whole()
    {
        // THE ATTACK. Both items are the same action type (loan.decision.record, baseRung L1).
        // The second is above the L1 ceiling, so it resolves to L2. A batch that keyed on baseRung
        // would wave it through; a batch that keys on the resolved rung refuses the whole batch.
        var l1Max = decimal.Parse(TestData.Baseline().Thresholds["loan_l1_max"]);
        var (store, policy) = BatchOfTwo(l1Max - 10_000m, l1Max + 10_000m);

        store.Get("apr_batch_0").RequiredRung.Should().Be(Rung.L1, "the small loan stays L1");
        store.Get("apr_batch_1").RequiredRung.Should().Be(Rung.L2,
            "the large loan escalated — this is the item a baseRung-keyed batch would miss");

        var signer = TestData.Principal(TestData.Banker, "banker", seniority: 1);

        var act = () => BatchSigner.SignBatch(
            store, ["apr_batch_0", "apr_batch_1"], signer, TestData.Hierarchy(), policy, TestData.T0);

        act.Should().Throw<BatchInvariantViolation>()
            .WithMessage("*above L1*");

        // Fail-closed AND all-or-nothing: the L1 item must NOT have been signed on the way to
        // discovering the L2 one. A partial batch that signed apr_batch_0 would be the quiet
        // failure — it looks like it worked.
        store.Get("apr_batch_0").SignatureSlots.Should().OnlyContain(s => !s.IsFilled,
            "no signature may be applied when the batch as a whole is inadmissible");
    }

    [Fact]
    public void A_batch_keys_on_required_rung_not_base_rung()
    {
        // The property named directly, so the finding survives even if the escalation math above
        // is later refactored. The escalated item's BASE rung is L1; its REQUIRED rung is L2; the
        // batch must read the latter.
        var l1Max = decimal.Parse(TestData.Baseline().Thresholds["loan_l1_max"]);
        var (store, _) = BatchOfTwo(l1Max - 10_000m, l1Max + 10_000m);

        var escalated = store.Get("apr_batch_1");
        escalated.BaseRung.Should().Be(Rung.L1);
        escalated.RequiredRung.Should().Be(Rung.L2);
        escalated.BaseRung.Should().NotBe(escalated.RequiredRung,
            "this divergence is exactly what a baseRung-keyed batch check would fail to see");
    }

    [Fact]
    public void A_batch_that_spans_two_action_types_is_refused()
    {
        // sameActionTypeOnly: true. Build one loan and one transfer, both L1, and prove the batch
        // still refuses — a cross-type batch is "Approve All" with extra steps even at L1.
        var policy = TestData.Baseline();
        var version = SpecLoader.DerivePolicyVersion(policy);
        var store = new ApprovalStore();
        var evaluator = new SpecReferenceEvaluator();

        var loan = TestData.LoanDecision(policy, 1_000m);
        store.Propose("apr_loan", loan, evaluator.Evaluate(loan, policy), policy, version, TestData.T0);
        var transfer = TestData.TransferReversal(policy, 100m);
        store.Propose("apr_transfer", transfer, evaluator.Evaluate(transfer, policy), policy, version, TestData.T0);

        store.Get("apr_loan").RequiredRung.Should().Be(Rung.L1);
        store.Get("apr_transfer").RequiredRung.Should().Be(Rung.L1);

        var signer = TestData.Principal(TestData.Banker, "banker", seniority: 1);
        var act = () => BatchSigner.SignBatch(
            store, ["apr_loan", "apr_transfer"], signer, TestData.Hierarchy(), policy, TestData.T0);

        act.Should().Throw<BatchInvariantViolation>().WithMessage("*action type*");
    }

    // ---- Production loader: a config that raises the batch cap is refused -------------------

    private static string RepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, ".git")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new DirectoryNotFoundException("Repository root not found.");
    }

    private static string RealPolicyYaml() =>
        File.ReadAllText(Path.Combine(RepoRoot(), "config", "authority-policy.yaml"));

    private static ResolvedPolicy LoadYaml(string yaml) =>
        new ProdLoader(new Dictionary<string, string?>()).LoadFromYaml(yaml, "<tampered>");

    [Fact]
    public void The_shipping_policy_caps_batches_at_L1_within_one_action_type()
    {
        // Read the real, shipping values — not a fixture. If the ships-today config ever regresses,
        // this is the test that says so.
        var resolved = LoadYaml(RealPolicyYaml());
        resolved.Document.Defaults.BatchApproval.MaxRung.Should().Be("L1");
        resolved.Document.Defaults.BatchApproval.SameActionTypeOnly.Should().BeTrue();
    }

    [Fact]
    public void The_loader_refuses_a_batch_cap_of_L2()
    {
        // Tamper the real YAML: raise the cap to L2 and prove Turk's loader refuses it. This is the
        // production guard for I-10, exercised against the shipping validator rather than the oracle.
        var tampered = RealPolicyYaml().Replace("maxRung: L1", "maxRung: L2");
        tampered.Should().Contain("maxRung: L2", "the tamper must actually change the config");

        var act = () => LoadYaml(tampered);
        act.Should().Throw<AuthorityService.Models.PolicyValidationException>()
            .WithMessage("*maxRung*L1*");
    }

    [Fact]
    public void The_loader_refuses_a_cross_action_type_batch_config()
    {
        var tampered = RealPolicyYaml().Replace("sameActionTypeOnly: true", "sameActionTypeOnly: false");
        tampered.Should().Contain("sameActionTypeOnly: false");

        var act = () => LoadYaml(tampered);
        act.Should().Throw<AuthorityService.Models.PolicyValidationException>()
            .WithMessage("*sameActionTypeOnly*");
    }

    // ---- F3-1 tripwire: no action may be both batchable and >L1 ------------------------------
    // FINDING F3-1: the loader enforces I-10 ("batch is L1-only") ONLY through the global
    // defaults.batchApproval.maxRung cap. It does NOT reject a per-action `batchable: true` on an
    // action whose baseRung is L2 (or whose rules escalate it to L2). I proved this empirically:
    // adding `batchable: true` to transaction.score.override (baseRung L2) loads WITHOUT error.
    // It is latent today — no action sets `batchable`, and no batch-sign endpoint exists — so I do
    // NOT assert the loader rejects it (that would be a false pass defending a gap that isn't
    // closed). Instead this pins the shipping config: the day someone marks an L2 action batchable,
    // this goes red and forces the loader fix. Keyed on baseRung; an L1 action that RULES up to L2
    // is a second, subtler variant recorded in the finding, not detectable from static config.
    [Fact]
    public void No_shipping_action_is_both_batchable_and_above_L1()
    {
        var resolved = LoadYaml(RealPolicyYaml());
        // Non-vacuity: the scan is worthless if the action corpus is empty. Anchor on the two L2
        // actions that ship today, so an empty/again-misparsed ActionTypes fails loudly instead of
        // passing this tripwire by scanning nothing (the empty-corpus false pass, learning #1).
        resolved.Document.ActionTypes.Keys.Should().Contain(
            new[] { "transaction.score.override", "user.unlock" },
            "the L2 actions must be present or this tripwire is scanning an empty corpus");
        var offenders = resolved.Document.ActionTypes
            .Where(kv => kv.Value.Batchable && kv.Value.BaseRung == "L2")
            .Select(kv => kv.Key)
            .ToList();
        offenders.Should().BeEmpty(
            "I-10 requires batch approval to be L1-only, but the loader does not enforce this " +
            "per-action (F3-1); if this fires, the config just defeated batch containment");
    }
}
