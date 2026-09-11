using AuthorityService.Models;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using StackExchange.Redis;

namespace AuthorityService.Services;

/// <summary>
/// Out-of-band notification that a human supervisor is needed to co-sign an approval
/// (epic §5.6). This is the L2 "a second, more senior human must review this" ping, fired
/// OUTSIDE the harness UI so a supervisor who is not staring at a Copilot session still learns
/// a card is waiting.
///
/// Two properties are load-bearing and enforced by construction, not by comment:
///
///  1. <b>Fire-and-forget; never gates state.</b> A failed notification must never block or
///     auto-approve anything (invariant I-1/I-6). Every sink swallows its own transport
///     failures and logs them; <see cref="ApprovalService"/> awaits nothing it cannot ignore.
///
///  2. <b>Describes the KIND of signer needed, never WHO.</b> The payload carries
///     <c>awaitingSeniority</c> / <c>pendingSlotOrdinal</c> — it does not, and must not, name a
///     co-signer. Naming one at proposal time is exactly the <c>cosignerId</c> pointer that
///     epic §5.2.2 ruled out on security grounds: it lets the requesting banker choose their own
///     reviewer, which is the self-dealing the L2 rung exists to prevent. The queue is a property
///     of the work, not of an individual.
/// </summary>
public interface INotificationSink
{
    /// <summary>A short, stable name used in logs and in the composite fan-out.</summary>
    string Name { get; }

    Task NotifyAsync(SupervisorNotification notification, CancellationToken ct = default);
}

/// <summary>
/// The out-of-band payload. Deliberately small and free of any co-signer identity — see the
/// second property on <see cref="INotificationSink"/>.
/// </summary>
public sealed record SupervisorNotification(
    string ApprovalId,
    string ActionId,
    string ActionLabel,
    string RequesterId,
    string? RequesterUsername,
    string? SessionId,
    int AwaitingSeniority,
    int PendingSlotOrdinal,
    string RequiredRung,
    DateTime ExpiresAt,
    string? CorrelationId)
{
    public const string Kind = "SupervisorCoSignatureRequested";

    public static SupervisorNotification FromApproval(Approval approval) => new(
        ApprovalId: approval.Id,
        ActionId: approval.ActionId,
        ActionLabel: approval.ActionLabel,
        RequesterId: approval.RequesterId,
        RequesterUsername: approval.RequesterUsername,
        SessionId: approval.SessionId,
        // Never a co-signer id: the KIND of signer needed, straight off the pending slot.
        AwaitingSeniority: approval.AwaitingSeniority ?? approval.MinSeniority,
        PendingSlotOrdinal: approval.PendingSlotOrdinal ?? -1,
        RequiredRung: RungOrder.ToWire(approval.RequiredRung),
        ExpiresAt: approval.ExpiresAt,
        CorrelationId: approval.CorrelationId);

    /// <summary>The wire envelope shared by every sink, so consumers parse one shape.</summary>
    public JObject ToEnvelope() => new()
    {
        ["kind"] = Kind,
        ["timestamp"] = DateTime.UtcNow.ToString("O"),
        ["approvalId"] = ApprovalId,
        ["actionId"] = ActionId,
        ["actionLabel"] = ActionLabel,
        ["requesterId"] = RequesterId,
        ["requesterUsername"] = RequesterUsername,
        ["sessionId"] = SessionId,
        ["awaitingSeniority"] = AwaitingSeniority,
        ["pendingSlotOrdinal"] = PendingSlotOrdinal,
        ["requiredRung"] = RequiredRung,
        ["expiresAt"] = ExpiresAt.ToString("O"),
        ["correlationId"] = CorrelationId
    };
}

