namespace BankerCopilotTests.Spec;

/// <summary>Epic §5.1. Exactly five. There is NO `expired` state and NO `voided` state.</summary>
public enum ApprovalStatus
{
    Proposed,
    Pending,
    Signed,
    Executed,
    Denied
}

/// <summary>Epic §5.1.1(b) / engine §5.3.1. Closed. Exactly four. No free text, no embedded id.</summary>
public enum TerminalReason
{
    HumanDenied,
    PolicyRungEscalated,
    PayloadSuperseded,
    TtlExpired
}

public enum ExecutionState
{
    NotAttempted,
    InFlight,
    Succeeded,
    Failed
}

public static class TerminalReasonNames
{
    public const string HumanDenied = "HUMAN_DENIED";
    public const string PolicyRungEscalated = "POLICY_RUNG_ESCALATED";
    public const string PayloadSuperseded = "PAYLOAD_SUPERSEDED";
    public const string TtlExpired = "TTL_EXPIRED";

    public static readonly string[] All =
        [HumanDenied, PolicyRungEscalated, PayloadSuperseded, TtlExpired];

    public static string Wire(TerminalReason r) => r switch
    {
        TerminalReason.HumanDenied => HumanDenied,
        TerminalReason.PolicyRungEscalated => PolicyRungEscalated,
        TerminalReason.PayloadSuperseded => PayloadSuperseded,
        TerminalReason.TtlExpired => TtlExpired,
        _ => throw new InvalidOperationException(
            $"Unrecognised TerminalReason '{r}'. The enum is closed at four members; adding one " +
            "requires a spec change, not a string literal.")
    };

    /// <summary>Readers fail closed (§5.3.1 layer 4): an unknown reason is denied-and-NOT-executable.</summary>
    public static TerminalReason Parse(string wire) => wire switch
    {
        HumanDenied => TerminalReason.HumanDenied,
        PolicyRungEscalated => TerminalReason.PolicyRungEscalated,
        PayloadSuperseded => TerminalReason.PayloadSuperseded,
        TtlExpired => TerminalReason.TtlExpired,
        _ => throw new UnknownTerminalReasonException(wire)
    };
}

public sealed class UnknownTerminalReasonException(string value)
    : Exception($"Unrecognised terminalReason '{value}'. Treated as denied and NOT executable.")
{
    public string Value { get; } = value;
}

/// <summary>
/// Epic §5.1.1(a): "a `denied` record with no reason must be impossible to write — enforced in
/// the model, not by convention: ... a REQUIRED CONSTRUCTOR PARAMETER (so there is no
/// object-initializer path that omits it)".
///
/// <see cref="Reason"/> is positional with no default, so no object-initializer path can produce
/// one of these without a reason, and <see cref="Approval.Status"/> is DERIVED from the presence
/// of this object. A reasonless `denied` is therefore not "rejected" — it is unrepresentable.
/// </summary>
public sealed record TerminalTransition(TerminalReason Reason, DateTimeOffset At)
{
    /// <summary>Free text for HUMAN_DENIED only; structured detail otherwise (§8.7.1).</summary>
    public string? Detail { get; init; }

    /// <summary>The id lives in its own FIELD, never inside the reason — or the enum is not closed.</summary>
    public string? SupersededByApprovalId { get; init; }

    public IReadOnlyList<DiscardedSignature> DiscardedSignatures { get; init; } = [];
}

public sealed record SignatureSlot
{
    public required int Ordinal { get; init; }
    public required int MinSeniority { get; init; }
    public required IReadOnlyList<string> MustDifferFrom { get; init; }
    public string? SignedBy { get; init; }
    public DateTimeOffset? SignedAt { get; init; }
    public string? SignedPayloadHash { get; init; }
    public string? BoundPolicyVersion { get; init; }
    public string? SignerTokenJti { get; init; }
    public string? Nonce { get; init; }

    public bool IsFilled => SignedBy is not null;
}

public sealed record DiscardedSignature(
    string SignerId,
    int SlotOrdinal,
    DateTimeOffset SignedAt,
    Rung RungSatisfied,
    string BoundPolicyVersion);

/// <summary>The durable approval record (engine §5.3).</summary>
public sealed record Approval
{
    public required string Id { get; init; }
    public required string RequesterId { get; init; }
    public required string ActionId { get; init; }
    public required string SessionId { get; init; }

    public required IReadOnlyDictionary<string, object?> Payload { get; init; }
    public required string PayloadHash { get; init; }
    public required IReadOnlyList<string> HashFields { get; init; }
    public int CanonicalizationVersion { get; init; } = Canonicalizer.CanonicalizationVersion;

