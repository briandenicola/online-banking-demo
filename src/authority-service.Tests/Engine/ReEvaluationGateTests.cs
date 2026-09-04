using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;
using Xunit.Abstractions;

namespace BankerCopilotTests.Engine;

/// <summary>
/// Epic §5.3.2 / engine §3.6. BOTH DIRECTIONS.
///
/// Brian's rule: "test both directions or you have tested neither." The asymmetry IS the ruling —
/// a tightening voids, a relaxation does not. A suite that only tests the tightening direction
/// would pass identically against a (wrong) symmetric implementation that voids on ANY policy
/// change, and that wrong implementation would churn bankers into distrusting the card.
/// </summary>
public sealed class ReEvaluationGateTests(ITestOutputHelper output)
{
    private readonly IPolicyEvaluator _evaluator = new SpecReferenceEvaluator();

    private ExecutionAuthorization.ReEvaluationGate Gate() => new(_evaluator);

    // ---- Direction 1: TIGHTENED ⇒ VOID -------------------------------------------------

    [Fact]
    public void Escalation_while_pending_voids_the_signature_and_refuses_execution()
    {
        // The canonical worked example: sign a loan at L1, then drop the L1 ceiling under it.
        var policy = TestData.Baseline();
        var l1Max = decimal.Parse(policy.Thresholds["loan_l1_max"]);
        var amount = l1Max - 10_000m;                    // comfortably L1 under the old policy

        var ctx = TestData.LoanDecision(policy, amount);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);

        approval.RequiredRung.Should().Be(Rung.L1, "the fixture must actually start at L1");

        var signed = store.Sign(approval.Id,
            TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "nonce_1", TestData.T0);
        signed.Accepted.Should().BeTrue();
        store.Get(approval.Id).Status.Should().Be(ApprovalStatus.Signed);

        // Ops drops the L1 ceiling below the signed amount — a ConfigMap edit, file unchanged.
        var tightened = policy.WithThreshold("loan_l1_max", (amount - 1m).ToString("F2"));
        var tightenedVersion = PolicyLoader.DerivePolicyVersion(tightened);
        tightenedVersion.Should().NotBe(version,
            "a resolved-policy content hash must notice a threshold override even though the " +
            "policy FILE is byte-identical (§6.2.1 point 2)");

        var outcome = Gate().Authorize(
            store.Get(approval.Id), tightened, tightenedVersion, ctx, TestData.T0.AddMinutes(1));

        outcome.Kind.Should().Be(GateOutcomeKind.VoidPolicyEscalated);
        outcome.NewRung.Should().Be(Rung.L2);
        outcome.Authorization.Should().BeNull("a void must not hand out an execution token");

        // The original goes terminal and immutable; a NEW approval carries the new rung.
        var newDecision = _evaluator.Evaluate(ctx, tightened);
        var (voided, replacement) = store.VoidByPolicyChange(
            approval.Id, outcome, ctx, newDecision, tightened, tightenedVersion,
            "apr_test_2", TestData.T0.AddMinutes(1));

        voided.Status.Should().Be(ApprovalStatus.Denied);
        voided.TerminalReason.Should().Be(Spec.TerminalReason.PolicyRungEscalated);
        voided.SupersededByApprovalId.Should().Be(replacement.Id);
        replacement.RequiredRung.Should().Be(Rung.L2);
        replacement.PayloadHash.Should().NotBe(voided.PayloadHash,
            "policyVersion is bound into the hash, so an escalation changes the visible hash — " +
            "which is what EXPLAINS the re-sign request to the banker (§5.3 point 4)");

        // (d) The discarded signature is recorded in full: whose, which slot, which rung, which
        //     policy version. This is the only event where a machine throws away a human's
        //     signature and it must not be reconstructible only by inference.
        voided.DiscardedSignatures.Should().ContainSingle();
        var discarded = voided.DiscardedSignatures[0];
        discarded.SignerId.Should().Be(TestData.Banker);
        discarded.SlotOrdinal.Should().Be(0);
        discarded.RungSatisfied.Should().Be(Rung.L1);
        discarded.BoundPolicyVersion.Should().Be(version);

