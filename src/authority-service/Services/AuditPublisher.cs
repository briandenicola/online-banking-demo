using AuthorityService.Models;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using StackExchange.Redis;

namespace AuthorityService.Services;

/// <summary>
/// Publishes the Banker Copilot audit events onto the existing <c>banking-events</c> Redis
/// Stream, in the envelope the Go <c>event-processor</c> already consumes.
///
/// Event names are PascalCase because the existing consumer switches on
/// <c>TransactionCreated</c>-style names. A new snake_case family would either be silently
/// dropped or force a second vocabulary into the same stream — either way, the audit trail
/// stops being one trail (epic §5.7).
/// </summary>
public interface IAuditPublisher
{
    Task PublishAsync(string eventType, object data, CancellationToken ct = default);
}

public class RedisAuditPublisher : IAuditPublisher
{
    private const string StreamKey = "banking-events";

    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<RedisAuditPublisher> _logger;

    public RedisAuditPublisher(IConnectionMultiplexer redis, ILogger<RedisAuditPublisher> logger)
    {
        _redis = redis;
        _logger = logger;
    }

    public async Task PublishAsync(string eventType, object data, CancellationToken ct = default)
    {
        if (!SharedIdentifiers.Events.All.Contains(eventType))
        {
            // A typo'd event name is a silently missing audit record, so it fails loudly here.
            throw new InvalidOperationException(
                $"'{eventType}' is not one of the declared Banker Copilot audit events.");
        }

        try
        {
            var envelope = new JObject
            {
                ["eventType"] = eventType,
                ["timestamp"] = DateTime.UtcNow.ToString("O"),
                ["data"] = JToken.FromObject(data)
            };

            var db = _redis.GetDatabase();

            await db.StreamAddAsync(
                StreamKey,
                [new NameValueEntry("payload", envelope.ToString(Formatting.None))]);
        }
        catch (Exception ex)
        {
            // Audit publishing is best-effort at the transport layer; the Cosmos document is
            // the system of record. Failing the approval because Redis blinked would be worse
            // than a late audit event.
            _logger.LogError(ex, "Failed to publish {EventType} to the audit stream", eventType);
        }
    }
}

/// <summary>Used when no Redis connection is configured (unit tests, isolated dev runs).</summary>
public class NullAuditPublisher : IAuditPublisher
{
    public List<(string EventType, object Data)> Published { get; } = [];

    public Task PublishAsync(string eventType, object data, CancellationToken ct = default)
    {
        Published.Add((eventType, data));
        return Task.CompletedTask;
    }
}

/// <summary>
/// The event payload shapes (design §7.2). Kept as explicit factories rather than anonymous
/// objects at call sites so the field names are reviewable in one place.
/// </summary>
public static class AuditEvents
{
    public static object ApprovalProposed(Approval approval) => new
    {
        approvalId = approval.Id,
        sessionId = approval.SessionId,
        actionId = approval.ActionId,
        requesterId = approval.RequesterId,
        baseRung = RungOrder.ToWire(approval.BaseRung),
        requiredRung = RungOrder.ToWire(approval.RequiredRung),
        requiredSigners = approval.RequiredSigners,
        firedEscalators = approval.FiredEscalators.Select(e => e.Key).ToArray(),
        payloadHash = approval.PayloadHash,
        policyVersion = approval.PolicyVersion,
        expiresAt = approval.ExpiresAt,
        correlationId = approval.CorrelationId
    };

    public static object ActionProposalRejected(
        string actionId, string requesterId, string? sessionId, string reason, string? correlationId) => new
    {
        actionId,
        requesterId,
        sessionId,
        reason,
        correlationId
    };

    public static object PolicyEscalated(Approval approval) => new
    {
        approvalId = approval.Id,
        actionId = approval.ActionId,
        requesterId = approval.RequesterId,
        baseRung = RungOrder.ToWire(approval.BaseRung),
        requiredRung = RungOrder.ToWire(approval.RequiredRung),
        firedEscalators = approval.FiredEscalators.Select(e => new
        {
            key = e.Key,
            raisedTo = RungOrder.ToWire(e.RaisedTo),
            thresholdName = e.ThresholdName,
            thresholdValue = e.ThresholdValue,
            reason = e.Reason
        }).ToArray(),
        policyVersion = approval.PolicyVersion,
        correlationId = approval.CorrelationId
    };

    public static object ApprovalSigned(Approval approval, SignatureSlot slot) => new
    {
        approvalId = approval.Id,
        actionId = approval.ActionId,
        requesterId = approval.RequesterId,
        signedBy = slot.SignedBy,
        signedByUsername = slot.SignedByUsername,
        slotOrdinal = slot.Ordinal,
        signaturesCollected = approval.SignaturesCollected,
        requiredSigners = approval.RequiredSigners,
        quorumReached = approval.Status == ApprovalStatus.Signed,
        requiredRung = RungOrder.ToWire(approval.RequiredRung),
        payloadHash = approval.PayloadHash,
        policyVersion = approval.PolicyVersion,
        correlationId = approval.CorrelationId
    };

