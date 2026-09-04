using AuthorityService.Models;
using AuthorityService.Policy;
using AuthorityService.Services;
using FluentAssertions;
using Xunit;

namespace AuthorityService.UnitTests;

public class ApprovalLifecycleTests
{
    private const string Reason =
        "The customer confirmed this charge in branch, so reversing it would be incorrect.";

    [Fact]
    public async Task A_routine_request_runs_propose_sign_execute()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, "corr-1");

        approval.Status.Should().Be(ApprovalStatus.Pending);
        approval.RequiredRung.Should().Be(Rung.L1);
        approval.PayloadHash.Should().StartWith("sha256:");
        approval.PolicyVersion.Should().Be(h.Policies.Current.PolicyVersion);

        approval = await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");
        approval.Status.Should().Be(ApprovalStatus.Signed);

        var result = await h.Service.ExecuteAsync(approval.Id, banker, "token");

        result.Voided.Should().BeFalse();
        result.Approval.Status.Should().Be(ApprovalStatus.Executed);
        result.Approval.Execution.State.Should().Be(ExecutionState.Succeeded);
        h.Broker.Calls.Should().HaveCount(1);
    }

    [Fact]
    public async Task The_agent_can_never_execute_without_a_signature()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);

        var act = async () => await h.Service.ExecuteAsync(approval.Id, banker, "token");

        (await act.Should().ThrowAsync<AuthorityException>()).Which.Code.Should().Be("conflict");
        h.Broker.Calls.Should().BeEmpty();
    }

    [Fact]
    public async Task A_dual_control_request_needs_two_distinct_humans()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();
        var threshold = h.Policies.Current.Threshold("flagged_transaction_dual_control_amount").AsDecimal();

        var approval = await h.Service.ProposeAsync(
            TestHarness.FlagReview((threshold + 100).ToString("F2")), banker, null);

        approval.RequiredRung.Should().Be(Rung.L2);
        approval.RequiredSigners.Should().Be(2);

        approval = await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");
        approval.Status.Should().Be(ApprovalStatus.Pending, "one signature is not a quorum at L2");

        approval = await h.Service.SignAsync(
            approval.Id, TestHarness.Supervisor(), new Contracts.SignRequest(), "jti-2");

        approval.Status.Should().Be(ApprovalStatus.Signed);
        approval.DistinctSignerCount.Should().Be(2);
    }

    [Fact]
    public async Task The_same_human_cannot_sign_twice()
    {
        // Separation of duties means separation of PEOPLE. Enforced server-side; the UI is not
        // the control.
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();
        var threshold = h.Policies.Current.Threshold("flagged_transaction_dual_control_amount").AsDecimal();

        var approval = await h.Service.ProposeAsync(
            TestHarness.FlagReview((threshold + 100).ToString("F2")), banker, null);

        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");

        var act = async () =>
            await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-2");

        (await act.Should().ThrowAsync<AuthorityException>()).Which.Code.Should().Be("cannot_sign");
    }

    [Fact]
    public async Task A_junior_signer_cannot_fill_a_supervisor_slot()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();
        var threshold = h.Policies.Current.Threshold("flagged_transaction_dual_control_amount").AsDecimal();

        var approval = await h.Service.ProposeAsync(
            TestHarness.FlagReview((threshold + 100).ToString("F2")), banker, null);

        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");

        var otherBanker = TestHarness.Banker("banker-2");
        var act = async () =>
            await h.Service.SignAsync(approval.Id, otherBanker, new Contracts.SignRequest(), "jti-3");

        (await act.Should().ThrowAsync<AuthorityException>())
            .Which.Message.Should().Contain("seniority");
    }

    [Fact]
    public async Task A_denial_records_HUMAN_DENIED_and_the_reason()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);

        approval = await h.Service.DenyAsync(
            approval.Id, TestHarness.Supervisor(), new Contracts.DenyRequest { Reason = Reason });

        approval.Status.Should().Be(ApprovalStatus.Denied);
        approval.TerminalReason.Should().Be(TerminalReason.HumanDenied);
        approval.TerminalDetail.Should().Be(Reason);
        approval.Ttl.Should().BePositive("a terminal approval arms the retention tail");
    }

    [Fact]
    public async Task A_denied_approval_cannot_be_signed_or_executed()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);
        await h.Service.DenyAsync(approval.Id, TestHarness.Supervisor(),
            new Contracts.DenyRequest { Reason = Reason });

        var sign = async () =>
            await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");
        var execute = async () => await h.Service.ExecuteAsync(approval.Id, banker, "token");

        await sign.Should().ThrowAsync<AuthorityException>();
        await execute.Should().ThrowAsync<AuthorityException>();
    }

    [Fact]
    public async Task Superseding_denies_the_original_with_PAYLOAD_SUPERSEDED()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var first = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);

        var replan = TestHarness.FlagReview("250.00");
        replan.SupersedesApprovalId = first.Id;

        var second = await h.Service.ProposeAsync(replan, banker, null);

        var reloaded = await h.Repository.FindAsync(first.Id);

        reloaded!.Status.Should().Be(ApprovalStatus.Denied);
        reloaded.TerminalReason.Should().Be(TerminalReason.PayloadSuperseded);
        reloaded.SupersededByApprovalId.Should().Be(second.Id);
        second.SupersedesApprovalId.Should().Be(first.Id);
    }

    [Fact]
    public async Task A_signature_binds_to_the_payload_so_tampering_is_caught()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);
        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");

        // Reach past the repository's write path to simulate a store-level tamper.
        var stored = (await h.Repository.FindAsync(approval.Id))!;
        stored.Payload["amount"] = "999999.00";
        await h.Repository.ForceWriteForTestAsync(stored);

        var act = async () => await h.Service.ExecuteAsync(approval.Id, banker, "token");

        (await act.Should().ThrowAsync<AuthorityException>())
            .Which.Code.Should().Be("payload_hash_mismatch");
        h.Broker.Calls.Should().BeEmpty();
    }

    [Fact]
    public async Task A_failed_execution_stays_signed_and_never_becomes_a_lifecycle_state()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        h.Broker.Result = new BrokerResult(false, 503, null, "transaction-service is down");

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);
        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");

        var act = async () => await h.Service.ExecuteAsync(approval.Id, banker, "token");
        await act.Should().ThrowAsync<AuthorityException>();

        var stored = (await h.Repository.FindAsync(approval.Id))!;

        stored.Status.Should().Be(ApprovalStatus.Signed, "a downstream failure is not a human decision");
        stored.Execution.State.Should().Be(ExecutionState.Failed);
        stored.TerminalReason.Should().BeNull();
    }

    [Fact]
    public async Task A_retry_after_a_failed_execution_needs_no_new_signature()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        h.Broker.Result = new BrokerResult(false, 503, null, "down");

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);
        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");

        await Assert.ThrowsAsync<AuthorityException>(
            async () => await h.Service.ExecuteAsync(approval.Id, banker, "token"));

        h.Broker.Result = new BrokerResult(true, 200, "ref-2", null);

        var result = await h.Service.ExecuteAsync(approval.Id, banker, "token");

        result.Approval.Status.Should().Be(ApprovalStatus.Executed);
        result.Approval.Execution.Attempts.Should().Be(2);
    }

    [Fact]
    public async Task An_expired_approval_is_denied_on_read_and_never_auto_approved()
    {
        var h = TestHarness.Build(("POLICY_TTL_TRANSACTION_FLAG_REVIEW", "1"));
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);

        await Task.Delay(1200);

        var reloaded = await h.Service.GetAsync(approval.Id, banker);

        reloaded.Status.Should().Be(ApprovalStatus.Denied);
        reloaded.TerminalReason.Should().Be(TerminalReason.TtlExpired);
    }

    [Fact]
    public async Task The_sweeper_denies_expired_approvals_with_TTL_EXPIRED()
    {
        var h = TestHarness.Build(("POLICY_TTL_TRANSACTION_FLAG_REVIEW", "1"));
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);

        await Task.Delay(1200);

        var expired = await h.Repository.FindExpiredAsync(
            DateTimeOffset.UtcNow.ToUnixTimeSeconds(), 100);

        expired.Should().ContainSingle(a => a.Id == approval.Id);

        await h.Service.ExpireAsync(expired.Single());

        var reloaded = (await h.Repository.FindAsync(approval.Id))!;

        reloaded.Status.Should().Be(ApprovalStatus.Denied);
        reloaded.TerminalReason.Should().Be(TerminalReason.TtlExpired);

        h.Audit.Published.Select(p => p.EventType)
            .Should().Contain(SharedIdentifiers.Events.ApprovalExpired);
    }

    [Fact]
    public async Task Audit_events_use_the_PascalCase_names_the_event_processor_understands()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null);
        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");
        await h.Service.ExecuteAsync(approval.Id, banker, "token");

        h.Audit.Published.Select(p => p.EventType).Should().ContainInOrder(
            "ApprovalProposed", "ApprovalSigned", "ApprovalExecuted");

        h.Audit.Published.Should().OnlyContain(p => SharedIdentifiers.Events.All.Contains(p.EventType));
    }
}