        var evt = store.AuditLog.Single(e => e.EventType == "ApprovalVoidedByPolicyChange");
        evt.Data["signedRung"].Should().Be("L1");
        evt.Data["newRung"].Should().Be("L2");
        evt.Data["signedUnderPolicyVersion"].Should().Be(version);
        evt.Data["evaluatedUnderPolicyVersion"].Should().Be(tightenedVersion);
        evt.Data["supersededByApprovalId"].Should().Be(replacement.Id);
        evt.Data["discardedSignatures"].Should().NotBeNull();
    }

    [Fact]
    public void An_escalation_to_L3_refuses_entirely_whatever_was_signed()
    {
        var policy = TestData.Baseline();
        var ctx = TestData.LoanDecision(policy);
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        // Drop the L3 ceiling below the signed amount: the action leaves the harness entirely.
        var amount = (decimal)ctx.Payload["amount"]!;
        var l3 = policy.WithThreshold("loan_l2_max", (amount - 1m).ToString("F2"));

        var outcome = Gate().Authorize(
            store.Get(approval.Id), l3, PolicyLoader.DerivePolicyVersion(l3), ctx,
            TestData.T0.AddMinutes(1));

        outcome.Kind.Should().Be(GateOutcomeKind.VoidPolicyEscalated);
        outcome.NewRung.Should().Be(Rung.L3);
        outcome.Authorization.Should().BeNull();
    }

    // ---- Direction 2: RELAXED ⇒ HONOUR --------------------------------------------------

    [Fact]
    public void Relaxation_while_pending_honours_the_signature_and_the_action_executes()
    {
        // The direction that is easy to forget, and the one whose absence would hide a wrongly
        // symmetric "void on any policy change" implementation.
        var policy = TestData.Baseline();
        var l1Max = decimal.Parse(policy.Thresholds["loan_l1_max"]);
        var amount = l1Max + 10_000m;                    // starts ABOVE the ceiling ⇒ L2

        var ctx = TestData.LoanDecision(policy, amount);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);

        approval.RequiredRung.Should().Be(Rung.L2, "the fixture must actually start at L2");
        approval.RequiredSigners.Should().Be(2);

        // Two distinct humans sign.
        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n1", TestData.T0)
            .Accepted.Should().BeTrue();
        store.Sign(approval.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n2", TestData.T0)
            .Accepted.Should().BeTrue();

        store.Get(approval.Id).Status.Should().Be(ApprovalStatus.Signed);

        // Policy is RELAXED: the ceiling rises above the signed amount, so this would now be L1.
        var relaxed = policy.WithThreshold("loan_l1_max", (amount + 50_000m).ToString("F2"));
        var relaxedVersion = PolicyLoader.DerivePolicyVersion(relaxed);
        relaxedVersion.Should().NotBe(version);

        _evaluator.Evaluate(ctx, relaxed).RequiredRung.Should().Be(Rung.L1,
            "the relaxation must genuinely lower the required rung, or this test proves nothing");

        var outcome = Gate().Authorize(
            store.Get(approval.Id), relaxed, relaxedVersion, ctx, TestData.T0.AddMinutes(1));

        outcome.Kind.Should().Be(GateOutcomeKind.Proceed,
            "a signature given for MORE scrutiny than is now required is strictly safe. Voiding " +
            "on a downward change would punish a banker for a policy relaxation (§5.3.2).");
        outcome.Authorization.Should().NotBeNull();

        var executed = store.Execute(outcome.Authorization!, 200);
        executed.Status.Should().Be(ApprovalStatus.Executed);

        // No downgrade is applied and none is recorded: the audit trail preserves the rung that
        // was actually signed.
        executed.RequiredRung.Should().Be(Rung.L2);
        executed.SignatureSlots.Count(s => s.IsFilled).Should().Be(2,
            "the system never REMOVES a signature that was already given");
        executed.SignedUnderPolicyVersion.Should().Be(version);
        executed.EvaluatedUnderPolicyVersion.Should().Be(relaxedVersion);

        output.WriteLine(
            $"Honoured L2 signature under a relaxed policy: signed under {version}, " +
            $"evaluated under {relaxedVersion}.");
    }

    [Fact]
    public void An_unchanged_policy_proceeds_and_the_two_version_fields_are_equal()
    {
        var policy = TestData.Baseline();
        var ctx = TestData.LoanDecision(policy);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        var outcome = Gate().Authorize(
            store.Get(approval.Id), policy, version, ctx, TestData.T0.AddMinutes(1));

        outcome.Kind.Should().Be(GateOutcomeKind.Proceed);
        var executed = store.Execute(outcome.Authorization!, 201);
        executed.SignedUnderPolicyVersion.Should().Be(executed.EvaluatedUnderPolicyVersion);
    }

    [Fact]
    public void A_cosmetic_policy_edit_does_not_void_anything()
    {
        // "Any policy edit nukes all pending approvals" is the obvious WRONG implementation of
        // the ruling and the one a reasonable engineer reaches for first (§6.2.1). The hash
        // changes; nothing else may.
        var policy = TestData.Baseline();
        var ctx = TestData.LoanDecision(policy);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        // A change that alters the resolved content but not any rung outcome for this action.
        var cosmetic = policy.WithThreshold("flagged_txn_l2_amount", "25001.00");
        var cosmeticVersion = PolicyLoader.DerivePolicyVersion(cosmetic);
        cosmeticVersion.Should().NotBe(version, "the content hash must move");

        var outcome = Gate().Authorize(
            store.Get(approval.Id), cosmetic, cosmeticVersion, ctx, TestData.T0.AddMinutes(1));

        outcome.Kind.Should().Be(GateOutcomeKind.Proceed,
            "a changed hash by itself invalidates nothing — the gate keys off the RE-EVALUATED " +
            "RUNG, not off hash inequality (§6.2.1)");
    }

    // ---- The hash-recompute half of the same ruling --------------------------------------

    [Fact]
    public void Hash_recompute_uses_the_stored_policy_version_never_the_live_one()
    {
        // Engine §6.4: "getting this backwards silently converts the ruling into 'any policy
        // edit invalidates everything'". Verification is archaeology; authority is live.
        var policy = TestData.Baseline();
        var ctx = TestData.LoanDecision(policy);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        var edited = policy.WithThreshold("bulk_fanout_count", "11");
        var editedVersion = PolicyLoader.DerivePolicyVersion(edited);

        var underStored = Canonicalizer.PayloadHash(
            approval.Payload, approval.ActionId, approval.PolicyVersion,
            policy.Actions[approval.ActionId]);
        var underLive = Canonicalizer.PayloadHash(
            approval.Payload, approval.ActionId, editedVersion,
            policy.Actions[approval.ActionId]);

        underStored.Should().Be(approval.PayloadHash);
        underLive.Should().NotBe(approval.PayloadHash);

        Gate().Authorize(store.Get(approval.Id), edited, editedVersion, ctx,
                TestData.T0.AddMinutes(1))
            .Kind.Should().Be(GateOutcomeKind.Proceed,
                "if the gate recomputed the hash under the LIVE policy version, this would " +
                "wrongly fail as a hash mismatch");
    }
}
