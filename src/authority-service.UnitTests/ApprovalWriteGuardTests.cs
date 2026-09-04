using AuthorityService.Models;
using AuthorityService.Repositories;
using FluentAssertions;
using Microsoft.Extensions.Configuration;
using Xunit;

namespace AuthorityService.UnitTests;

public class ApprovalWriteGuardTests
{
    private static Approval Valid() => new()
    {
        Id = SharedIdentifiers.ApprovalIdPrefix + "0123456789abcdef01234567",
        RequesterId = "banker-1",
        ActionId = "transaction.flag.review",
        RequiredSigners = 1,
        SignatureSlots = [new SignatureSlot { Ordinal = 0, MinSeniority = 1 }],
        Status = ApprovalStatus.Pending
    };

    [Fact]
    public void A_denied_approval_without_a_terminalReason_cannot_be_written()
    {
        // This is the invariant the whole terminalReason ruling rests on: there is no code path
        // that produces a reason-less denial.
        var approval = Valid();
        approval.Status = ApprovalStatus.Denied;
        approval.TerminalAt = DateTime.UtcNow;
        approval.Ttl = 100;

        var act = () => ApprovalWriteGuard.Assert(approval);

        act.Should().Throw<ApprovalWriteGuardException>().WithMessage("*terminalReason*");
    }

    [Fact]
    public void A_terminalReason_on_a_live_approval_cannot_be_written()
    {
        var approval = Valid();
        approval.TerminalReason = TerminalReason.HumanDenied;

        var act = () => ApprovalWriteGuard.Assert(approval);

        act.Should().Throw<ApprovalWriteGuardException>();
    }

    [Fact]
    public void HUMAN_DENIED_requires_the_recorded_reason_text()
    {
        var approval = Valid();
        approval.Status = ApprovalStatus.Denied;
        approval.TerminalReason = TerminalReason.HumanDenied;
        approval.TerminalAt = DateTime.UtcNow;
        approval.Ttl = 100;

        var act = () => ApprovalWriteGuard.Assert(approval);

        act.Should().Throw<ApprovalWriteGuardException>().WithMessage("*terminalDetail*");
    }

    [Fact]
    public void The_same_identity_cannot_occupy_two_signature_slots()
    {
        var approval = Valid();
        approval.RequiredSigners = 2;
        approval.SignatureSlots =
        [
            new SignatureSlot { Ordinal = 0, SignedBy = "supervisor-1", SignedAt = DateTime.UtcNow },
            new SignatureSlot { Ordinal = 1, SignedBy = "supervisor-1", SignedAt = DateTime.UtcNow }
        ];

        var act = () => ApprovalWriteGuard.Assert(approval);

        act.Should().Throw<ApprovalWriteGuardException>().WithMessage("*one human signing twice*");
    }

    [Fact]
    public void A_live_approval_may_not_carry_a_cosmos_ttl()
    {
        // TTL deletion must never be the expiry mechanism — losing the record is not the same
        // as denying the request.
        var approval = Valid();
        approval.Ttl = 60;

        var act = () => ApprovalWriteGuard.Assert(approval);

        act.Should().Throw<ApprovalWriteGuardException>();
    }

    [Fact]
    public void An_executed_approval_requires_a_succeeded_execution()
    {
        var approval = Valid();
        approval.Status = ApprovalStatus.Executed;
        approval.Ttl = 100;
        approval.TerminalAt = DateTime.UtcNow;
        approval.Execution.State = ExecutionState.Failed;

        var act = () => ApprovalWriteGuard.Assert(approval);

        act.Should().Throw<ApprovalWriteGuardException>();
    }

    [Theory]
    [InlineData(ApprovalStatus.Proposed, ApprovalStatus.Signed)]
    [InlineData(ApprovalStatus.Proposed, ApprovalStatus.Executed)]
    [InlineData(ApprovalStatus.Pending, ApprovalStatus.Executed)]
    [InlineData(ApprovalStatus.Denied, ApprovalStatus.Pending)]
    [InlineData(ApprovalStatus.Denied, ApprovalStatus.Executed)]
    [InlineData(ApprovalStatus.Executed, ApprovalStatus.Denied)]
    public void Illegal_lifecycle_transitions_are_refused(ApprovalStatus from, ApprovalStatus to)
    {
        var act = () => ApprovalStateMachine.AssertTransition(from, to);

        act.Should().Throw<ApprovalWriteGuardException>();
    }

    [Theory]
    [InlineData(ApprovalStatus.Proposed, ApprovalStatus.Pending)]
    [InlineData(ApprovalStatus.Pending, ApprovalStatus.Signed)]
    [InlineData(ApprovalStatus.Pending, ApprovalStatus.Denied)]
    [InlineData(ApprovalStatus.Signed, ApprovalStatus.Executed)]
    [InlineData(ApprovalStatus.Signed, ApprovalStatus.Denied)]
    public void The_declared_lifecycle_transitions_are_permitted(ApprovalStatus from, ApprovalStatus to)
    {
        var act = () => ApprovalStateMachine.AssertTransition(from, to);

        act.Should().NotThrow();
    }

    [Fact]
    public void There_is_no_expired_or_voided_status()
    {
        SharedIdentifiers.Status.All.Should().BeEquivalentTo(
            ["proposed", "pending", "signed", "executed", "denied"]);
    }

    [Fact]
    public void The_terminal_reason_enum_is_exactly_four_values()
    {
        SharedIdentifiers.TerminalReasons.All.Should().BeEquivalentTo(
            ["HUMAN_DENIED", "POLICY_RUNG_ESCALATED", "PAYLOAD_SUPERSEDED", "TTL_EXPIRED"]);

        Enum.GetValues<TerminalReason>().Should().HaveCount(4);
    }

    [Fact]
    public void An_unrecognised_terminalReason_fails_the_read_rather_than_being_repaired()
    {
        var json = """
        {
          "id": "apr_0123456789abcdef01234567",
          "requesterId": "banker-1",
          "status": "denied",
          "terminalReason": "SUPERSEDED_BY_REPLAN"
        }
        """;

        var act = () => Newtonsoft.Json.JsonConvert.DeserializeObject<Approval>(json);

        act.Should().Throw<UnknownTerminalReasonException>()
            .Which.OffendingValue.Should().Be("SUPERSEDED_BY_REPLAN");
    }

    [Fact]
    public async Task The_in_memory_store_refuses_a_write_that_violates_the_guard()
    {
        var configuration = TestHarness.Configuration();
        var repository = new InMemoryApprovalRepository(configuration);

        var approval = Valid();
        approval.Status = ApprovalStatus.Denied;
        approval.TerminalAt = DateTime.UtcNow;
        approval.Ttl = 100;

        var act = async () => await repository.CreateAsync(approval);

        await act.Should().ThrowAsync<ApprovalWriteGuardException>();
    }
}
