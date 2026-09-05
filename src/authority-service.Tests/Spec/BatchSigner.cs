using System.Text.Json;

namespace BankerCopilotTests.Spec;

/// <summary>
/// Batch approval, reduced to the one invariant that matters: I-10 — a batch is L1-only, within
/// one action type. Epic §5 policy file (<c>defaults.batchApproval.maxRung: L1</c>,
/// <c>sameActionTypeOnly: true</c>) and the Phase 3 milestone bullet: "Batch approval within one
/// action type, L1 only."
///
/// The dangerous reading of "L1 only" is "baseRung L1 only". That is NOT the invariant. An action
/// whose baseRung is L1 can ESCALATE to L2 on a threshold — a large amount, an adverse decision,
/// a high-risk customer. The resolved rung is what governs how many humans must sign, so the
/// batch must key on <see cref="Approval.RequiredRung"/> (the resolved rung), never on
/// <see cref="Approval.BaseRung"/>. A batch that admitted an escalated item would collect ONE
/// signature for an action the ladder says needs TWO from two identities — L2 defeated by being
/// swept into a list.
///
/// The guard is fail-closed and ALL-OR-NOTHING: a single L2 item, or a single foreign actionId,
/// refuses the whole batch before any signature is applied. A batch that signed the L1 items and
/// dropped the L2 one would be worse — it would look like it worked.
/// </summary>
public sealed class BatchInvariantViolation : Exception
{
    public BatchInvariantViolation(string message) : base(message) { }
}

public static class BatchSigner
{
    /// <summary>
    /// Sign every approval in <paramref name="approvalIds"/> with ONE human's signature each.
    /// Refuses the whole batch if any item is not L1, or if the items span more than one action
    /// type. Returns the per-item sign results only if the batch was admissible in full.
    /// </summary>
    public static IReadOnlyList<SignResult> SignBatch(
        ApprovalStore store,
        IReadOnlyList<string> approvalIds,
        Principal signer,
        RoleHierarchy hierarchy,
        Policy policy,
        DateTimeOffset now)
    {
        if (approvalIds.Count == 0)
            throw new BatchInvariantViolation("An empty batch signs nothing; it is a no-op, not an approval.");

        var approvals = approvalIds.Select(store.Get).ToList();

        // I-10, part 1: within ONE action type. `sameActionTypeOnly: true` — a batch that spans
        // action types is "Approve All" with extra steps.
        var actionTypes = approvals.Select(a => a.ActionId).Distinct(StringComparer.Ordinal).ToList();
        if (actionTypes.Count != 1)
        {
            throw new BatchInvariantViolation(
                $"A batch spans {actionTypes.Count} action types ({string.Join(", ", actionTypes)}). " +
                "Batch approval is within one action type only (defaults.batchApproval.sameActionTypeOnly).");
        }

        // I-10, part 2: L1 ONLY, and this reads the RESOLVED rung. This is the line the whole
        // file exists to protect: `RequiredRung`, never `BaseRung`.
        var escalated = approvals.Where(a => a.RequiredRung != Rung.L1).ToList();
        if (escalated.Count > 0)
        {
            throw new BatchInvariantViolation(
                $"{escalated.Count} approval(s) resolved above L1 " +
                $"({string.Join(", ", escalated.Select(a => $"{a.Id}:{a.RequiredRung}"))}). " +
                "Batch approval is never available above L1 (invariant I-10). An escalated item " +
                "needs its own dual-control signing, not a place in a list.");
        }

        // Only now, with the whole batch proven L1 and single-action-type, does anything sign.
        return approvals
            .Select(a => store.Sign(a.Id, signer, hierarchy, policy, a.PayloadHash, $"nonce_{a.Id}", now))
            .ToList();
    }

    /// <summary>
    /// The config-level guard, as an executable predicate: a policy's batch defaults are valid
    /// only if maxRung is L1 and sameActionTypeOnly is true. Mirrors the production loader's
    /// refusal so the oracle and the shipping validator make the same statement.
    /// </summary>
    public static void ValidateBatchDefaults(string maxRung, bool sameActionTypeOnly)
    {
        if (maxRung != "L1")
            throw new BatchInvariantViolation(
                "defaults.batchApproval.maxRung must be 'L1' (I-10). Batch signing is never available at L2.");
        if (!sameActionTypeOnly)
            throw new BatchInvariantViolation(
                "defaults.batchApproval.sameActionTypeOnly must be true. A cross-action-type batch is 'Approve All'.");
    }
}
