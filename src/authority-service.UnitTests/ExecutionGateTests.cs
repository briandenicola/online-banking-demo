using AuthorityService.Models;
using AuthorityService.Policy;
using AuthorityService.Services;
using FluentAssertions;
using Xunit;

namespace AuthorityService.UnitTests;

/// <summary>
/// Epic §5.3.2 — execution-time re-evaluation.
///
/// Brian's rule applies here more than anywhere: test BOTH directions or you have tested
/// neither. A gate that only voids is a gate that will eventually void everything; a gate that
/// only honors is not a gate at all.
/// </summary>
public class ExecutionGateTests
{
    /// <summary>
    /// DIRECTION 1 — the rules TIGHTENED between signing and execution. The signatures were
    /// given under a ruleset that has since been judged insufficient, so they do not carry over.
    /// </summary>
    [Fact]
    public async Task Escalation_voids_the_approval_and_raises_a_replacement()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        // Signed at L1 with the shipped $25,000 dual-control limit.
        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("5000.00"), banker, null);
        approval.RequiredRung.Should().Be(Rung.L1);

        approval = await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");
        approval.Status.Should().Be(ApprovalStatus.Signed);

        var signedPolicyVersion = approval.PolicyVersion;

        // Risk tightens the limit to $1,000. The same payload is now dual-control.
        h.Policies.Swap(TestHarness.LoadPolicy(("POLICY_FLAGGED_TXN_DUAL_CONTROL_AMOUNT", "1000.00")));
        h.Policies.Current.PolicyVersion.Should().NotBe(signedPolicyVersion);

        var result = await h.Service.ExecuteAsync(approval.Id, banker, "token");

        result.Voided.Should().BeTrue();
        h.Broker.Calls.Should().BeEmpty("the downstream call must not happen when the gate voids");

        result.Approval.Status.Should().Be(ApprovalStatus.Denied);
        result.Approval.TerminalReason.Should().Be(TerminalReason.PolicyRungEscalated);
        result.Approval.SupersededByApprovalId.Should().NotBeNull();

        result.Replacement.Should().NotBeNull();
        result.Replacement!.Id.Should().Be(result.Approval.SupersededByApprovalId);
        result.Replacement.RequiredRung.Should().Be(Rung.L2);
        result.Replacement.RequiredSigners.Should().Be(2);
        result.Replacement.Status.Should().Be(ApprovalStatus.Pending);
        result.Replacement.SupersedesApprovalId.Should().Be(approval.Id);
        result.Replacement.SignaturesCollected.Should().Be(0, "signatures do not carry over a rung change");

        var voidEvent = h.Audit.Published
            .Single(p => p.EventType == SharedIdentifiers.Events.ApprovalVoidedByPolicyChange);

        var payload = Newtonsoft.Json.Linq.JObject.FromObject(voidEvent.Data);

        payload["signedPolicyVersion"]!.ToString().Should().Be(signedPolicyVersion);
        payload["currentPolicyVersion"]!.ToString().Should().Be(h.Policies.Current.PolicyVersion);
        payload["signedRung"]!.ToString().Should().Be("L1");
        payload["newRung"]!.ToString().Should().Be("L2");
        payload["discardedSignatures"]!.Should().HaveCount(1,
            "the humans who signed deserve to see that their signature was discarded, and why");
    }

    /// <summary>
    /// DIRECTION 2 — the rules RELAXED between signing and execution. The approval is honored:
    /// two people did in fact agree, and nothing about a loosened rule makes that less true.
    /// </summary>
    [Fact]
    public async Task Relaxation_honors_the_approval_and_never_auto_downgrades_it()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        // Signed at L2, because $5,000 is over the tightened $1,000 limit.
        var tightened = TestHarness.LoadPolicy(("POLICY_FLAGGED_TXN_DUAL_CONTROL_AMOUNT", "1000.00"));
        h.Policies.Swap(tightened);

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("5000.00"), banker, null);
        approval.RequiredRung.Should().Be(Rung.L2);
        approval.RequiredSigners.Should().Be(2);

        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");
        approval = await h.Service.SignAsync(
            approval.Id, TestHarness.Supervisor(), new Contracts.SignRequest(), "jti-2");

        approval.Status.Should().Be(ApprovalStatus.Signed);
        var signedPolicyVersion = approval.PolicyVersion;

        // Risk relaxes the limit back to the shipped default. The same payload is now L1.
        h.Policies.Swap(TestHarness.LoadPolicy());
        h.Policies.Current.PolicyVersion.Should().NotBe(signedPolicyVersion);

        var result = await h.Service.ExecuteAsync(approval.Id, banker, "token");

        result.Voided.Should().BeFalse();
        result.Replacement.Should().BeNull();
        result.Approval.Status.Should().Be(ApprovalStatus.Executed);
        h.Broker.Calls.Should().HaveCount(1);

        // The rung is NOT rewritten downward. The record says what was actually required of
        // the humans at the time they were asked.
        result.Approval.RequiredRung.Should().Be(Rung.L2);
        result.Approval.RequiredSigners.Should().Be(2);
        result.Approval.SignaturesCollected.Should().Be(2);

        // The version the signatures were produced under is the approval's own
        // policy.policyVersion — stored ONCE. `execution.signedUnderPolicyVersion` was a second
        // copy of it in the same document and is gone (Danny, 2026-09-04).
        result.Approval.PolicyVersion.Should().Be(signedPolicyVersion);

        // The live ruleset at execute time is genuinely new information, so it IS recorded —
        // as an audit annotation, never as a branch condition.
        result.Approval.Execution.EvaluatedUnderPolicyVersion
            .Should().Be(h.Policies.Current.PolicyVersion);
    }

    [Fact]
    public async Task An_unchanged_policy_simply_honors_the_approval()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);
        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");

        var result = await h.Service.ExecuteAsync(approval.Id, banker, "token");

        result.Voided.Should().BeFalse();
        result.Approval.Status.Should().Be(ApprovalStatus.Executed);
    }

    [Fact]
    public async Task An_unrelated_policy_edit_does_not_invalidate_an_outstanding_approval()
    {
        // The critical split: the HASH is recomputed under the approval's OWN policyVersion,
        // while the RUNG is re-derived under the live policy. If those were swapped, any policy
        // edit at all would void every outstanding approval.
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);
        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");

        // Change a threshold this action does not consult at all.
        h.Policies.Swap(TestHarness.LoadPolicy(("POLICY_LOAN_DUAL_CONTROL_AMOUNT", "42000.00")));

        var result = await h.Service.ExecuteAsync(approval.Id, banker, "token");

        result.Voided.Should().BeFalse();
        result.Approval.Status.Should().Be(ApprovalStatus.Executed);
    }

    [Fact]
    public async Task An_action_withdrawn_from_the_policy_voids_without_a_replacement()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);
        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");

        // The action is promoted out of the Copilot's reach entirely.
        var yaml = TestHarness.MutatedPolicyYaml(
            """
              transaction.flag.review:
                displayName: Clear or confirm a flagged transaction
                baseRung: L1
            """,
            """
              transaction.flag.review:
                displayName: Clear or confirm a flagged transaction
                baseRung: L3
            """);

        h.Policies.Swap(PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml));

        var result = await h.Service.ExecuteAsync(approval.Id, banker, "token");

        result.Voided.Should().BeTrue();
        result.Replacement.Should().BeNull("there is no rung the Copilot could re-propose at");
        result.Approval.TerminalReason.Should().Be(TerminalReason.PolicyRungEscalated);
        h.Broker.Calls.Should().BeEmpty();
    }

    [Fact]
    public async Task A_voided_approval_is_terminal_and_immutable()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("5000.00"), banker, null);
        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");

        h.Policies.Swap(TestHarness.LoadPolicy(("POLICY_FLAGGED_TXN_DUAL_CONTROL_AMOUNT", "1000.00")));

        await h.Service.ExecuteAsync(approval.Id, banker, "token");

        var act = async () => await h.Service.ExecuteAsync(approval.Id, banker, "token");

        await act.Should().ThrowAsync<AuthorityException>();
    }
}
