using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;

namespace BankerCopilotTests.Engine;

/// <summary>
/// Epic §5.4, §5.4.1 (Q4), §5.8.2, §5.8.4. Every assertion here is against the SERVER-SIDE
/// signature-acceptance path. The UI may hide a disabled button; that is a courtesy, not a
/// control, and nothing in this file touches the UI.
/// </summary>
public sealed class SeparationOfDutiesTests
{
    private static (ApprovalStore Store, Approval Approval, Policy Policy) L2Approval(
        string requesterId = TestData.Banker)
    {
        var policy = TestData.Baseline();
        var amount = decimal.Parse(policy.Thresholds["loan_l1_max"]) + 10_000m;
        var ctx = TestData.LoanDecision(policy, amount, requesterId: requesterId);
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        approval.RequiredRung.Should().Be(Rung.L2);
        approval.RequiredSigners.Should().Be(2);
        approval.DistinctIdentitiesRequired.Should().Be(2);

        return (store, approval, policy);
    }

    [Fact]
    public void The_same_human_cannot_fill_both_L2_slots()
    {
        var (store, approval, policy) = L2Approval();
        var banker = TestData.Principal(TestData.Banker, "banker", 1, "jti_session_1");

        store.Sign(approval.Id, banker, TestData.Hierarchy(), policy,
            approval.PayloadHash, "n1", TestData.T0).Accepted.Should().BeTrue();

        var second = store.Sign(approval.Id, banker, TestData.Hierarchy(), policy,
            approval.PayloadHash, "n2", TestData.T0);

        second.Accepted.Should().BeFalse();
        second.RejectionCode.Should().Be("DUPLICATE_SIGNER");
        store.Get(approval.Id).Status.Should().Be(ApprovalStatus.Pending);
    }

    [Fact]
    public void A_second_session_or_a_second_token_for_the_same_human_still_counts_once()
    {
        // §5.4: "The same human with two sessions or two tokens counts once." This is the
        // concrete shape of the step-up-auth question — a fresh jti is exactly what re-
        // authenticating produces.
        var (store, approval, policy) = L2Approval();

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1, "jti_session_1"),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n1", TestData.T0);

        var stepUp = store.Sign(
            approval.Id,
            TestData.Principal(TestData.Banker, "banker", 1, "jti_session_2_after_mfa"),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n2", TestData.T0);

        stepUp.Accepted.Should().BeFalse(
            "MFA proves WHO is signing. It says nothing about HOW MANY people reviewed. The " +
            "moment step-up auth stands in for a second human, L2 becomes L1 wearing a hat " +
            "(Q4, §5.4.1).");
        stepUp.RejectionCode.Should().Be("DUPLICATE_SIGNER");
        store.Get(approval.Id).QuorumMet.Should().BeFalse();
    }

