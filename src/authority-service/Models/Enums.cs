using Newtonsoft.Json;

namespace AuthorityService.Models;

/// <summary>
/// The approval lifecycle: <c>proposed → pending → signed → executed</c>, with <c>denied</c>
/// as the single terminal rejection state (epic §5.1.1).
///
/// There is NO <c>expired</c>, NO <c>voided</c> and NO <c>execution_failed</c> member, and
/// adding one is a spec change, not an edit here.
/// </summary>
public enum ApprovalStatus
{
    Proposed,
    Pending,
    Signed,
    Executed,
    Denied
}

/// <summary>
/// The closed four-value terminal reason enum (epic §5.1.1b).
///
/// Mandatory whenever <see cref="ApprovalStatus.Denied"/>; null otherwise. All four resolve to
/// the same state — that is the point of the collapse. Consumers MUST group by this value and
/// must never aggregate across it (epic §5.1.1c).
/// </summary>
public enum TerminalReason
{
    /// <summary>An eligible human signer refused. The only reason carrying a human judgement about the action.</summary>
    HumanDenied,

    /// <summary>Execution-gate re-evaluation returned a higher rung. A machine discarded a human's signature.</summary>
    PolicyRungEscalated,

    /// <summary>The agent re-planned; a replacement approval carries the changed payload.</summary>
    PayloadSuperseded,

    /// <summary>The signature window closed unsigned. A denial by I-6 — never an approval.</summary>
    TtlExpired
}

/// <summary>
/// Execution state, orthogonal to <see cref="ApprovalStatus"/>. A failed execution leaves
/// <c>status = signed</c> because the signatures remain valid (epic §5.1).
/// </summary>
public enum ExecutionState
{
    NotAttempted,
    InFlight,
    Succeeded,
    Failed
}

/// <summary>
/// Thrown when a persisted document carries a <c>terminalReason</c> outside the closed enum.
/// Readers fail closed on this: the approval is treated as denied and NOT executable, and the
/// event alerts. The failure mode of an unknown value is always "refuses to act".
/// </summary>
public class UnknownTerminalReasonException : Exception
{
    public UnknownTerminalReasonException(string offendingValue)
        : base($"terminalReason '{offendingValue}' is outside the closed enum " +
               $"[{string.Join(", ", SharedIdentifiers.TerminalReasons.All)}]. " +
               "Refusing to act on this approval.")
    {
        OffendingValue = offendingValue;
    }

    public string OffendingValue { get; }
}

/// <summary>
/// Wire mapping for the enums above, plus the throwing converters the design (§5.3.1 layer 1)
/// requires: a typo does not compile, and a foreign value does not deserialize.
/// </summary>
public static class EnumWire
{
    public static string ToWire(ApprovalStatus status) => status switch
    {
        ApprovalStatus.Proposed => SharedIdentifiers.Status.Proposed,
        ApprovalStatus.Pending => SharedIdentifiers.Status.Pending,
        ApprovalStatus.Signed => SharedIdentifiers.Status.Signed,
        ApprovalStatus.Executed => SharedIdentifiers.Status.Executed,
        ApprovalStatus.Denied => SharedIdentifiers.Status.Denied,
        _ => throw new InvalidOperationException($"Unmapped status {status}.")
    };

    public static ApprovalStatus ParseStatus(string value) => value switch
    {
        SharedIdentifiers.Status.Proposed => ApprovalStatus.Proposed,
        SharedIdentifiers.Status.Pending => ApprovalStatus.Pending,
        SharedIdentifiers.Status.Signed => ApprovalStatus.Signed,
        SharedIdentifiers.Status.Executed => ApprovalStatus.Executed,
        SharedIdentifiers.Status.Denied => ApprovalStatus.Denied,
        _ => throw new InvalidOperationException(
            $"status '{value}' is outside the closed lifecycle " +
            $"[{string.Join(", ", SharedIdentifiers.Status.All)}].")
    };

    public static string ToWire(TerminalReason reason) => reason switch
    {
        TerminalReason.HumanDenied => SharedIdentifiers.TerminalReasons.HumanDenied,
        TerminalReason.PolicyRungEscalated => SharedIdentifiers.TerminalReasons.PolicyRungEscalated,
        TerminalReason.PayloadSuperseded => SharedIdentifiers.TerminalReasons.PayloadSuperseded,
        TerminalReason.TtlExpired => SharedIdentifiers.TerminalReasons.TtlExpired,
        _ => throw new UnknownTerminalReasonException(reason.ToString())
    };

