using System.Collections.Concurrent;
using System.Linq;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using StackExchange.Redis;
using TransactionService.Models;

namespace TransactionService.Services;

public class InMemoryTransactionService : ITransactionService
{
    private readonly ConcurrentDictionary<string, Transaction> _transactions = new();
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<InMemoryTransactionService> _logger;
    private const string StreamName = "banking-events";

    public InMemoryTransactionService(IConnectionMultiplexer redis, ILogger<InMemoryTransactionService> logger)
    {
        _redis = redis;
        _logger = logger;
    }

    public async Task<Transaction> CreateTransactionAsync(CreateTransactionRequest request)
    {
        var transaction = new Transaction
        {
            Id = System.Guid.NewGuid().ToString(),
            AccountId = request.AccountId,
            Amount = request.Amount,
            Currency = request.Currency ?? "USD",
            Type = request.Type,
            Description = request.Description,
            Category = request.Category ?? "Uncategorized"
        };
        _transactions[transaction.Id] = transaction;

        // Publish TransactionCreated event to Redis Stream
        try
        {
            var eventPayload = new
            {
                eventType = "TransactionCreated",
                timestamp = DateTime.UtcNow.ToString("o"),
                data = new
                {
                    accountId = transaction.AccountId,
                    amount = transaction.Amount,
                    type = transaction.Type,
                    description = transaction.Description
                }
            };

            var db = _redis.GetDatabase();
            await db.StreamAddAsync(StreamName, new NameValueEntry[]
            {
                new("payload", JsonConvert.SerializeObject(eventPayload))
            });

            _logger.LogInformation("Published TransactionCreated event to Redis for transaction {TransactionId}", transaction.Id);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to publish event to Redis for transaction {TransactionId}", transaction.Id);
        }

        return transaction;
    }

    public Task<Transaction?> GetTransactionByIdAsync(string id, string? accountId = null)
    {
        _transactions.TryGetValue(id, out var transaction);
        return Task.FromResult(transaction);
    }

    public Task<IEnumerable<Transaction>> GetAccountTransactionsAsync(string accountId, int limit = 50)
    {
        var transactions = _transactions.Values
            .Where(t => t.AccountId == accountId)
            .OrderByDescending(t => t.Timestamp)
            .Take(limit);
        return Task.FromResult(transactions);
    }

    public Task<IEnumerable<Transaction>> GetUserTransactionsAsync(string userId, int limit = 50)
    {
        var transactions = _transactions.Values
            .OrderByDescending(t => t.Timestamp)
            .Take(limit);
        return Task.FromResult(transactions);
    }
}