    [Fact]
    public void The_requester_may_hold_the_first_slot_but_never_a_co_signer_slot()
    {
        // §5.4 constrains the CO-SIGNER — "must not be the approval's requesterId" — and says
        // nothing about slot 0. That asymmetry is deliberate: a banker who requests a reversal
        // and signs it themselves has still put a human signature on it (I-1). What they cannot
        // do is BE the independent second judgement. So this test asserts the real rule rather
        // than the tempting stricter one; asserting the stricter rule would have made the suite
        // disagree with the ratified spec and put pressure on Turk to over-implement.
        var (store, approval, policy) = L2Approval();

        approval.SignatureSlots[0].MustDifferFrom.Should().BeEmpty();
        approval.SignatureSlots[1].MustDifferFrom.Should().Contain(TestData.Banker,
            "slot 1 excludes the requester unconditionally");

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n1", TestData.T0)
            .Accepted.Should().BeTrue();

        // Same human, now escalated to supervisor, tries to take the co-signer slot too.
        var cosign = store.Sign(approval.Id,
            TestData.Principal(TestData.Banker, "supervisor", 2),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n2", TestData.T0);

        cosign.Accepted.Should().BeFalse(
            "a role promotion does not turn one person into two");
        cosign.RejectionCode.Should().BeOneOf("SEPARATION_OF_DUTIES", "DUPLICATE_SIGNER");
        store.Get(approval.Id).QuorumMet.Should().BeFalse();
    }

    [Fact]
    public void An_agent_proposed_action_still_requires_a_human_in_slot_zero()
    {
        // The normal case: the requester is the AGENT, and no agent identity can ever occupy a
        // signature slot. I-1, asserted at the acceptance path rather than by inspection.
        var policy = TestData.Baseline();
        var ctx = TestData.TransferReversal(policy, requesterId: "agent_banker_copilot");
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        var agentSigns = store.Sign(approval.Id,
            TestData.Principal("agent_banker_copilot", "agent", 0),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        agentSigns.Accepted.Should().BeFalse("agents never approve");
        agentSigns.RejectionCode.Should().Be("ROLE_INELIGIBLE");
        store.Get(approval.Id).Status.Should().Be(ApprovalStatus.Pending);
    }

    [Fact]
    public void No_config_value_can_empty_mustDifferFrom()
    {
        // §8.6.1: "There is no config value, no policy rule, and no escalator that can empty
        // mustDifferFrom — the grammar has no verb for it, exactly as it has no verb for
        // lowering a rung." Prove it across the whole escalator power set.
        var policy = TestData.Baseline();
        var amount = decimal.Parse(policy.Thresholds["loan_l1_max"]) + 10_000m;
        var evaluator = new SpecReferenceEvaluator();

        var factSets = new[]
        {
            new Dictionary<string, object?>(),
            new Dictionary<string, object?> { ["context.selfDealing"] = true },
            new Dictionary<string, object?> { ["customer.riskTier"] = "high" },
            new Dictionary<string, object?> { ["agent.confidence"] = 0.1m },
            new Dictionary<string, object?>
            {
                ["context.selfDealing"] = true,
                ["customer.riskTier"] = "pep",
                ["session.anomalyScore"] = 0.99m
            }
        };

        foreach (var facts in factSets)
        {
            var ctx = TestData.LoanDecision(policy, amount, facts: facts);
            var decision = evaluator.Evaluate(ctx, policy);
            if (!decision.Admissible) continue;

            foreach (var slot in decision.SignerRequirements.Where(s => s.Ordinal > 0))
            {
                slot.MustDifferFrom.Should().Contain(ctx.RequesterId,
                    "every co-signer slot must exclude the requester, whatever fired");
            }
        }
    }

    // ---- The admin trap ------------------------------------------------------------------

    [Fact]
    public void Admin_implies_neither_banker_nor_supervisor()
    {
        // §5.8.2, and the second half matters more than the first: "If admin implied supervisor,
        // then a single admin identity could satisfy both signatures on an L2 approval — and
        // separation of duties evaporates WHILE EVERY TEST STILL PASSES."
        var h = TestData.Hierarchy();

        h.Expand("admin").Should().BeEquivalentTo(["admin"],
            "platform authority and banking authority are different axes");
        h.Expand("supervisor").Should().BeEquivalentTo(["supervisor", "banker"],
            "a supervisor doing ordinary case work should not need a second account");
        h.Expand("banker").Should().BeEquivalentTo(["banker"]);
        h.Expand("user").Should().BeEquivalentTo(["user"],
            "a customer has no harness access at all");
    }

    [Fact]
    public void One_admin_identity_cannot_satisfy_both_L2_signatures()
    {
        // The end-to-end form of the trap, and the acceptance criterion verbatim: "an `admin`
        // who is the requester CANNOT co-sign their own L2 approval".
        var (store, approval, policy) = L2Approval(requesterId: TestData.Admin);
        var admin = TestData.Principal(TestData.Admin, "admin", 3);

        var first = store.Sign(approval.Id, admin, TestData.Hierarchy(), policy,
            approval.PayloadHash, "n1", TestData.T0);
        first.Accepted.Should().BeTrue("admin is in L2 signerRoles, so slot 0 is legitimate");

        var second = store.Sign(approval.Id, admin, TestData.Hierarchy(), policy,
            approval.PayloadHash, "n2", TestData.T0);

        second.Accepted.Should().BeFalse();
        store.Get(approval.Id).QuorumMet.Should().BeFalse();
        store.Get(approval.Id).Status.Should().NotBe(ApprovalStatus.Signed);
    }

    [Fact]
    public void An_admin_who_is_not_the_requester_still_cannot_co_sign_without_a_supervisor_grant()
    {
        // The other half of §5.8.2: an admin who genuinely needs to co-sign must hold an
        // EXPLICIT supervisor grant. Being admin is not enough, even when the identity differs.
        var (store, approval, policy) = L2Approval();

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n1", TestData.T0);

        var cosign = store.Sign(approval.Id, TestData.Principal(TestData.Admin, "admin", 3),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n2", TestData.T0);

        cosign.Accepted.Should().BeFalse();
        cosign.RejectionCode.Should().Be("ROLE_INELIGIBLE");
        cosign.RejectionReason.Should().Contain("supervisor");
    }

    [Fact]
    public void Two_distinct_eligible_humans_do_complete_an_L2_approval()
    {
        // The positive control. Without it, every rejection above could be produced by a signing
        // path that is simply broken, and the suite would pass while nothing worked.
        var (store, approval, policy) = L2Approval();

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n1", TestData.T0)
            .Accepted.Should().BeTrue();

        store.Sign(approval.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n2", TestData.T0)
            .Accepted.Should().BeTrue();

        var signed = store.Get(approval.Id);
        signed.Status.Should().Be(ApprovalStatus.Signed);
        signed.DistinctSignerCount.Should().Be(2);
    }

    [Fact]
    public void An_L1_approval_needs_exactly_one_human_and_never_zero()
    {
        var policy = TestData.Baseline();
        var (store, approval, _) = TestData.ProposeL1(policy, TestData.TransferReversal(policy));

        approval.RequiredRung.Should().Be(Rung.L1);
        approval.RequiredSigners.Should().Be(1);
        approval.Status.Should().Be(ApprovalStatus.Pending,
            "a freshly proposed approval is never already signed — I-1, there is no auto-execute tier");
        approval.QuorumMet.Should().BeFalse();
    }
}
