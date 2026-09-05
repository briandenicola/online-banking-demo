using System.ComponentModel.DataAnnotations;
using AuthorityService.Models;
using Newtonsoft.Json.Linq;

namespace AuthorityService.Contracts;

public class ProposeRequest
{
    /// <summary>Canonical <c>&lt;domain&gt;.&lt;entity&gt;.&lt;verb&gt;</c> action id.</summary>
    [Required]
    public string ActionId { get; set; } = string.Empty;

    [Required]
    public JObject Payload { get; set; } = new();

    public JObject Evidence { get; set; } = new();

    /// <summary>Facts the caller supplies for evaluation (counts, flags, prior state).</summary>
    public JObject Facts { get; set; } = new();

    public JObject? AgentAssessment { get; set; }

    public string? SessionId { get; set; }

    public string? AgentId { get; set; }

    /// <summary>
    /// The approval this one replaces, when the agent re-plans. The old one is denied with
    /// <c>PAYLOAD_SUPERSEDED</c> and linked by <c>supersededByApprovalId</c>.
    /// </summary>
    public string? SupersedesApprovalId { get; set; }
}

public class SignRequest
{
    public string? Comment { get; set; }

    /// <summary>
    /// The hash the signer's client displayed. Optional, but when supplied it must match — it
    /// catches a payload that changed between render and click.
    /// </summary>
    public string? ExpectedPayloadHash { get; set; }
}

public class DenyRequest
{
    /// <summary>Mandatory free text. Validated against the V1–V6 rules (design §8.7.1).</summary>
    [Required]
    public string Reason { get; set; } = string.Empty;
}

/// <summary>
/// Batch sign (design §8.6). <b>L1 only, one action type, never "Approve All".</b> There is no
/// endpoint that accepts a batch without an <see cref="ActionId"/>, so an unscoped bulk approve
/// is not expressible; and any item that resolved to L2 is rejected into
/// <see cref="BatchSignResponse.Rejected"/> for individual handling rather than co-signed in bulk
/// — batching a second opinion defeats the second opinion (invariant I-10).
/// </summary>
public class BatchSignRequest
{
    /// <summary>The approvals to sign. All must carry <see cref="ActionId"/>.</summary>
    [Required]
    public List<string> ApprovalIds { get; set; } = [];

    /// <summary>
    /// The single action type this batch is scoped to. Server-verified against every item; an
    /// approval of any other action is rejected, not signed. This is what makes "Approve All"
    /// unrepresentable.
    /// </summary>
    [Required]
    public string ActionId { get; set; } = string.Empty;

    public string? Comment { get; set; }

    /// <summary>
    /// Optional per-approval expected payload hash (the hash the client displayed). When supplied
    /// for an item and it does not match, that item is rejected — the same TOCTOU guard the single
    /// sign path applies, per item.
    /// </summary>
    public Dictionary<string, string>? ExpectedPayloadHashes { get; set; }
}

public class BatchSignResponse
{
    public List<ApprovalResponse> Signed { get; set; } = [];
    public List<BatchRejection> Rejected { get; set; } = [];
}

public class BatchRejection
{
    public string ApprovalId { get; set; } = string.Empty;
    public string Code { get; set; } = string.Empty;
    public string Reason { get; set; } = string.Empty;

    public BatchRejection() { }

    public BatchRejection(string approvalId, string code, string reason)
    {
        ApprovalId = approvalId;
        Code = code;
        Reason = reason;
    }
}

public class EvaluateRequest
{
    [Required]
    public string ActionId { get; set; } = string.Empty;

    [Required]
    public JObject Payload { get; set; } = new();

    public JObject Evidence { get; set; } = new();

    public JObject Facts { get; set; } = new();
}

