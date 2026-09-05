using AuthorityService.Models;
using AuthorityService.Policy;
using AuthorityService.Repositories;
using AuthorityService.Services;
using FluentAssertions;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace AuthorityService.UnitTests;

/// <summary>
/// The crown-jewel invariant of the epic — "agents never approve; every state-changing action
/// carries a human signature" — has its last line of defence at EXECUTE time, not sign time.
/// <c>ApprovalsController</c> exposes <c>POST /{id}/execute</c> as its own endpoint, so the real
/// attack is: propose an L2 action, sign it once from a single identity, then call execute
/// directly. Two server-side re-checks in <see cref="ApprovalService.ExecuteAsync"/> refuse it:
///
///   * quorum      — <c>SignaturesCollected &lt; RequiredSigners</c> ⇒ <c>insufficient_signatures</c>
///   * separation  — a slot signed by an identity in its <c>mustDifferFrom</c> ⇒ <c>separation_of_duties</c>
///
/// The coordinator found that BOTH could be deleted with all 350 tests still green: they were
/// correct but unpinned, dead code by every existing test's reckoning. These tests pin them by
/// driving the <c>/execute</c> path directly with states the sign-time front door can never
/// produce — a signed approval carrying too few signatures, and one whose second slot is validly
/// signed by the very identity it was required to differ from.
///
/// Faithfulness matters here. The separation case does NOT forge a bad signature (that would be
/// caught by signature verification, a DIFFERENT guard, and would prove nothing about line 532).
/// It mints a genuinely VALID signature for the offending identity, exactly as an attacker with
/// their own session would, so that ONLY the separation-of-duties check stands between it and the
/// executor. Each test asserts on the downstream side effect (the broker was never called), not
/// merely the status code, so a future refactor that returns 409 AFTER executing still fails.
/// </summary>
public class ExecuteReVerificationTests
{
    /// <summary>
    /// Serves exactly one hand-mutated approval to the execute path and records whether execution
    /// was ever claimed. Only the members <see cref="ApprovalService.ExecuteAsync"/> touches are
    /// implemented; the rest throw, so an unexpected write shows up rather than passing silently.
    /// </summary>
    private sealed class SingleApprovalRepository(Approval approval) : IApprovalRepository
    {
        public bool BeginExecutionCalled { get; private set; }

        public Task<Approval?> FindAsync(string id, CancellationToken ct = default) =>
            Task.FromResult<Approval?>(string.Equals(id, approval.Id, StringComparison.Ordinal) ? approval : null);

        public Task<Approval> BeginExecutionAsync(Approval a, CancellationToken ct = default)
        {
            BeginExecutionCalled = true;
            a.Execution.State = ExecutionState.InFlight;
            return Task.FromResult(a);
        }

        public Task<Approval> CompleteExecutionAsync(Approval a, int downstreamStatus, string? downstreamRef, string evaluatedUnderPolicyVersion, CancellationToken ct = default)
        {
            a.Execution.State = ExecutionState.Succeeded;
            a.Status = ApprovalStatus.Executed;
            return Task.FromResult(a);
        }

        public Task<Approval> FailExecutionAsync(Approval a, string error, int? downstreamStatus, CancellationToken ct = default)
        {
            a.Execution.State = ExecutionState.Failed;
            return Task.FromResult(a);
        }

