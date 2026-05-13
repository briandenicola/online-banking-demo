using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using StackExchange.Redis;
using TransferService.Repositories;

namespace TransferService.Services;

/// <summary>
/// In-memory variant of <see cref="TransferService"/>. Differs from production
/// only in storage (uses <see cref="InMemoryTransferRepository"/>); HTTP-based
/// account ownership / transaction creation calls and Redis stream publishing
/// retain real implementations.
/// </summary>
public sealed class InMemoryTransferService : TransferService
{
    public InMemoryTransferService(
        IConnectionMultiplexer redis,
        IHttpClientFactory httpClientFactory,
        IHttpContextAccessor httpContextAccessor,
        IConfiguration configuration,
        ILogger<InMemoryTransferService> logger)
        : base(
            new InMemoryTransferRepository(),
            new RedisEventPublisher(redis),
            NullLogger<TransferService>.Instance,
            configuration,
            httpClientFactory,
            httpContextAccessor)
    {
        logger.LogInformation("InMemoryTransferService initialised (in-memory transfer store)");
    }
}
