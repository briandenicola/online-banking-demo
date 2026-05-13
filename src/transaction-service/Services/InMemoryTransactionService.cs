using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using StackExchange.Redis;
using TransactionService.Repositories;

namespace TransactionService.Services;

/// <summary>
/// In-memory variant of <see cref="TransactionService"/>. Uses
/// <see cref="InMemoryTransactionRepository"/> + <see cref="InMemoryAccountBalanceRepository"/>
/// for storage; Redis stream publishing is preserved when a multiplexer is
/// supplied so dev / test environments can still drive event consumers.
/// </summary>
public sealed class InMemoryTransactionService : TransactionService
{
    public InMemoryTransactionService(
        IConnectionMultiplexer redis,
        ILogger<InMemoryTransactionService> logger)
        : base(
            new InMemoryTransactionRepository(),
            new InMemoryAccountBalanceRepository(),
            new RedisEventPublisher(redis, NullLogger<RedisEventPublisher>.Instance),
            NullLogger<TransactionService>.Instance)
    {
        logger.LogInformation("InMemoryTransactionService seeded with demo transactions and balances");
    }
}