/// <summary>
/// Selection and endpoints are configuration, never literals. Bound from the <c>Notifications</c>
/// section (env form <c>Notifications__*</c>). There is no hardcoded URL, stream name or address
/// anywhere in this file — an unconfigured optional sink is inert, not defaulted to a guess.
/// </summary>
public sealed class NotificationOptions
{
    /// <summary>Comma-separated list of enabled sink names, e.g. <c>redis-stream,webhook</c>.</summary>
    public string Sinks { get; set; } = "redis-stream";

    /// <summary>
    /// Redis Stream key the <c>redis-stream</c> sink publishes to. Defaults to a DEDICATED
    /// notification stream, NOT the audited <c>banking-events</c> bus — see
    /// <c>.squad/decisions/inbox/rusty-phase3-notification-sinks.md</c>. Override to merge them.
    /// </summary>
    public string RedisStreamKey { get; set; } = "copilot-notifications";

    /// <summary>Absolute URL for the <c>webhook</c> sink. No default: unset ⇒ the sink is inert.</summary>
    public string? WebhookUrl { get; set; }

    public int WebhookTimeoutSeconds { get; set; } = 5;

    /// <summary>Recipient for the <c>email</c> stub. Unset ⇒ inert.</summary>
    public string? EmailTo { get; set; }

    public IReadOnlyList<string> EnabledSinks() => Sinks
        .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
        .Select(s => s.ToLowerInvariant())
        .Distinct()
        .ToList();
}

/// <summary>
/// Default local implementation. Publishes the notification envelope onto a Redis Stream
/// (the same transport the audit bus uses, a DIFFERENT stream key). Reuses the connection the
/// audit publisher already holds so no second Redis dependency is introduced.
/// </summary>
public sealed class RedisStreamNotificationSink : INotificationSink
{
    public string Name => "redis-stream";

    private readonly IConnectionMultiplexer _redis;
    private readonly string _streamKey;
    private readonly ILogger<RedisStreamNotificationSink> _logger;

    public RedisStreamNotificationSink(
        IConnectionMultiplexer redis, string streamKey, ILogger<RedisStreamNotificationSink> logger)
    {
        _redis = redis;
        _streamKey = streamKey;
        _logger = logger;
    }

    public async Task NotifyAsync(SupervisorNotification notification, CancellationToken ct = default)
    {
        try
        {
            var db = _redis.GetDatabase();
            await db.StreamAddAsync(
                _streamKey,
                [new NameValueEntry("payload", notification.ToEnvelope().ToString(Formatting.None))]);
        }
        catch (Exception ex)
        {
            // Fire-and-forget: a supervisor notification that fails to send must never fail the
            // signature that triggered it. The approval is the system of record; a late ping is
            // recoverable, a blocked approval path is not.
            _logger.LogError(ex,
                "redis-stream notification for approval {ApprovalId} failed to publish to {StreamKey}",
                notification.ApprovalId, _streamKey);
        }
    }
}

/// <summary>
/// POSTs the notification envelope to a configured URL (Teams/Slack incoming webhook in a live
/// demo). Inert — and says so once at startup — when no URL is configured, rather than inventing
/// an endpoint.
/// </summary>
public sealed class WebhookNotificationSink : INotificationSink
{
    public string Name => "webhook";

    private readonly IHttpClientFactory _httpClientFactory;
    private readonly string? _url;
    private readonly TimeSpan _timeout;
    private readonly ILogger<WebhookNotificationSink> _logger;

    public WebhookNotificationSink(
        IHttpClientFactory httpClientFactory, string? url, int timeoutSeconds,
        ILogger<WebhookNotificationSink> logger)
    {
        _httpClientFactory = httpClientFactory;
        _url = string.IsNullOrWhiteSpace(url) ? null : url.Trim();
        _timeout = TimeSpan.FromSeconds(Math.Max(1, timeoutSeconds));
        _logger = logger;

        if (_url is null)
        {
            _logger.LogWarning(
                "webhook notification sink is enabled but Notifications:WebhookUrl is unset; it is inert.");
        }
    }

