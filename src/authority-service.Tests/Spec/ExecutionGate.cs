namespace BankerCopilotTests.Spec;

public enum GateOutcomeKind
{
    Proceed,
    VoidPolicyEscalated,
    RefuseTtlExpired,
    RefuseHashMismatch,
    RefuseQuorum
}

public sealed record GateOutcome(
    GateOutcomeKind Kind,
    string Reason,
    Rung? NewRung = null,
    IReadOnlyList<SignerRequirement>? NewSigners = null,
    IReadOnlyList<FiredEscalator>? NewEscalators = null,
    ExecutionAuthorization? Authorization = null);

/// <summary>
/// The capability token that permits an execution. Its constructor is PRIVATE and the only type
/// that can reach it is the nested <see cref="ReEvaluationGate"/>.
///
/// This is the structural answer to acceptance criterion "no path from `signed` to `executed`
/// bypasses the re-evaluation gate". A test that asserts "the gate was called" only proves the
/// path it walked; it cannot prove the ABSENCE of another path. Here, the executor's signature
/// requires a token that nothing but the gate can manufacture, so a bypass is not a bug that
/// slipped through review — it does not compile.
/// </summary>
public sealed class ExecutionAuthorization
{
    public Approval Approval { get; }
    public Rung RungSigned { get; }
    public Rung RungNow { get; }
    public string SignedUnderPolicyVersion { get; }
    public string EvaluatedUnderPolicyVersion { get; }
    public DateTimeOffset AuthorizedAt { get; }

    private ExecutionAuthorization(
        Approval approval, Rung rungSigned, Rung rungNow,
        string signedUnder, string evaluatedUnder, DateTimeOffset at)
    {
        Approval = approval;
        RungSigned = rungSigned;
        RungNow = rungNow;
        SignedUnderPolicyVersion = signedUnder;
        EvaluatedUnderPolicyVersion = evaluatedUnder;
        AuthorizedAt = at;
    }

    /// <summary>
    /// Engine §3.6 / epic §5.3.2. The ordered gate of §8.8, in order. Nested inside
    /// <see cref="ExecutionAuthorization"/> so that it — and only it — can reach the private
    /// constructor above.
    /// </summary>
    public sealed class ReEvaluationGate(IPolicyEvaluator evaluator)
    {
        public GateOutcome Authorize(
            Approval approval,
            Policy currentPolicy,
            string currentPolicyVersion,
            EvaluationContext rebuiltContext,
            DateTimeOffset now)
        {
            // (1) Expiry is checked FIRST and independently. I-6: expiry is a denial, never a
            //     fall-through to execution. This must precede everything, including quorum,
            //     because a fully-signed-but-expired approval must still not execute.
            if (now >= approval.ExpiresAt)
            {
                return new GateOutcome(
                    GateOutcomeKind.RefuseTtlExpired,
                    $"This approval expired at {approval.ExpiresAt:O} without full signature, " +
                    "and was therefore denied.");
            }

            // (2) Quorum, distinct identities.
            if (!approval.QuorumMet)
            {
                return new GateOutcome(
                    GateOutcomeKind.RefuseQuorum,
                    $"Quorum not met: {approval.SignatureSlots.Count(s => s.IsFilled)} of " +
                    $"{approval.RequiredSigners} signatures, " +
                    $"{approval.DistinctSignerCount} of {approval.DistinctIdentitiesRequired} " +
                    "distinct identities.");
            }

            // (4) Re-evaluate under the CURRENT policy. Same pure function as at propose time.
            var current = evaluator.Evaluate(rebuiltContext, currentPolicy);

            // (c) Hard L3 is absolute, whatever was signed.
            if (!current.Admissible || current.RequiredRung == Rung.L3)
            {
                return new GateOutcome(
                    GateOutcomeKind.VoidPolicyEscalated,
                    "The approval policy changed while this was pending, and this action is no " +
                    "longer permitted through the Copilot at all.",
                    NewRung: Rung.L3,
                    NewEscalators: current.FiredEscalators);
            }

            var rungSigned = approval.RequiredRung;

            // (d) THE RULING. One comparison, same total order as §3.4. Tightened ⇒ void.
            if (current.RequiredRung > rungSigned)
            {
                return new GateOutcome(
                    GateOutcomeKind.VoidPolicyEscalated,
                    $"The approval policy changed while this was pending. This action now " +
                    $"requires {current.RequiredRung}; your signature authorised {rungSigned}.",
                    NewRung: current.RequiredRung,
                    NewSigners: current.SignerRequirements,
                    NewEscalators: current.FiredEscalators);
            }

            // Unchanged or LOOSENED ⇒ honour what was signed. There is deliberately no branch
            // that rewrites requiredRung down, drops a signature, or shrinks the quorum. A
            // loosened policy is simply not an event.

            // (5) Recompute the canonical hash using the policy version STORED ON THE APPROVAL,
            //     never the current one (§6.4). Signature verification is archaeology; authority
            //     is live. They must not share an input.
            //
            //     ⚠️ FINDING F-2 (found by PayloadHashTests, 2026-05). The obvious implementation
            //     hashes `approval.Payload` — the payload already in the store — and compares it
            //     to `approval.PayloadHash`. That is a TAUTOLOGY: it can only ever prove the
            //     record is self-consistent, and it passes forever while checking nothing. The
            //     hash must be recomputed from the payload PRESENTED FOR EXECUTION, which is the
            //     only value an attacker actually controls at this point.
            var action = currentPolicy.Actions[approval.ActionId];
            string recomputed;
            try
            {
                recomputed = Canonicalizer.PayloadHash(
                    rebuiltContext.Payload, approval.ActionId, approval.PolicyVersion, action);
            }
            catch (CanonicalizationException ex)
            {
                return new GateOutcome(GateOutcomeKind.RefuseHashMismatch, ex.Message);
            }

            if (!string.Equals(recomputed, approval.PayloadHash, StringComparison.Ordinal))
            {
                return new GateOutcome(
                    GateOutcomeKind.RefuseHashMismatch,
                    "The payload being executed is not the payload that was signed.");
            }

            // Every signature must have been taken against this same hash.
            foreach (var slot in approval.SignatureSlots.Where(s => s.IsFilled))
            {
                if (!string.Equals(slot.SignedPayloadHash, approval.PayloadHash, StringComparison.Ordinal))
                {
                    return new GateOutcome(
                        GateOutcomeKind.RefuseHashMismatch,
                        $"Signature in slot {slot.Ordinal} was taken against a different payload hash.");
                }
            }

            return new GateOutcome(
                GateOutcomeKind.Proceed,
                "Re-evaluation confirmed the ladder has not tightened.",
                NewRung: current.RequiredRung,
                Authorization: new ExecutionAuthorization(
                    approval, rungSigned, current.RequiredRung,
                    approval.PolicyVersion, currentPolicyVersion, now));
        }
    }
}
