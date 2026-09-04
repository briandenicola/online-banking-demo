using AuthorityService.Models;

namespace AuthorityService.Repositories;

/// <summary>
/// Holds every approval mutation in ONE place, shared by every backend.
///
/// Subclasses supply only dumb persistence primitives (<see cref="PersistNewAsync"/> /
/// <see cref="PersistReplaceAsync"/>); they never decide what a legal document looks like. That
/// keeps the write guard and the state machine on a single code path regardless of whether the
/// store is Cosmos or the in-memory dev backend.
/// </summary>
public abstract class ApprovalRepositoryBase : IApprovalRepository
{
    private readonly int _retentionSeconds;

    protected ApprovalRepositoryBase(int retentionSeconds)
    {
        _retentionSeconds = retentionSeconds;
    }

    protected abstract Task<Approval> PersistNewAsync(Approval approval, CancellationToken ct);
    protected abstract Task<Approval> PersistReplaceAsync(Approval approval, CancellationToken ct);

    public abstract Task<Approval?> GetAsync(string id, string requesterId, CancellationToken ct = default);
    public abstract Task<Approval?> FindAsync(string id, CancellationToken ct = default);
    public abstract Task<IReadOnlyList<Approval>> QueryAsync(ApprovalQuery query, CancellationToken ct = default);
    public abstract Task<IReadOnlyList<Approval>> FindExpiredAsync(long nowEpochSeconds, int batchSize, CancellationToken ct = default);
    public abstract Task<IReadOnlyList<Approval>> FindNonTerminalAsync(int batchSize, CancellationToken ct = default);

    public Task<Approval> CreateAsync(Approval approval, CancellationToken ct = default)
    {
        ApprovalWriteGuard.Assert(approval);
        return PersistNewAsync(approval, ct);
    }

    public Task<Approval> MarkPendingAsync(Approval approval, CancellationToken ct = default)
    {
        ApprovalStateMachine.AssertTransition(approval.Status, ApprovalStatus.Pending);

        approval.Status = ApprovalStatus.Pending;

        return WriteAsync(approval, ct);
    }

    public Task<Approval> RecordSignatureAsync(
        Approval approval,
        int slotOrdinal,
        SignatureSlot filled,
        bool quorumReached,
        CancellationToken ct = default)
    {
        var target = ApprovalStatus.Pending;

        if (quorumReached) target = ApprovalStatus.Signed;

        ApprovalStateMachine.AssertTransition(approval.Status, target);

        var slot = approval.SignatureSlots.SingleOrDefault(s => s.Ordinal == slotOrdinal)
                   ?? throw new ApprovalWriteGuardException($"Signature slot {slotOrdinal} does not exist.");

        if (slot.SignedBy is not null)
        {
            throw new ApprovalWriteGuardException($"Signature slot {slotOrdinal} is already filled.");
        }

        slot.SignedBy = filled.SignedBy;
        slot.SignedByUsername = filled.SignedByUsername;
        slot.SignedAt = filled.SignedAt;
        slot.Signature = filled.Signature;
        slot.SignerTokenJti = filled.SignerTokenJti;
        slot.Nonce = filled.Nonce;
        slot.Comment = filled.Comment;

        approval.Status = target;
        RefreshPendingSlot(approval);

        return WriteAsync(approval, ct);
    }

    public Task<Approval> TransitionTerminalAsync(
        Approval approval,
        TerminalReason reason,
        string? detail = null,
        string? supersededByApprovalId = null,
        CancellationToken ct = default)
    {
        ApprovalStateMachine.AssertTransition(approval.Status, ApprovalStatus.Denied);

        approval.Status = ApprovalStatus.Denied;
        approval.TerminalReason = reason;
        approval.TerminalDetail = detail;
        approval.TerminalAt = DateTime.UtcNow;
        approval.SupersededByApprovalId = supersededByApprovalId ?? approval.SupersededByApprovalId;
        approval.PendingSlotOrdinal = null;
        approval.AwaitingSeniority = null;
        approval.Ttl = _retentionSeconds;

        return WriteAsync(approval, ct);
    }

    public Task<Approval> BeginExecutionAsync(Approval approval, CancellationToken ct = default)
    {
        if (approval.Status != ApprovalStatus.Signed)
        {
            throw new ApprovalWriteGuardException(
                $"Only a signed approval may begin execution; this one is " +
                $"'{EnumWire.ToWire(approval.Status)}'.");
        }

        approval.Execution.State = ExecutionState.InFlight;
        approval.Execution.Attempts += 1;
        approval.Execution.StartedAtEpoch = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        approval.Execution.IdempotencyKey ??= approval.Id;

        return WriteAsync(approval, ct);
    }

    public Task<Approval> CompleteExecutionAsync(
        Approval approval,
        int downstreamStatus,
        string? downstreamRef,
        string evaluatedUnderPolicyVersion,
        CancellationToken ct = default)
    {
        ApprovalStateMachine.AssertTransition(approval.Status, ApprovalStatus.Executed);

        approval.Status = ApprovalStatus.Executed;
        approval.Execution.State = ExecutionState.Succeeded;
        approval.Execution.DownstreamStatus = downstreamStatus;
        approval.Execution.DownstreamRef = downstreamRef;
        approval.Execution.LastError = null;
        approval.Execution.EvaluatedUnderPolicyVersion = evaluatedUnderPolicyVersion;
        approval.TerminalAt = DateTime.UtcNow;
        approval.Ttl = _retentionSeconds;

        return WriteAsync(approval, ct);
    }

    public Task<Approval> FailExecutionAsync(
        Approval approval,
        string error,
        int? downstreamStatus,
        CancellationToken ct = default)
    {
        // A failed execution does NOT move status. It stays `signed`, because the signatures
        // remain valid and the action remains legitimately executable — a retry needs no new
        // human, and the retry re-enters the §5.3.2 gate anyway.
        approval.Execution.State = ExecutionState.Failed;
        approval.Execution.LastError = error;
        approval.Execution.DownstreamStatus = downstreamStatus;

        return WriteAsync(approval, ct);
    }

    private Task<Approval> WriteAsync(Approval approval, CancellationToken ct)
    {
        ApprovalWriteGuard.Assert(approval);
        return PersistReplaceAsync(approval, ct);
    }

    protected static void RefreshPendingSlot(Approval approval)
    {
        var next = approval.SignatureSlots
            .Where(s => s.SignedBy is null)
            .OrderBy(s => s.Ordinal)
            .FirstOrDefault();

        approval.PendingSlotOrdinal = next?.Ordinal;
        approval.AwaitingSeniority = next?.MinSeniority;
    }
}