        public Task<Approval> CreateAsync(Approval a, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval?> GetAsync(string id, string requesterId, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<IReadOnlyList<Approval>> QueryAsync(ApprovalQuery query, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<IReadOnlyList<Approval>> FindExpiredAsync(long nowEpochSeconds, int batchSize, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<IReadOnlyList<Approval>> FindNonTerminalAsync(int batchSize, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval> MarkPendingAsync(Approval a, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval> RecordSignatureAsync(Approval a, int slotOrdinal, SignatureSlot filled, bool quorumReached, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval> TransitionTerminalAsync(Approval a, TerminalReason reason, string? detail = null, string? supersededByApprovalId = null, CancellationToken ct = default) => throw new NotSupportedException();
    }

    private static (ApprovalService Service, SingleApprovalRepository Repo, FakeActionBroker Broker) ExecuteService(Approval signed)
    {
        var configuration = TestHarness.Configuration();
        var repo = new SingleApprovalRepository(signed);
        var broker = new FakeActionBroker();

        var service = new ApprovalService(
            repo,
            new PolicyProvider(TestHarness.LoadPolicy()),
            new PolicyEvaluator(),
            new HmacSignatureService(configuration),
            new DenialReasonValidator(configuration),
            new NullAuditPublisher(),
            broker,
            new NullNotificationSink(),
            NullLogger<ApprovalService>.Instance);

        return (service, repo, broker);
    }

    [Fact]
    public async Task Execute_refuses_a_signed_approval_carrying_fewer_signatures_than_required()
    {
        var (h, signed) = await BuildSignedL2();

        // A signed L2 document with one slot emptied: SignaturesCollected drops to 1 while
        // RequiredSigners stays 2 and Status stays `signed`. The front door can never mint this —
        // that is exactly why only the execute-time re-check stands here.
        var slot = signed.SignatureSlots.Single(s => s.Ordinal == 1);
        slot.SignedBy = null;
        slot.SignedByUsername = null;
        slot.Signature = null;
        slot.SignedAt = null;
        slot.SignerTokenJti = null;
        slot.Nonce = null;

        signed.SignaturesCollected.Should().Be(1, "the fixture must actually be under quorum");
        signed.Status.Should().Be(ApprovalStatus.Signed);

        var (service, repo, broker) = ExecuteService(signed);

        var act = () => service.ExecuteAsync(signed.Id, TestHarness.Banker(), "token");

        (await act.Should().ThrowAsync<AuthorityException>()).Which.Code.Should().Be("insufficient_signatures");
        broker.Calls.Should().BeEmpty("an under-quorum approval must never reach the executor");
        repo.BeginExecutionCalled.Should().BeFalse("execution must not be claimed for an under-quorum approval");
    }

    [Fact]
    public async Task Execute_refuses_when_a_slot_was_signed_by_an_identity_it_must_differ_from()
    {
        var (h, signed) = await BuildSignedL2();

        var bankerId = TestHarness.Banker().UserId; // the proposer; slot 1's mustDifferFrom names exactly this
        var slot = signed.SignatureSlots.Single(s => s.Ordinal == 1);
        slot.MustDifferFrom.Should().Contain(bankerId, "the co-signer slot must exclude the proposer");

        // The attack in full: the SECOND slot is signed by the SAME identity as the first, with a
        // genuinely valid signature (not a forgery — signature verification is a different guard).
        // Only the separation-of-duties re-check can refuse this.
        var sig = new HmacSignatureService(TestHarness.Configuration());
        slot.SignedBy = bankerId;
        slot.SignedByUsername = bankerId;
        slot.Signature = sig.Sign(new SigningInput(
            signed.Id, signed.ActionId, signed.PolicyVersion, signed.PayloadHash,
            slot.SignedBy!, slot.SignerTokenJti ?? string.Empty, slot.Ordinal,
            slot.SignedAt!.Value, slot.Nonce ?? string.Empty));

        signed.SignaturesCollected.Should().Be(2, "the fixture is at quorum; only separation is violated");

        var (service, repo, broker) = ExecuteService(signed);

        var act = () => service.ExecuteAsync(signed.Id, TestHarness.Banker(), "token");

        var thrown = (await act.Should().ThrowAsync<AuthorityException>()).Which;
        thrown.Code.Should().Be("separation_of_duties");
        thrown.Message.Should().Contain("Slot 1", "the failure must point at the specific slot that broke separation of duties");
        broker.Calls.Should().BeEmpty("both slots signed by one identity must never reach the executor");
        repo.BeginExecutionCalled.Should().BeFalse();
    }

    /// <summary>
    /// The positive control. The SAME construction path, left un-mutated, executes cleanly — so
    /// the two refusals above are the checks talking, not an artifact of the hand-built fixture.
    /// A gate that only ever refuses is untestable; this proves the fixture can also pass.
    /// </summary>
    [Fact]
    public async Task A_properly_dual_signed_approval_executes()
    {
        var (h, signed) = await BuildSignedL2();

        var (service, repo, broker) = ExecuteService(signed);

        var result = await service.ExecuteAsync(signed.Id, TestHarness.Banker(), "token");

        result.Voided.Should().BeFalse();
        result.Approval.Status.Should().Be(ApprovalStatus.Executed);
        broker.Calls.Should().HaveCount(1);
        repo.BeginExecutionCalled.Should().BeTrue();
    }

    private static async Task<(TestHarness.Harness Harness, Approval Signed)> BuildSignedL2()
    {
        var h = TestHarness.Build();
        var banker = TestHarness.Banker();

        var approval = await h.Service.ProposeAsync(TestHarness.FlagReview("30000.00"), banker, null);
        approval.RequiredRung.Should().Be(Rung.L2, "the test needs a two-slot approval; check the dual-control threshold");
        approval.RequiredSigners.Should().Be(2);

        await h.Service.SignAsync(approval.Id, banker, new Contracts.SignRequest(), "jti-1");
        var signed = await h.Service.SignAsync(approval.Id, TestHarness.Supervisor(), new Contracts.SignRequest(), "jti-2");
        signed.Status.Should().Be(ApprovalStatus.Signed);

        return (h, signed);
    }
}
