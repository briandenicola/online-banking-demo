using AuthorityService.Models;
using AuthorityService.Policy;
using AuthorityService.Repositories;
using AuthorityService.Services;
using FluentAssertions;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace AuthorityService.UnitTests;

/// <summary>
/// Phase 3 — the co-sign ("AwaitingSupervisor") queue must bar approvals below a seniority that
/// is DERIVED from <c>rungs.L2.cosignerRoles</c> through the ratified role hierarchy, never a
/// literal. Both repositories once compared <c>awaitingSeniority &gt;= 2</c>: a seniority integer
/// in code, and one that would silently point at the wrong bar the day a co-signer role's
/// seniority moved in <c>role-hierarchy.yaml</c>. <see cref="ApprovalService"/> now resolves the
/// bar from the live policy before the query reaches the repository.
///
/// These tests observe the RESOLVED query the service hands the repository, so the assertion is
/// on the derived value itself — not on downstream filtering that could mask a wrong bar. The
/// tamper cases move the policy and prove the bar follows it, rather than sitting on a constant.
/// </summary>
public class SupervisorQueueSeniorityTests
{
    /// <summary>
    /// A repository that does nothing but record the query it was handed. The service resolves
    /// the seniority bar BEFORE calling <see cref="QueryAsync"/>, so capturing the query captures
    /// the derivation. Every other member throws: this fixture is for the list path only, and a
    /// silent stub would let an unexpected call pass unnoticed.
    /// </summary>
    private sealed class RecordingRepository : IApprovalRepository
    {
        public ApprovalQuery? LastQuery { get; private set; }

        public Task<IReadOnlyList<Approval>> QueryAsync(ApprovalQuery query, CancellationToken ct = default)
        {
            LastQuery = query;
            return Task.FromResult<IReadOnlyList<Approval>>([]);
        }

        public Task<Approval> CreateAsync(Approval approval, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval?> GetAsync(string id, string requesterId, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval?> FindAsync(string id, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<IReadOnlyList<Approval>> FindExpiredAsync(long nowEpochSeconds, int batchSize, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<IReadOnlyList<Approval>> FindNonTerminalAsync(int batchSize, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval> MarkPendingAsync(Approval approval, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval> RecordSignatureAsync(Approval approval, int slotOrdinal, SignatureSlot filled, bool quorumReached, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval> TransitionTerminalAsync(Approval approval, TerminalReason reason, string? detail = null, string? supersededByApprovalId = null, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval> BeginExecutionAsync(Approval approval, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval> CompleteExecutionAsync(Approval approval, int downstreamStatus, string? downstreamRef, string evaluatedUnderPolicyVersion, CancellationToken ct = default) => throw new NotSupportedException();
        public Task<Approval> FailExecutionAsync(Approval approval, string error, int? downstreamStatus, CancellationToken ct = default) => throw new NotSupportedException();
    }

    private static (ApprovalService Service, RecordingRepository Repo, ResolvedPolicy Policy) Build(ResolvedPolicy policy)
    {
        var configuration = TestHarness.Configuration();
        var repo = new RecordingRepository();

        var service = new ApprovalService(
            repo,
            new PolicyProvider(policy),
            new PolicyEvaluator(),
            new HmacSignatureService(configuration),
            new DenialReasonValidator(configuration),
            new NullAuditPublisher(),
            new FakeActionBroker(),
            new NullNotificationSink(),
            NullLogger<ApprovalService>.Instance);

        return (service, repo, policy);
    }

    private static ResolvedPolicy ShippedPolicy() =>
        PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromFile(TestHarness.PolicyPath);

    private static ResolvedPolicy MutatedPolicy(string find, string replace) =>
        PolicyLoader.FromConfiguration(TestHarness.Configuration())
            .LoadFromYaml(TestHarness.MutatedPolicyYaml(find, replace));

    [Fact]
    public async Task Co_sign_queue_bar_is_derived_from_L2_cosignerRoles()
    {
        var (service, repo, policy) = Build(ShippedPolicy());

        await service.ListAsync(new ApprovalQuery { Scope = ApprovalScope.AwaitingSupervisor });

        var expected = policy.MinimumSeniorityAmong(policy.Rung(Rung.L2).CosignerRoles);

        repo.LastQuery.Should().NotBeNull();
        repo.LastQuery!.AwaitingSeniorityAtLeast.Should().Be(expected);
        // The shipped ladder: cosignerRoles: [supervisor], supervisor seniority 2.
        repo.LastQuery!.AwaitingSeniorityAtLeast.Should().Be(2);
    }

    [Fact]
    public async Task Bar_follows_the_policy_when_the_cosigner_role_changes()
    {
        // Move the co-signer role to `banker` (seniority 1). A bar hardcoded to 2 would ignore
        // this; a derived bar must drop to 1. This is the tamper that would catch a reverted
        // ResolveAwaitingSeniority.
        var (service, repo, _) = Build(MutatedPolicy(
            "cosignerRoles: [supervisor]",
            "cosignerRoles: [banker]"));

        await service.ListAsync(new ApprovalQuery { Scope = ApprovalScope.AwaitingSupervisor });

        repo.LastQuery!.AwaitingSeniorityAtLeast.Should().Be(1);
    }

    [Fact]
    public async Task An_explicit_bar_is_left_untouched()
    {
        // A caller who supplies the bar has already resolved it; the service must not overwrite
        // it. (The property is init-only, so this is the only way a value survives to the repo.)
        var (service, repo, _) = Build(ShippedPolicy());

        await service.ListAsync(new ApprovalQuery
        {
            Scope = ApprovalScope.AwaitingSupervisor,
            AwaitingSeniorityAtLeast = 7
        });

        repo.LastQuery!.AwaitingSeniorityAtLeast.Should().Be(7);
    }

    [Fact]
    public async Task Non_supervisor_scopes_do_not_acquire_a_bar()
    {
        // The derivation is scoped: only the co-sign queue gets a bar. A "mine" listing that
        // sprouted a seniority filter would silently hide a banker's own approvals.
        var (service, repo, _) = Build(ShippedPolicy());

        await service.ListAsync(new ApprovalQuery { Scope = ApprovalScope.Mine, RequesterId = "banker-1" });

        repo.LastQuery!.AwaitingSeniorityAtLeast.Should().BeNull();
    }

    [Fact]
    public void An_empty_cosigner_set_fails_closed_at_load_rather_than_defaulting()
    {
        // If cosignerRoles is emptied, the bar has no source. The loader refuses it at startup —
        // the earliest, strongest layer — rather than letting a slot resolve to a bar of 0, which
        // every authenticated principal clears and which is dual control evaporating in silence.
        // (MinimumSeniorityAmong is the second line of the same defence, should a policy ever
        // reach the service with an empty set another way.)
        var act = () => MutatedPolicy("cosignerRoles: [supervisor]", "cosignerRoles: []");

        act.Should().Throw<PolicyValidationException>()
            .WithMessage("*cosignerRoles*");
    }
}
