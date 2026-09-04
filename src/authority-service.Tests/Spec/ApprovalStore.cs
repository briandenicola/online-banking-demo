using System.Text.Json;

namespace BankerCopilotTests.Spec;

/// <summary>
/// Epic §5.8.2. `supervisor` implies `banker`. `admin` implies NEITHER — deliberately. If admin
/// implied supervisor, one admin identity could satisfy both signatures on an L2 approval and
/// separation of duties would evaporate while every test still passed.
///
/// Loaded from config (role-hierarchy.json), never hardcoded: the hierarchy is a policy
/// statement, not a constant (I-3).
/// </summary>
public sealed class RoleHierarchy
{
    private readonly Dictionary<string, List<string>> _implies;

    private RoleHierarchy(Dictionary<string, List<string>> implies) => _implies = implies;

    public static RoleHierarchy Load(string fileName = "role-hierarchy.json")
    {
        var path = Path.Combine(PolicyLoader.PolicyDirectory, fileName);
        if (!File.Exists(path))
            throw new FileNotFoundException($"Role hierarchy config missing at {path}.", path);

        var doc = JsonSerializer.Deserialize<Dictionary<string, List<string>>>(File.ReadAllText(path))
                  ?? throw new InvalidOperationException("role-hierarchy.json deserialized to null.");

        return new RoleHierarchy(doc);
    }

    public IReadOnlyCollection<string> DeclaredRoles => _implies.Keys;

    /// <summary>Expand once, at token issuance. Consumers read effectiveRoles; nothing re-expands.</summary>
    public HashSet<string> Expand(string role)
    {
        var result = new HashSet<string>(StringComparer.Ordinal);
        var queue = new Queue<string>([role]);

        while (queue.Count > 0)
        {
            var current = queue.Dequeue();
            if (!result.Add(current)) continue;
            if (_implies.TryGetValue(current, out var implied))
                foreach (var i in implied) queue.Enqueue(i);
        }

        return result;
    }
}

public sealed record Principal(string UserId, string Role, string TokenJti, int Seniority)
{
    public HashSet<string> EffectiveRoles(RoleHierarchy h) => h.Expand(Role);
}

public sealed record SignResult(bool Accepted, string? RejectionCode, string? RejectionReason)
{
    public static SignResult Ok() => new(true, null, null);
    public static SignResult Reject(string code, string reason) => new(false, code, reason);
}

/// <summary>
/// The single writer (engine §5.3.1 layer 2). All approval mutation funnels through here, so the
/// terminal-immutability guard and the execution-authorization requirement are structural rather
/// than advisory.
/// </summary>
public sealed class ApprovalStore
{
    private readonly Dictionary<string, Approval> _docs = new(StringComparer.Ordinal);
    private readonly List<AuditEvent> _audit = [];

    public IReadOnlyList<AuditEvent> AuditLog => _audit;

    public Approval Get(string id) => _docs[id];
    public IEnumerable<Approval> All() => _docs.Values;

    // ---- Write guard --------------------------------------------------------------------

    private Approval Write(Approval a)
    {
        // Belt to the model's braces (§5.1.1a). Status is derived from Terminal, so this can
        // only fire if someone subverts the model — which is exactly when a guard earns its keep.
        if (a.Status == ApprovalStatus.Denied && a.TerminalReason is null)
            throw new MissingTerminalReasonException(a.Id);

        // Terminal documents are immutable. Specifically: there is no denied → proposed edge.
        if (_docs.TryGetValue(a.Id, out var existing) && existing.IsTerminal)
        {
            throw new InvalidOperationException(
                $"Approval '{a.Id}' is already terminal ({existing.Status}/" +
                $"{existing.TerminalReason}). Terminal documents are immutable; re-proposal " +
                "creates a NEW document linked by supersededByApprovalId (§5.1.1).");
        }

        _docs[a.Id] = a;
        return a;
    }

    // ---- Propose ------------------------------------------------------------------------

