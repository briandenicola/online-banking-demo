using AuthorityService.Models;

namespace AuthorityService.Repositories;

/// <summary>
/// The lifecycle, expressed once: <c>proposed → pending → signed → executed</c>, with
/// <c>denied</c> as the single terminal rejection state (epic §5.1).
///
/// There is no <c>denied → proposed</c> edge. A terminal document is immutable; re-proposal
/// creates a NEW document linked by <c>supersededByApprovalId</c>. An auditor can rely on an
/// immutable terminal record; a mutable one lets a document's history be silently rewritten.
/// </summary>
public static class ApprovalStateMachine
{
    private static readonly Dictionary<ApprovalStatus, ApprovalStatus[]> Allowed = new()
    {
        [ApprovalStatus.Proposed] = [ApprovalStatus.Pending, ApprovalStatus.Denied],
        [ApprovalStatus.Pending] = [ApprovalStatus.Pending, ApprovalStatus.Signed, ApprovalStatus.Denied],
        [ApprovalStatus.Signed] = [ApprovalStatus.Signed, ApprovalStatus.Executed, ApprovalStatus.Denied],
        [ApprovalStatus.Executed] = [],
        [ApprovalStatus.Denied] = []
    };

    public static bool IsTerminal(ApprovalStatus status) =>
        status is ApprovalStatus.Denied or ApprovalStatus.Executed;

    public static void AssertTransition(ApprovalStatus from, ApprovalStatus to)
    {
        if (from == to && !IsTerminal(from)) return;

        if (!Allowed[from].Contains(to))
        {
            throw new ApprovalWriteGuardException(
                $"Illegal lifecycle transition {EnumWire.ToWire(from)} → {EnumWire.ToWire(to)}. " +
                (IsTerminal(from)
                    ? "Terminal approvals are immutable; a replacement approval must be created instead."
                    : "The lifecycle is proposed → pending → signed → executed, with denied as the " +
                      "single terminal rejection state."));
        }
    }
}

public class ApprovalWriteGuardException : Exception
{
    public ApprovalWriteGuardException(string message) : base(message) { }
}

/// <summary>
/// The invariants that must hold on every document leaving this service, checked BEFORE the
/// upsert. Cosmos has no CHECK constraints and will happily store <c>"terminalReason": "banana"</c>,
/// so "enforced at the persistence layer" is not literally achievable — this guard plus the
/// throwing enum converter plus the single-writer repository is what is achievable instead
/// (design §5.3.1).
/// </summary>
public static class ApprovalWriteGuard
{
    public static void Assert(Approval approval)
    {
        if (string.IsNullOrWhiteSpace(approval.Id) ||
            !approval.Id.StartsWith(SharedIdentifiers.ApprovalIdPrefix, StringComparison.Ordinal))
        {
            throw new ApprovalWriteGuardException(
                $"Approval id '{approval.Id}' must carry the '{SharedIdentifiers.ApprovalIdPrefix}' prefix.");
        }

        if (string.IsNullOrWhiteSpace(approval.RequesterId))
        {
            throw new ApprovalWriteGuardException("requesterId is the partition key and is required.");
        }

        if (approval.RequiredSigners < 1)
        {
            throw new ApprovalWriteGuardException(
                "requiredSigners must be at least 1. A human always signs (invariant I-1).");
        }

        if (approval.SignatureSlots.Count != approval.RequiredSigners)
        {
            throw new ApprovalWriteGuardException(
                $"Approval declares {approval.RequiredSigners} required signers but carries " +
                $"{approval.SignatureSlots.Count} slots.");
        }

        if (approval.Status == ApprovalStatus.Denied)
        {
            // (a) terminalReason is MANDATORY on every transition to a negative terminal state.
            // A denied record with no reason must be impossible to write (epic §5.1.1a).
            if (approval.TerminalReason is null)
            {
                throw new ApprovalWriteGuardException(
                    "A denied approval must carry a terminalReason from the closed enum " +
                    $"[{string.Join(", ", SharedIdentifiers.TerminalReasons.All)}]. Refusing the write: " +
                    "a reason-less denial collapses denied back into an undifferentiated bucket.");
            }

            if (approval.TerminalAt is null)
            {
                throw new ApprovalWriteGuardException("A terminal approval must carry terminalAt.");
            }

            if (approval.TerminalReason == Models.TerminalReason.HumanDenied &&
                string.IsNullOrWhiteSpace(approval.TerminalDetail))
            {
                throw new ApprovalWriteGuardException(
                    "HUMAN_DENIED requires the validated free-text denial reason in terminalDetail.");
            }
        }
        else if (approval.TerminalReason is not null)
        {
            throw new ApprovalWriteGuardException(
                $"terminalReason is set on a non-terminal approval (status " +
                $"'{EnumWire.ToWire(approval.Status)}'). It is null unless the approval is denied.");
        }

        if (approval.Status == ApprovalStatus.Executed &&
            approval.Execution.State != ExecutionState.Succeeded)
        {
            throw new ApprovalWriteGuardException(
                "status 'executed' requires execution.state 'succeeded'. A failed execution leaves " +
                "status 'signed' — the signatures remain valid and a retry needs no new human.");
        }

        var signerIds = approval.SignerIds;

        if (signerIds.Count != signerIds.Distinct(StringComparer.Ordinal).Count())
        {
            throw new ApprovalWriteGuardException(
                "The same identity appears in two signature slots. Separation of duties means " +
                "separation of people; one human signing twice is one mind.");
        }

        if (ApprovalStateMachine.IsTerminal(approval.Status) && approval.Ttl is null or <= 0)
        {
            throw new ApprovalWriteGuardException(
                "A terminal approval must carry the retention ttl. Live approvals are immortal; " +
                "terminal ones are purged on the retention tail.");
        }

        if (!ApprovalStateMachine.IsTerminal(approval.Status) && approval.Ttl is not null)
        {
            throw new ApprovalWriteGuardException(
                "A live approval must not carry a ttl. Cosmos TTL deletion must never be the " +
                "expiry mechanism — losing the record is not the same as denying the request.");
        }
    }
}
