using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;
using SpecPolicy = BankerCopilotTests.Spec.Policy;

namespace BankerCopilotTests.Store;

/// <summary>
/// Phase 3 fresh angle on the PAYLOAD_SUPERSEDED path (§6.4), aimed at the L2 co-signature window.
///
/// The existing <c>A_superseded_approval_records_both_the_reason_and_the_successor_id</c> proves the
/// terminal reason and the successor link, but it supersedes an approval that was NEVER SIGNED — so
/// its claim "a replan starts from zero signatures" is only lightly exercised: there was no
/// signature to lose. The attack that matters in Phase 3 is different: an agent obtains the FIRST
/// human co-signature on an L2 action, then mutates the payload and asks for the second. If any
/// prior signature survived the mutation, the proposer would have smuggled an unsigned change past a
/// real human. These tests fill a real slot first, then prove nothing survives the replan.
/// </summary>
public sealed class SupersedeSignatureVoidTests
{
    private static (ApprovalStore Store, Approval Approval, string Version, SpecPolicy Policy)
        ProposeL2Transfer()
    {
        var policy = TestData.Baseline();
        var ceiling = decimal.Parse(policy.Thresholds["transfer_l2_amount"]);
        var ctx = TestData.TransferReversal(policy, amount: ceiling + 50_000m);
        var store = new ApprovalStore();
        var version = PolicyLoader.DerivePolicyVersion(policy);
        var decision = new SpecReferenceEvaluator().Evaluate(ctx, policy);
        var approval = store.Propose("apr_l2_replan", ctx, decision, policy, version, TestData.T0);
        return (store, approval, version, policy);
    }

    [Fact]
    public void A_first_L2_signature_does_not_survive_a_payload_replan()
    {
        var (store, approval, version, policy) = ProposeL2Transfer();

        // Setup must actually be L2, or the whole scenario is vacuous.
        approval.RequiredRung.Should().Be(Rung.L2,
            "the scenario is about the co-signature window; an L1 approval has no second slot");
        approval.SignatureSlots.Should().HaveCount(2);

        // First human co-signs the ORIGINAL payload — a real, filled slot.
        store.Sign(approval.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
            TestData.Hierarchy(), policy, approval.PayloadHash, "nonce_a", TestData.T0.AddMinutes(1));
        var signedOriginal = store.Get(approval.Id);
        signedOriginal.SignatureSlots.Count(s => s.IsFilled).Should().Be(1,
            "non-vacuity: there must be a real signature for the replan to be able to discard");
        var firstSigner = signedOriginal.SignatureSlots.Single(s => s.IsFilled).SignedBy;

        // Agent replans: the amount changes, so the hash changes.
        var ceiling = decimal.Parse(policy.Thresholds["transfer_l2_amount"]);
        var newCtx = TestData.TransferReversal(policy, amount: ceiling + 60_000m);
        var (superseded, replacement) = store.SupersedeByReplan(
            approval.Id, newCtx, new SpecReferenceEvaluator().Evaluate(newCtx, policy),
            policy, version, "apr_l2_replan_succ", TestData.T0.AddMinutes(2));

        // The mutation is real.
        replacement.PayloadHash.Should().NotBe(superseded.PayloadHash,
            "if the hash did not change, this was not a replan and the test proves nothing");

        // The original is terminal and correctly linked.
        superseded.TerminalReason.Should().Be(TerminalReason.PayloadSuperseded);
        superseded.SupersededByApprovalId.Should().Be(replacement.Id);

        // THE INVARIANT: not one signature crossed the boundary.
        replacement.SignatureSlots.Should().OnlyContain(s => !s.IsFilled,
            "a payload mutation voids every prior signature; the successor re-collects from zero");
        replacement.SignatureSlots.Should().NotContain(s => s.SignedBy == firstSigner,
            "the first co-signer's signature must not be inherited by the replanned approval");
        replacement.QuorumMet.Should().BeFalse();
    }

    [Fact]
    public void The_replanned_L2_approval_still_demands_two_independent_signatures()
    {
        var (store, approval, version, policy) = ProposeL2Transfer();

        store.Sign(approval.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
            TestData.Hierarchy(), policy, approval.PayloadHash, "nonce_a", TestData.T0.AddMinutes(1));

        var ceiling = decimal.Parse(policy.Thresholds["transfer_l2_amount"]);
        var newCtx = TestData.TransferReversal(policy, amount: ceiling + 60_000m);
        var (_, replacement) = store.SupersedeByReplan(
            approval.Id, newCtx, new SpecReferenceEvaluator().Evaluate(newCtx, policy),
            policy, version, "apr_l2_replan_succ2", TestData.T0.AddMinutes(2));

        // A replan must never quietly become an L1 action or a single-slot approval — that would be
        // an auto-downgrade of the co-signature requirement, dressed up as a payload edit.
        replacement.RequiredRung.Should().Be(Rung.L2,
            "the replanned action is still above the L2 amount ceiling; dual control still applies");
        replacement.SignatureSlots.Should().HaveCount(2,
            "the successor must present two empty slots, not inherit a half-signed quorum");
    }
}