    public Approval Propose(
        string id, EvaluationContext ctx, PolicyDecision decision,
        Policy policy, string policyVersion, DateTimeOffset now)
    {
        if (!decision.Admissible)
            throw new InvalidOperationException(
                $"Inadmissible action cannot become an approval: {decision.InadmissibleReason}");

        var action = policy.Actions[ctx.ActionId];
        var ttl = TimeSpan.FromMinutes(action.TtlMinutes ?? policy.Defaults.TtlMinutes);

        var approval = new Approval
        {
            Id = id,
            RequesterId = ctx.RequesterId,
            ActionId = ctx.ActionId,
            SessionId = "sess_test",
            Payload = ctx.Payload,
            PayloadHash = Canonicalizer.PayloadHash(ctx.Payload, ctx.ActionId, policyVersion, action),
            HashFields = action.HashFields,
            PolicyVersion = policyVersion,
            BaseRung = decision.BaseRung,
            RequiredRung = decision.RequiredRung,
            RequiredSigners = decision.RequiredSigners,
            DistinctIdentitiesRequired = decision.DistinctIdentitiesRequired,
            SignatureSlots = decision.SignerRequirements
                .Select(r => new SignatureSlot
                {
                    Ordinal = r.Ordinal,
                    MinSeniority = r.MinSeniority,
                    MustDifferFrom = r.MustDifferFrom
                })
                .ToList(),
            FiredEscalators = decision.FiredEscalators,
            CreatedAt = now,
            ExpiresAt = now + ttl
        };

        Write(approval);
        Emit("ApprovalProposed", approval);
        return approval;
    }

    // ---- Sign (epic §5.8.4 steps 1-8) ---------------------------------------------------

    public SignResult Sign(
        string approvalId, Principal signer, RoleHierarchy hierarchy, Policy policy,
        string presentedPayloadHash, string nonce, DateTimeOffset now)
    {
        var a = _docs[approvalId];

        // Lazy read-side expiry (engine §5.4.1): sweeper lag can never permit a late signature.
        if (!a.IsTerminal && now >= a.ExpiresAt)
        {
            ExpireByTtl(approvalId, now);
            return SignResult.Reject("TTL_EXPIRED",
                "This approval expired and was therefore denied. It cannot be signed.");
        }

        if (a.IsTerminal)
            return SignResult.Reject("TERMINAL", $"Approval is already {a.Status}.");

        // Step 3. A replayed signature is a no-op, not a second signature. The same human with
        // two sessions or two tokens counts once (§5.4).
        if (a.SignatureSlots.Any(s => string.Equals(s.SignedBy, signer.UserId, StringComparison.Ordinal)))
        {
            return SignResult.Reject("DUPLICATE_SIGNER",
                "This identity has already signed. The same human with two sessions or two " +
                "tokens counts once (§5.4).");
        }

        var slot = a.SignatureSlots.FirstOrDefault(s => !s.IsFilled);
        if (slot is null)
            return SignResult.Reject("SLOTS_FULL", "All signature slots are filled.");

        var effective = signer.EffectiveRoles(hierarchy);
        var rungSpec = policy.RungSpecFor(a.RequiredRung);

        // Step 4. Role eligibility, read from the RUNG SPEC in config — never a hardcoded list.
        var acceptableRoles = slot.Ordinal == 0
            ? rungSpec.SignerRoles
            : (rungSpec.CosignerRoles.Count > 0 ? rungSpec.CosignerRoles : rungSpec.SignerRoles);

        if (!effective.Overlaps(acceptableRoles))
        {
            return SignResult.Reject("ROLE_INELIGIBLE",
                $"Role '{signer.Role}' (effective: {string.Join(",", effective)}) is not in " +
                $"[{string.Join(",", acceptableRoles)}] for slot {slot.Ordinal} at {a.RequiredRung}.");
        }

        // Step 5. THE CORE CHECK, and it is never conditional on anything: a co-signature may
        // never come from the requester. Not with step-up auth, not with MFA (Q4, §5.4.1).
        if (slot.MustDifferFrom.Contains(signer.UserId, StringComparer.Ordinal))
        {
            return SignResult.Reject("SEPARATION_OF_DUTIES",
                "You proposed this action; a different human must co-sign. Re-authenticating " +
                "does not add a reviewer (§5.4.1).");
        }

        if (signer.Seniority < slot.MinSeniority)
            return SignResult.Reject("SENIORITY", "Insufficient seniority for this slot.");

        // Step 8. The hash the client echoed must match what is stored.
        if (!string.Equals(presentedPayloadHash, a.PayloadHash, StringComparison.Ordinal))
        {
            return SignResult.Reject("HASH_MISMATCH",
                "The figure you are signing is not the figure on record. Re-open the card.");
        }

        var filled = slot with
        {
            SignedBy = signer.UserId,
            SignedAt = now,
            SignedPayloadHash = a.PayloadHash,
            BoundPolicyVersion = a.PolicyVersion,
            SignerTokenJti = signer.TokenJti,
            Nonce = nonce
        };

        var updated = a with
        {
            SignatureSlots = a.SignatureSlots
                .Select(s => s.Ordinal == slot.Ordinal ? filled : s)
                .ToList()
        };

        Write(updated);
        Emit("ApprovalSigned", updated, new Dictionary<string, object?>
        {
            ["signerId"] = signer.UserId,
            ["slotOrdinal"] = slot.Ordinal
        });

        return SignResult.Ok();
    }