public class ApprovalResponse
{
    public string Id { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public string ActionId { get; set; } = string.Empty;
    public string ActionLabel { get; set; } = string.Empty;
    public string RequesterId { get; set; } = string.Empty;
    public string? RequesterUsername { get; set; }
    public string? SessionId { get; set; }
    public JObject Payload { get; set; } = new();
    public JObject Evidence { get; set; } = new();
    public JObject? AgentAssessment { get; set; }
    public string PayloadHash { get; set; } = string.Empty;
    public string PayloadHashShort { get; set; } = string.Empty;
    public string PolicyVersion { get; set; } = string.Empty;
    public string PolicyId { get; set; } = string.Empty;
    public string BaseRung { get; set; } = string.Empty;
    public string RequiredRung { get; set; } = string.Empty;
    public int RequiredSigners { get; set; }
    public int SignaturesCollected { get; set; }
    public List<FiredEscalatorView> FiredEscalators { get; set; } = [];
    public List<SignatureSlotView> SignatureSlots { get; set; } = [];
    public DateTime CreatedAt { get; set; }
    public DateTime ExpiresAt { get; set; }
    public DateTime? TerminalAt { get; set; }
    public string? TerminalReason { get; set; }
    public string? TerminalDetail { get; set; }
    public string? SupersededByApprovalId { get; set; }
    public string? SupersedesApprovalId { get; set; }
    public string ExecutionState { get; set; } = string.Empty;
    public string? DownstreamRef { get; set; }
    public int? DownstreamStatus { get; set; }
    public string? ExecutionError { get; set; }

    /// <summary>True only when the CALLER may sign this approval right now.</summary>
    public bool CallerMaySign { get; set; }

    /// <summary>Why not, when <see cref="CallerMaySign"/> is false. Server-computed, never inferred client-side.</summary>
    public string? CallerMaySignReason { get; set; }

    public static ApprovalResponse From(Approval a) => new()
    {
        Id = a.Id,
        Status = EnumWire.ToWire(a.Status),
        ActionId = a.ActionId,
        ActionLabel = a.ActionLabel,
        RequesterId = a.RequesterId,
        RequesterUsername = a.RequesterUsername,
        SessionId = a.SessionId,
        Payload = a.Payload,
        Evidence = a.Evidence,
        AgentAssessment = a.AgentAssessment,
        PayloadHash = a.PayloadHash,
        PayloadHashShort = Policy.PayloadHasher.Short(a.PayloadHash),
        PolicyVersion = a.PolicyVersion,
        PolicyId = a.PolicyId,
        BaseRung = RungOrder.ToWire(a.BaseRung),
        RequiredRung = RungOrder.ToWire(a.RequiredRung),
        RequiredSigners = a.RequiredSigners,
        SignaturesCollected = a.SignaturesCollected,
        FiredEscalators = a.FiredEscalators.Select(FiredEscalatorView.From).ToList(),
        SignatureSlots = a.SignatureSlots.Select(SignatureSlotView.From).ToList(),
        CreatedAt = a.CreatedAt,
        ExpiresAt = a.ExpiresAt,
        TerminalAt = a.TerminalAt,
        TerminalReason = a.TerminalReason is null ? null : EnumWire.ToWire(a.TerminalReason.Value),
        TerminalDetail = a.TerminalDetail,
        SupersededByApprovalId = a.SupersededByApprovalId,
        SupersedesApprovalId = a.SupersedesApprovalId,
        ExecutionState = EnumWire.ToWire(a.Execution.State),
        DownstreamRef = a.Execution.DownstreamRef,
        DownstreamStatus = a.Execution.DownstreamStatus,
        ExecutionError = a.Execution.LastError
    };
}

public class FiredEscalatorView
{
    public string Key { get; set; } = string.Empty;
    public string RaisedTo { get; set; } = string.Empty;
    public string Scope { get; set; } = string.Empty;
    public string? ThresholdName { get; set; }
    public string? ThresholdValue { get; set; }
    public string Reason { get; set; } = string.Empty;

    public static FiredEscalatorView From(FiredEscalator e) => new()
    {
        Key = e.Key,
        RaisedTo = RungOrder.ToWire(e.RaisedTo),
        Scope = e.Scope,
        ThresholdName = e.ThresholdName,
        ThresholdValue = e.ThresholdValue,
        Reason = e.Reason
    };
}

public class SignatureSlotView
{
    public int Ordinal { get; set; }
    public int MinSeniority { get; set; }
    public List<string> MustDifferFrom { get; set; } = [];
    public string? SignedBy { get; set; }
    public string? SignedByUsername { get; set; }
    public DateTime? SignedAt { get; set; }
    public string? Comment { get; set; }
    public bool Filled { get; set; }

    public static SignatureSlotView From(SignatureSlot s) => new()
    {
        Ordinal = s.Ordinal,
        MinSeniority = s.MinSeniority,
        MustDifferFrom = s.MustDifferFrom,
        SignedBy = s.SignedBy,
        SignedByUsername = s.SignedByUsername,
        SignedAt = s.SignedAt,
        Comment = s.Comment,
        Filled = s.SignedBy is not null
    };
}

public class EvaluateResponse
{
    public string ActionId { get; set; } = string.Empty;
    public string Outcome { get; set; } = string.Empty;
    public string BaseRung { get; set; } = string.Empty;
    public string RequiredRung { get; set; } = string.Empty;
    public int RequiredSigners { get; set; }
    public int MinSeniority { get; set; }
    public int TtlSeconds { get; set; }
    public string PolicyVersion { get; set; } = string.Empty;
    public List<FiredEscalatorView> FiredEscalators { get; set; } = [];
    public List<string> EvidenceGaps { get; set; } = [];
    public string? RejectionReason { get; set; }
}

public class PolicySummaryResponse
{
    public string PolicyId { get; set; } = string.Empty;
    public string PolicyVersion { get; set; } = string.Empty;
    public string ApiVersion { get; set; } = string.Empty;
    public DateTime LoadedAt { get; set; }
    public List<ThresholdView> Thresholds { get; set; } = [];
    public List<ActionView> Actions { get; set; } = [];
}

public class ThresholdView
{
    public string Name { get; set; } = string.Empty;
    public string Kind { get; set; } = string.Empty;
    public string Env { get; set; } = string.Empty;
    public string Value { get; set; } = string.Empty;
    public bool OverriddenByEnv { get; set; }
    public string Description { get; set; } = string.Empty;
}

public class ActionView
{
    public string Id { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string BaseRung { get; set; } = string.Empty;
    public bool AgentMayPropose { get; set; }
    public List<string> RequiredEvidence { get; set; } = [];
}

/// <summary>An operational failure the API surfaces verbatim. Never a raw exception message.</summary>
public class ApiError
{
    public string Error { get; set; }
    public string Message { get; set; }
    public string? Detail { get; set; }
    public object? Data { get; set; }

    public ApiError(string error, string message, string? detail = null, object? data = null)
    {
        Error = error;
        Message = message;
        Detail = detail;
        Data = data;
    }
}
