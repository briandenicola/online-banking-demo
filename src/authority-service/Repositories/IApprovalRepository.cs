using AuthorityService.Models;

namespace AuthorityService.Repositories;

public enum ApprovalScope
{
    Mine,
    AwaitingSupervisor,
    Session,
    All
}

public record ApprovalQuery
{
    public ApprovalScope Scope { get; init; } = ApprovalScope.Mine;
    public string? RequesterId { get; init; }
    public string? SessionId { get; init; }
    public ApprovalStatus? Status { get; init; }
    public TerminalReason? TerminalReason { get; init; }
    public string? ActionId { get; init; }

    /// <summary>Excluded from the co-sign queue: a supervisor never sees their own approvals there.</summary>
    public string? ExcludeRequesterId { get; init; }

    /// <summary>
    /// The seniority bar an approval's next unfilled slot must demand to appear in the
    /// <see cref="ApprovalScope.AwaitingSupervisor"/> queue. DERIVED from the policy's
    /// <c>rungs.L2.cosignerRoles</c> via the ratified hierarchy — never a literal. It was a
    /// hardcoded <c>2</c> in both repositories, which is a seniority integer in code and exactly
    /// the magic-number the whole engine forbids; worse, if the co-signer role's seniority ever
    /// moved in <c>role-hierarchy.yaml</c> the queue would silently point at the wrong bar.
    /// <c>ApprovalService.ListAsync</c> fills it from the live policy; a repository that reaches
    /// the co-sign query with this still null <b>throws</b> rather than guessing a default.
    /// </summary>
    public int? AwaitingSeniorityAtLeast { get; init; }

    public int Limit { get; init; } = 25;
}

/// <summary>
/// The single write path for approvals.
///
/// Every mutation is intent-shaped — there is no <c>SaveAsync(approval)</c> and no raw
/// container access anywhere else in the service. That is enforcement layer 2 of design
/// §5.3.1, and it is the one carrying the real weight: nothing can write the document while
/// bypassing the guard.
/// </summary>
public interface IApprovalRepository
{
    Task<Approval> CreateAsync(Approval approval, CancellationToken ct = default);

    /// <summary>Point read within a known partition.</summary>
    Task<Approval?> GetAsync(string id, string requesterId, CancellationToken ct = default);

    /// <summary>
    /// Cross-partition lookup by id — the co-signer's path, since a supervisor does not know
    /// whose partition an approval lives in.
    /// </summary>
    Task<Approval?> FindAsync(string id, CancellationToken ct = default);

    Task<IReadOnlyList<Approval>> QueryAsync(ApprovalQuery query, CancellationToken ct = default);

    /// <summary>The sweep query: pending approvals past <c>expiresAtEpoch</c>.</summary>
    Task<IReadOnlyList<Approval>> FindExpiredAsync(long nowEpochSeconds, int batchSize, CancellationToken ct = default);

    /// <summary>Non-terminal approvals, for the policy-reload blast-radius sweep.</summary>
    Task<IReadOnlyList<Approval>> FindNonTerminalAsync(int batchSize, CancellationToken ct = default);

    Task<Approval> MarkPendingAsync(Approval approval, CancellationToken ct = default);

    Task<Approval> RecordSignatureAsync(
        Approval approval,
        int slotOrdinal,
        SignatureSlot filled,
        bool quorumReached,
        CancellationToken ct = default);

    /// <summary>
    /// The only path to a negative terminal state. <paramref name="reason"/> is non-nullable
    /// precisely so there is no object-initializer route that omits it.
    /// </summary>
    Task<Approval> TransitionTerminalAsync(
        Approval approval,
        TerminalReason reason,
        string? detail = null,
        string? supersededByApprovalId = null,
        CancellationToken ct = default);

    Task<Approval> BeginExecutionAsync(Approval approval, CancellationToken ct = default);

    Task<Approval> CompleteExecutionAsync(
        Approval approval,
        int downstreamStatus,
        string? downstreamRef,
        string evaluatedUnderPolicyVersion,
        CancellationToken ct = default);

    Task<Approval> FailExecutionAsync(Approval approval, string error, int? downstreamStatus, CancellationToken ct = default);
}