    // ---- Deny ---------------------------------------------------------------------------

    public SignResult Deny(
        string approvalId, Principal signer, string? reason,
        DenialReasonValidator validator, DateTimeOffset now)
    {
        var a = _docs[approvalId];

        if (a.IsTerminal)
            return SignResult.Reject("TERMINAL", $"Approval is already {a.Status}.");

        var validation = validator.Validate(reason);
        if (!validation.Valid)
            return SignResult.Reject(validation.FailedRule!, validation.Message!);

        var denied = a.ToDenied(new TerminalTransition(Spec.TerminalReason.HumanDenied, now)
        {
            Detail = reason
        });

        Write(denied);
        Emit("ApprovalDenied", denied, new Dictionary<string, object?>
        {
            ["terminalReason"] = TerminalReasonNames.HumanDenied,
            ["deniedBy"] = signer.UserId,
            ["reasonText"] = reason
        });

        return SignResult.Ok();
    }

    // ---- TTL expiry ---------------------------------------------------------------------

    /// <summary>
    /// Engine §5.4. Writes `denied` + TTL_EXPIRED. It writes a different VALUE than the old
    /// `expired` state, not a different OUTCOME. Expiry has always meant denied.
    /// </summary>
    public Approval ExpireByTtl(string approvalId, DateTimeOffset now)
    {
        var a = _docs[approvalId];
        if (a.IsTerminal) return a;

        var expired = a.ToDenied(new TerminalTransition(Spec.TerminalReason.TtlExpired, now));

        Write(expired);
        Emit("ApprovalExpired", expired, new Dictionary<string, object?>
        {
            ["terminalReason"] = TerminalReasonNames.TtlExpired
        });

        return expired;
    }

    /// <summary>The housekeeper. NOT a security control — lazy read-side expiry is (§5.4.1).</summary>
    public int Sweep(DateTimeOffset now)
    {
        var due = _docs.Values
            .Where(d => d.Status is ApprovalStatus.Pending or ApprovalStatus.Proposed
                        && now >= d.ExpiresAt)
            .Select(d => d.Id)
            .ToList();

        foreach (var id in due) ExpireByTtl(id, now);
        return due.Count;
    }

    // ---- Policy void --------------------------------------------------------------------

    /// <summary>
    /// Engine §3.6 VOID path. The original goes terminal and immutable; a NEW approval carries
    /// the new rung. The discarded signature is recorded in full — this is the only event in the
    /// system where a machine throws away a human's signature (§5.7).
    /// </summary>
    public (Approval Voided, Approval Replacement) VoidByPolicyChange(
        string approvalId, GateOutcome outcome, EvaluationContext ctx,
        PolicyDecision newDecision, Policy newPolicy, string newPolicyVersion,
        string replacementId, DateTimeOffset now)
    {
        var a = _docs[approvalId];

        var discarded = a.SignatureSlots
            .Where(s => s.IsFilled)
            .Select(s => new DiscardedSignature(
                s.SignedBy!, s.Ordinal, s.SignedAt!.Value, a.RequiredRung, s.BoundPolicyVersion!))
            .ToList();

        var replacement = Propose(replacementId, ctx, newDecision, newPolicy, newPolicyVersion, now);

        var voided = a.ToDenied(
            new TerminalTransition(Spec.TerminalReason.PolicyRungEscalated, now)
            {
                SupersededByApprovalId = replacement.Id,
                DiscardedSignatures = discarded
            });

        Write(voided);
        Emit("ApprovalVoidedByPolicyChange", voided, new Dictionary<string, object?>
        {
            ["terminalReason"] = TerminalReasonNames.PolicyRungEscalated,
            ["signedRung"] = a.RequiredRung.ToString(),
            ["newRung"] = (outcome.NewRung ?? newDecision.RequiredRung).ToString(),
            ["signedUnderPolicyVersion"] = a.PolicyVersion,
            ["evaluatedUnderPolicyVersion"] = newPolicyVersion,
            ["supersededByApprovalId"] = replacement.Id,
            ["discardedSignatures"] = discarded,
            ["newEscalators"] = newDecision.FiredEscalators
        });

        return (voided, replacement);
    }