    public static TerminalReason ParseTerminalReason(string value) => value switch
    {
        SharedIdentifiers.TerminalReasons.HumanDenied => TerminalReason.HumanDenied,
        SharedIdentifiers.TerminalReasons.PolicyRungEscalated => TerminalReason.PolicyRungEscalated,
        SharedIdentifiers.TerminalReasons.PayloadSuperseded => TerminalReason.PayloadSuperseded,
        SharedIdentifiers.TerminalReasons.TtlExpired => TerminalReason.TtlExpired,
        _ => throw new UnknownTerminalReasonException(value)
    };

    public static string ToWire(ExecutionState state) => state switch
    {
        ExecutionState.NotAttempted => SharedIdentifiers.ExecutionStates.NotAttempted,
        ExecutionState.InFlight => SharedIdentifiers.ExecutionStates.InFlight,
        ExecutionState.Succeeded => SharedIdentifiers.ExecutionStates.Succeeded,
        ExecutionState.Failed => SharedIdentifiers.ExecutionStates.Failed,
        _ => throw new InvalidOperationException($"Unmapped execution state {state}.")
    };

    public static ExecutionState ParseExecutionState(string value) => value switch
    {
        SharedIdentifiers.ExecutionStates.NotAttempted => ExecutionState.NotAttempted,
        SharedIdentifiers.ExecutionStates.InFlight => ExecutionState.InFlight,
        SharedIdentifiers.ExecutionStates.Succeeded => ExecutionState.Succeeded,
        SharedIdentifiers.ExecutionStates.Failed => ExecutionState.Failed,
        _ => throw new InvalidOperationException($"Unknown execution state '{value}'.")
    };
}

/// <summary>
/// Serializes <see cref="TerminalReason"/> as its SCREAMING_SNAKE wire value and <b>throws on
/// unknown values in both directions</b> (design §5.3.1, enforcement layer 1).
/// </summary>
public class ThrowingTerminalReasonConverter : JsonConverter<TerminalReason?>
{
    public override void WriteJson(JsonWriter writer, TerminalReason? value, JsonSerializer serializer)
    {
        if (value is null)
        {
            writer.WriteNull();
            return;
        }

        writer.WriteValue(EnumWire.ToWire(value.Value));
    }

    public override TerminalReason? ReadJson(
        JsonReader reader, Type objectType, TerminalReason? existingValue,
        bool hasExistingValue, JsonSerializer serializer)
    {
        if (reader.TokenType == JsonToken.Null) return null;

        var raw = reader.Value?.ToString();
        if (string.IsNullOrEmpty(raw)) return null;

        return EnumWire.ParseTerminalReason(raw);
    }
}

/// <summary>Serializes <see cref="ApprovalStatus"/> as its lowercase wire value, throwing on unknown input.</summary>
public class ThrowingApprovalStatusConverter : JsonConverter<ApprovalStatus>
{
    public override void WriteJson(JsonWriter writer, ApprovalStatus value, JsonSerializer serializer)
        => writer.WriteValue(EnumWire.ToWire(value));

    public override ApprovalStatus ReadJson(
        JsonReader reader, Type objectType, ApprovalStatus existingValue,
        bool hasExistingValue, JsonSerializer serializer)
        => EnumWire.ParseStatus(reader.Value?.ToString()
            ?? throw new InvalidOperationException("status is required on an approval document."));
}

/// <summary>Serializes <see cref="ExecutionState"/> as its snake_case wire value, throwing on unknown input.</summary>
public class ThrowingExecutionStateConverter : JsonConverter<ExecutionState>
{
    public override void WriteJson(JsonWriter writer, ExecutionState value, JsonSerializer serializer)
        => writer.WriteValue(EnumWire.ToWire(value));

    public override ExecutionState ReadJson(
        JsonReader reader, Type objectType, ExecutionState existingValue,
        bool hasExistingValue, JsonSerializer serializer)
        => EnumWire.ParseExecutionState(reader.Value?.ToString()
            ?? SharedIdentifiers.ExecutionStates.NotAttempted);
}

/// <summary>Serializes <see cref="Rung"/> as <c>L1</c>/<c>L2</c>/<c>L3</c>.</summary>
public class RungConverter : JsonConverter<Rung>
{
    public override void WriteJson(JsonWriter writer, Rung value, JsonSerializer serializer)
        => writer.WriteValue(RungOrder.ToWire(value));

    public override Rung ReadJson(
        JsonReader reader, Type objectType, Rung existingValue,
        bool hasExistingValue, JsonSerializer serializer)
        => RungOrder.Parse(reader.Value?.ToString()
            ?? throw new InvalidOperationException("rung is required."));
}
