using AuthorityService.Models;
using AuthorityService.Services;
using FluentAssertions;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace BankerCopilotTests.Store;

/// <summary>
/// Out-of-band notification sinks (epic §5.6). Two invariants are the whole point and are the
/// things tested here rather than transport plumbing:
///
///   1. A notification NEVER names a co-signer — that is the epic §5.2.2 rule against a
///      requester choosing their own reviewer, expressed on the wire.
///   2. Notification is fire-and-forget: a failing sink is isolated and never propagates.
/// </summary>
public sealed class NotificationSinkTests
{
    private static Approval PendingCoSignApproval() => new()
    {
        Id = "apr_test_0001",
        RequesterId = "user_banker",
        RequesterUsername = "b.torres",
        ActionId = "transfer.initiate",
        ActionLabel = "Initiate a transfer between accounts",
        SessionId = "sess_1",
        Status = ApprovalStatus.Pending,
        RequiredRung = Rung.L2,
        RequesterSeniority = 1,
        AwaitingSeniority = 2,
        PendingSlotOrdinal = 1,
        CorrelationId = "corr_1",
        CreatedAt = DateTime.UtcNow,
        ExpiresAt = DateTime.UtcNow.AddMinutes(15)
    };

    [Fact]
    public void FromApproval_carries_the_kind_of_signer_needed_and_never_a_cosigner()
    {
        var approval = PendingCoSignApproval();

        var notification = SupervisorNotification.FromApproval(approval);

        notification.AwaitingSeniority.Should().Be(2);
        notification.PendingSlotOrdinal.Should().Be(1);
        notification.RequiredRung.Should().Be("L2");

        // The envelope is the whole cross-sink contract. It must describe WHAT KIND of signer is
        // needed and never WHO — there is no cosigner/cosignerId/assignee field, by design.
        var envelope = notification.ToEnvelope();
        var propertyNames = envelope.Properties().Select(p => p.Name.ToLowerInvariant()).ToList();

        propertyNames.Should().NotContain(n =>
            n.Contains("cosigner") || n.Contains("assignee") || n.Contains("reviewerid"));
        ((int)envelope["awaitingSeniority"]!).Should().Be(2);
        ((string)envelope["approvalId"]!).Should().Be("apr_test_0001");
    }

    [Fact]
    public async Task Composite_isolates_a_failing_sink_from_the_others()
    {
        var good = new NullNotificationSink();
        var boom = new ThrowingSink();

        var composite = new CompositeNotificationSink(
            new INotificationSink[] { boom, good },
            NullLogger<CompositeNotificationSink>.Instance);

        // The throwing sink must not stop the working one, and the whole call must not throw.
        var act = async () => await composite.NotifyAsync(
            SupervisorNotification.FromApproval(PendingCoSignApproval()));

        await act.Should().NotThrowAsync();
        good.Sent.Should().HaveCount(1);
    }

    [Fact]
    public void Webhook_sink_is_inert_when_no_url_is_configured()
    {
        // An unconfigured optional sink is inert, never defaulted to a guessed endpoint.
        var sink = new WebhookNotificationSink(
            new StubHttpClientFactory(), url: null, timeoutSeconds: 5,
            NullLogger<WebhookNotificationSink>.Instance);

        var act = async () => await sink.NotifyAsync(
            SupervisorNotification.FromApproval(PendingCoSignApproval()));

        act.Should().NotThrowAsync();
    }

    [Theory]
    [InlineData("redis-stream", 1)]
    [InlineData("redis-stream, webhook", 2)]
    [InlineData("redis-stream,webhook,redis-stream", 2)]
    [InlineData("", 0)]
    public void EnabledSinks_parses_the_configured_list_without_duplicates(string configured, int expected)
    {
        var options = new NotificationOptions { Sinks = configured };

        options.EnabledSinks().Should().HaveCount(expected);
    }

    [Fact]
    public void RedisStreamKey_default_is_not_the_audited_banking_events_bus()
    {
        // A notification is transient and must never share the audited event vocabulary.
        new NotificationOptions().RedisStreamKey.Should().NotBe("banking-events");
    }

    private sealed class ThrowingSink : INotificationSink
    {
        public string Name => "throwing";

        public Task NotifyAsync(SupervisorNotification notification, CancellationToken ct = default)
            => throw new InvalidOperationException("sink transport is down");
    }

    private sealed class StubHttpClientFactory : IHttpClientFactory
    {
        public HttpClient CreateClient(string name) => new();
    }
}