    /// <summary>Engine §6.4. Agent re-planned; payload changed, so the hash changed.</summary>
    public (Approval Superseded, Approval Replacement) SupersedeByReplan(
        string approvalId, EvaluationContext newCtx, PolicyDecision newDecision,
        Policy policy, string policyVersion, string replacementId, DateTimeOffset now)
    {
        var a = _docs[approvalId];
        var replacement = Propose(replacementId, newCtx, newDecision, policy, policyVersion, now);

        var superseded = a.ToDenied(
            new TerminalTransition(Spec.TerminalReason.PayloadSuperseded, now)
            {
                SupersededByApprovalId = replacement.Id
            });

        Write(superseded);
        Emit("ApprovalDenied", superseded, new Dictionary<string, object?>
        {
            ["terminalReason"] = TerminalReasonNames.PayloadSuperseded,
            ["supersededByApprovalId"] = replacement.Id
        });

        return (superseded, replacement);
    }

    // ---- Execute ------------------------------------------------------------------------

    /// <summary>
    /// The ONLY method in the system that can produce <see cref="ApprovalStatus.Executed"/>, and
    /// it cannot be called without an <see cref="ExecutionAuthorization"/> — which only the
    /// re-evaluation gate can mint. That is the absence-of-path proof.
    /// </summary>
    public Approval Execute(ExecutionAuthorization auth, int downstreamStatus)
    {
        ArgumentNullException.ThrowIfNull(auth);

        var a = _docs[auth.Approval.Id];

        if (a.PayloadHash != auth.Approval.PayloadHash)
            throw new InvalidOperationException(
                "The stored approval changed after authorization. Re-enter the gate.");

        if (a.IsTerminal)
            throw new InvalidOperationException(
                $"Approval '{a.Id}' is terminal ({a.Status}/{a.TerminalReason}) and cannot execute.");

        var succeeded = downstreamStatus is >= 200 and < 300;

        // §8.8: a FAILED execution does NOT move status. It stays `signed`, because the
        // signatures remain valid and a retry needs no new human — and the retry re-enters the
        // gate, so a retry after a policy tightening is voided exactly like a first attempt.
        var updated = a with
        {
            ExecutionState = succeeded ? ExecutionState.Succeeded : ExecutionState.Failed,
            DownstreamStatus = downstreamStatus,
            SignedUnderPolicyVersion = auth.SignedUnderPolicyVersion,
            EvaluatedUnderPolicyVersion = auth.EvaluatedUnderPolicyVersion
        };

        Write(updated);
        Emit(succeeded ? "ApprovalExecuted" : "ApprovalExecutionFailed", updated);
        return updated;
    }

    // ---- Audit --------------------------------------------------------------------------

    private void Emit(string eventType, Approval a, IDictionary<string, object?>? extra = null)
    {
        var data = new Dictionary<string, object?>
        {
            ["approvalId"] = a.Id,
            ["actionId"] = a.ActionId,
            ["requesterId"] = a.RequesterId,
            // §5.3.1: COPIED from approval.policyVersion. Never re-read from the live policy.
            ["policyVersion"] = a.PolicyVersion,
            ["requiredRung"] = a.RequiredRung.ToString(),
            ["baseRung"] = a.BaseRung.ToString(),
            ["status"] = a.Status.ToString().ToLowerInvariant()
        };

        if (extra is not null)
            foreach (var kv in extra) data[kv.Key] = kv.Value;

        _audit.Add(new AuditEvent(eventType, data));
    }
}

public sealed record AuditEvent(string EventType, IReadOnlyDictionary<string, object?> Data)
{
    public string Type => EventType;

    /// <summary>
    /// Read back out of the payload rather than stored alongside it, so a test cannot pass by
    /// comparing a convenience property to itself while the emitted event carries something else.
    /// </summary>
    public string? PolicyVersion => Data.TryGetValue("policyVersion", out var v) ? v as string : null;
}