    public async Task NotifyAsync(SupervisorNotification notification, CancellationToken ct = default)
    {
        if (_url is null) return;

        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(_timeout);

            var client = _httpClientFactory.CreateClient();
            var content = new StringContent(
                notification.ToEnvelope().ToString(Formatting.None),
                System.Text.Encoding.UTF8, "application/json");

            var response = await client.PostAsync(_url, content, cts.Token);
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning(
                    "webhook notification for approval {ApprovalId} returned {StatusCode}",
                    notification.ApprovalId, (int)response.StatusCode);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex,
                "webhook notification for approval {ApprovalId} failed to POST", notification.ApprovalId);
        }
    }
}

/// <summary>
/// Demo stub: logs the notification instead of sending mail, so the interface exists and adding a
/// real transport later is not a refactor (epic §5.6). Inert unless a recipient is configured.
/// </summary>
public sealed class EmailNotificationSink : INotificationSink
{
    public string Name => "email";

    private readonly string? _emailTo;
    private readonly ILogger<EmailNotificationSink> _logger;

    public EmailNotificationSink(string? emailTo, ILogger<EmailNotificationSink> logger)
    {
        _emailTo = string.IsNullOrWhiteSpace(emailTo) ? null : emailTo.Trim();
        _logger = logger;

        if (_emailTo is null)
        {
            _logger.LogWarning(
                "email notification sink is enabled but Notifications:EmailTo is unset; it is inert.");
        }
    }

    public Task NotifyAsync(SupervisorNotification notification, CancellationToken ct = default)
    {
        if (_emailTo is not null)
        {
            _logger.LogInformation(
                "[email stub] Would notify {EmailTo}: approval {ApprovalId} ({ActionId}) awaits a " +
                "seniority-{AwaitingSeniority} co-signature.",
                _emailTo, notification.ApprovalId, notification.ActionId, notification.AwaitingSeniority);
        }

        return Task.CompletedTask;
    }
}

/// <summary>
/// Fans a notification out to every configured sink and ISOLATES their failures from each other —
/// one broken webhook must not stop the redis-stream ping. Fire-and-forget all the way down.
/// </summary>
public sealed class CompositeNotificationSink : INotificationSink
{
    public string Name => "composite";

    private readonly IReadOnlyList<INotificationSink> _sinks;
    private readonly ILogger<CompositeNotificationSink> _logger;

    public CompositeNotificationSink(
        IReadOnlyList<INotificationSink> sinks, ILogger<CompositeNotificationSink> logger)
    {
        _sinks = sinks;
        _logger = logger;
    }

    public IReadOnlyList<INotificationSink> Sinks => _sinks;

    public async Task NotifyAsync(SupervisorNotification notification, CancellationToken ct = default)
    {
        if (_sinks.Count == 0) return;

        var results = await Task.WhenAll(_sinks.Select(async sink =>
        {
            try
            {
                await sink.NotifyAsync(notification, ct);
                return true;
            }
            catch (Exception ex)
            {
                // Belt and braces: a sink already swallows its own transport errors, but a bug in
                // one sink must not deny the others their turn.
                _logger.LogError(ex,
                    "notification sink {Sink} threw for approval {ApprovalId}",
                    sink.Name, notification.ApprovalId);
                return false;
            }
        }));

        if (results.All(ok => !ok) && _sinks.Count > 0)
        {
            _logger.LogWarning(
                "every notification sink failed for approval {ApprovalId}; the approval is unaffected.",
                notification.ApprovalId);
        }
    }
}

/// <summary>Used when notifications are disabled or no Redis connection exists. Records for tests.</summary>
public sealed class NullNotificationSink : INotificationSink
{
    public string Name => "null";

    public List<SupervisorNotification> Sent { get; } = [];

    public Task NotifyAsync(SupervisorNotification notification, CancellationToken ct = default)
    {
        Sent.Add(notification);
        return Task.CompletedTask;
    }
}
