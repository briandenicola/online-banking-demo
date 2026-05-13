using StackExchange.Redis;

namespace UserService.Repositories;

public class RedisEventPublisher : IEventPublisher
{
    private readonly IConnectionMultiplexer _redis;

    public RedisEventPublisher(IConnectionMultiplexer redis)
    {
        _redis = redis;
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