    public required string PolicyVersion { get; init; }
    public required Rung BaseRung { get; init; }
    public required Rung RequiredRung { get; init; }
    public required int RequiredSigners { get; init; }
    public required int DistinctIdentitiesRequired { get; init; }
    public required IReadOnlyList<SignatureSlot> SignatureSlots { get; init; }
    public IReadOnlyList<FiredEscalator> FiredEscalators { get; init; } = [];

    public required DateTimeOffset CreatedAt { get; init; }
    public required DateTimeOffset ExpiresAt { get; init; }

    /// <summary>Null while non-terminal. Non-null ⇒ denied, and it always carries a reason.</summary>
    public TerminalTransition? Terminal { get; init; }

    public ExecutionState ExecutionState { get; init; } = ExecutionState.NotAttempted;
    public string? SignedUnderPolicyVersion { get; init; }
    public string? EvaluatedUnderPolicyVersion { get; init; }
    public int? DownstreamStatus { get; init; }

    /// <summary>Set once the harness has surfaced the card; drives proposed → pending.</summary>
    public bool Surfaced { get; init; } = true;

    // ---- Derived state ------------------------------------------------------------------

    /// <summary>
    /// DERIVED, never assigned. This is what makes §5.1.1(a) structural: there is no
    /// <c>Status = Denied</c> setter to reach without supplying a
    /// <see cref="TerminalTransition"/>, and a TerminalTransition cannot exist without a reason.
    ///
    /// It also removes the whole class of "status says denied but the reason field is null"
    /// bugs, because the two cannot disagree — one is computed from the other.
    /// </summary>
    public ApprovalStatus Status =>
        Terminal is not null ? ApprovalStatus.Denied
        : ExecutionState == ExecutionState.Succeeded ? ApprovalStatus.Executed
        : QuorumMet ? ApprovalStatus.Signed
        : Surfaced ? ApprovalStatus.Pending
        : ApprovalStatus.Proposed;

    public TerminalReason? TerminalReason => Terminal?.Reason;
    public DateTimeOffset? TerminalAt => Terminal?.At;
    public string? TerminalDetail => Terminal?.Detail;
    public string? SupersededByApprovalId => Terminal?.SupersededByApprovalId;

    public IReadOnlyList<DiscardedSignature> DiscardedSignatures =>
        Terminal?.DiscardedSignatures ?? [];

    public bool IsTerminal => Status is ApprovalStatus.Denied or ApprovalStatus.Executed;

    public int DistinctSignerCount =>
        SignatureSlots.Where(s => s.SignedBy is not null)
                      .Select(s => s.SignedBy!)
                      .Distinct(StringComparer.Ordinal)
                      .Count();

    public bool QuorumMet =>
        SignatureSlots.Count(s => s.IsFilled) >= RequiredSigners &&
        DistinctSignerCount >= DistinctIdentitiesRequired;

    /// <summary>The ONLY way to reach a negative terminal state, and it demands a reason.</summary>
    public Approval ToDenied(TerminalTransition transition)
    {
        ArgumentNullException.ThrowIfNull(transition);

        if (IsTerminal)
            throw new InvalidOperationException(
                $"Approval '{Id}' is already terminal ({Status}/{TerminalReason}). Terminal " +
                "documents are immutable; re-proposal creates a NEW document (§5.1.1).");

        return this with { Terminal = transition };
    }
}

public sealed class MissingTerminalReasonException(string approvalId)
    : Exception(
        $"Approval '{approvalId}' cannot be written as denied without a terminalReason. " +
        "The reason is mandatory on every transition to a negative terminal state (§5.1.1a) — " +
        "not nullable, not defaulted.");

/// <summary>
/// Epic §5.1.1(c). The four terminal reasons are NOT interchangeable for measurement, and the
/// distinction is the whole reason the reason field exists.
///
/// Only <c>HUMAN_DENIED</c> is a judgement — a person looked at the proposal and said no. The
/// other three are mechanical: the clock ran out, the ladder moved, or the plan was replaced.
/// Counting them together makes a policy edit look like a fleet of misbehaving agents, and a
/// busy Friday afternoon look like a spike in refusals. An operator who learns the denial-rate
/// chart lies stops reading it, and that is a worse outcome than not having the chart.
/// </summary>
public static class DenialMetrics
{
    public static bool CountsTowardDenialRate(this TerminalReason reason) =>
        reason == TerminalReason.HumanDenied;

    /// <summary>The grouping key any denial-rate dashboard must slice on before aggregating.</summary>
    public static string MetricBucket(this TerminalReason reason) => reason switch
    {
        TerminalReason.HumanDenied => "human_judgement",
        TerminalReason.PolicyRungEscalated => "policy_change",
        TerminalReason.PayloadSuperseded => "replan",
        TerminalReason.TtlExpired => "queue_latency",
        _ => throw new UnknownTerminalReasonException(reason.ToString())
    };
}