    public static object ApprovalDenied(Approval approval) => new
    {
        approvalId = approval.Id,
        actionId = approval.ActionId,
        requesterId = approval.RequesterId,
        terminalReason = EnumWire.ToWire(approval.TerminalReason!.Value),
        terminalDetail = approval.TerminalDetail,
        deniedBy = approval.SignatureSlots.LastOrDefault(s => s.SignedBy is not null)?.SignedBy,
        terminalAt = approval.TerminalAt,
        supersededByApprovalId = approval.SupersededByApprovalId,
        correlationId = approval.CorrelationId
    };

    public static object ApprovalExpired(Approval approval, int ageSeconds) => new
    {
        approvalId = approval.Id,
        actionId = approval.ActionId,
        requesterId = approval.RequesterId,
        // Emitted alongside ApprovalDenied/TTL_EXPIRED. Expiry means denied, never approved.
        terminalReason = SharedIdentifiers.TerminalReasons.TtlExpired,
        expiresAt = approval.ExpiresAt,
        ageSeconds,
        signaturesCollected = approval.SignaturesCollected,
        requiredSigners = approval.RequiredSigners,
        correlationId = approval.CorrelationId
    };

    public static object ApprovalExecuted(Approval approval) => new
    {
        approvalId = approval.Id,
        actionId = approval.ActionId,
        requesterId = approval.RequesterId,
        signers = approval.SignerIds,
        downstreamStatus = approval.Execution.DownstreamStatus,
        downstreamRef = approval.Execution.DownstreamRef,
        attempts = approval.Execution.Attempts,
        // Denormalised deliberately: an audit event is a standalone record and must be
        // interpretable without reading the approval back. Sourced from policy.policyVersion,
        // which §5.3.2 guarantees is the version the signatures were produced under.
        signedUnderPolicyVersion = approval.PolicyVersion,
        evaluatedUnderPolicyVersion = approval.Execution.EvaluatedUnderPolicyVersion,
        payloadHash = approval.PayloadHash,
        correlationId = approval.CorrelationId
    };

    public static object ApprovalExecutionFailed(Approval approval, string error) => new
    {
        approvalId = approval.Id,
        actionId = approval.ActionId,
        requesterId = approval.RequesterId,
        // NOTE: status remains `signed`. There is no execution_failed lifecycle state.
        status = EnumWire.ToWire(approval.Status),
        executionState = EnumWire.ToWire(approval.Execution.State),
        attempts = approval.Execution.Attempts,
        downstreamStatus = approval.Execution.DownstreamStatus,
        error,
        correlationId = approval.CorrelationId
    };

    /// <summary>
    /// The §5.3.2 void. Carries BOTH policy versions and the signatures that were discarded —
    /// without that, "your approval vanished" is indistinguishable from a bug.
    /// </summary>
    public static object ApprovalVoidedByPolicyChange(
        Approval voided, string signedPolicyVersion, string currentPolicyVersion,
        Rung signedRung, Rung newRung, IEnumerable<FiredEscalator> newEscalators) => new
    {
        approvalId = voided.Id,
        actionId = voided.ActionId,
        requesterId = voided.RequesterId,
        terminalReason = SharedIdentifiers.TerminalReasons.PolicyRungEscalated,
        signedPolicyVersion,
        currentPolicyVersion,
        signedRung = RungOrder.ToWire(signedRung),
        newRung = RungOrder.ToWire(newRung),
        newEscalators = newEscalators.Select(e => new
        {
            key = e.Key,
            raisedTo = RungOrder.ToWire(e.RaisedTo),
            thresholdName = e.ThresholdName,
            thresholdValue = e.ThresholdValue,
            reason = e.Reason
        }).ToArray(),
        discardedSignatures = voided.SignatureSlots
            .Where(s => s.SignedBy is not null)
            .Select(s => new
            {
                signedBy = s.SignedBy,
                signedAt = s.SignedAt,
                // Sourced from the document's single copy; an audit event is a standalone
                // record and must be readable without joining back to the approval.
                rungSatisfied = RungOrder.ToWire(voided.RequiredRung),
                boundPolicyVersion = voided.PolicyVersion
            }).ToArray(),
        supersededByApprovalId = voided.SupersededByApprovalId,
        correlationId = voided.CorrelationId
    };

    public static object PolicyReloaded(
        string previousPolicyVersion, string newPolicyVersion, int affectedApprovals) => new
    {
        previousPolicyVersion,
        newPolicyVersion,
        affectedApprovals,
        reloadedAt = DateTime.UtcNow
    };

    public static object CopilotSessionStarted(string sessionId, string requesterId, string policyVersion) => new
    {
        sessionId,
        requesterId,
        policyVersion,
        startedAt = DateTime.UtcNow
    };
}
