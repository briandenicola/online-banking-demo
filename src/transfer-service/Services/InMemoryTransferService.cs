using System.Collections.Concurrent;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using StackExchange.Redis;
using TransferService.Models;

namespace TransferService.Services;

public class InMemoryTransferService : ITransferService
{
    private readonly ConcurrentDictionary<string, Transfer> _transfers = new();
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<InMemoryTransferService> _logger;
    private const string StreamName = "banking-events";

    public InMemoryTransferService(IConnectionMultiplexer redis, ILogger<InMemoryTransferService> logger)
    {
        _redis = redis;
        _logger = logger;
    }

    public async Task<Transfer> InitiateTransferAsync(string userId, CreateTransferRequest request)
    {
        var transfer = new Transfer
        {
            FromAccountNumber = request.FromAccountNumber,
            ToAccountNumber = request.ToAccountNumber,
            Amount = request.Amount,
            Description = request.Description
        };
        _transfers[transfer.Id] = transfer;

        // Publish TransferInitiated event to Redis Stream
        try
        {
            var eventPayload = new
            {
                eventType = "TransferInitiated",
                timestamp = DateTime.UtcNow.ToString("o"),
                data = new
                {
                    fromAccountId = transfer.FromAccountNumber,
                    toAccountId = transfer.ToAccountNumber,
                    amount = transfer.Amount,
                    description = transfer.Description
                }
            };

            var db = _redis.GetDatabase();
            await db.StreamAddAsync(StreamName, new NameValueEntry[]
            {
                new("payload", JsonConvert.SerializeObject(eventPayload))
            });

            _logger.LogInformation("Published TransferInitiated event to Redis for transfer {TransferId}", transfer.Id);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to publish event to Redis for transfer {TransferId}", transfer.Id);
        }

        return transfer;
    }

    public Task<Transfer?> GetTransferByIdAsync(string id)
    {
        _transfers.TryGetValue(id, out var transfer);
        return Task.FromResult(transfer);
    }
}