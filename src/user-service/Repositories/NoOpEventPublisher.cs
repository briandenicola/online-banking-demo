using Microsoft.Extensions.Logging;

namespace UserService.Repositories;

/// <summary>
/// No-op event publisher used when the service is configured with the in-memory
/// store. Logs each publish at debug level so dev / test logs still show events.
/// </summary>
public class NoOpEventPublisher : IEventPublisher
{
    private readonly ILogger<NoOpEventPublisher>? _logger;

    public NoOpEventPublisher(ILogger<NoOpEventPublisher>? logger = null)
    {
        _logger = logger;
    }

    public Task PublishAsync(string streamName, string payload)
    {
        _logger?.LogDebug("[NoOp] would publish to {StreamName}: {Payload}", streamName, payload);
        return Task.CompletedTask;
    }
}
