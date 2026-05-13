using Microsoft.Extensions.Logging;
using StackExchange.Redis;

namespace TransactionService.Repositories;

public class RedisEventPublisher : IEventPublisher
{
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<RedisEventPublisher> _logger;

    public RedisEventPublisher(IConnectionMultiplexer redis, ILogger<RedisEventPublisher> logger)
    {
        _redis = redis;
        _logger = logger;
    }

    public async Task PublishAsync(string streamName, string payload)
    {
        var db = _redis.GetDatabase();
        await db.StreamAddAsync(streamName, new NameValueEntry[]
        {
            new("payload", payload)
        });
    }
}
