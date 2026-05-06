using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using StackExchange.Redis;
using TransactionService.Models;

namespace TransactionService.Services;

public class TransactionService : ITransactionService
{
    private readonly Container _container;
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<TransactionService> _logger;
    private readonly IConfiguration _configuration;
    private const string StreamName = "banking-events";

    public TransactionService(
        CosmosClient cosmosClient,
        IConnectionMultiplexer redis,
        ILogger<TransactionService> logger,
        IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _redis = redis;
        _logger = logger;
        _configuration = configuration;
    }

    public async Task<Transaction> CreateTransactionAsync(OnlineBankingDemo.Contracts.Dtos.CreateTransactionRequest request)
    {
        var transaction = new Transaction
        {
            Id = Guid.NewGuid().ToString(),
            AccountId = request.AccountId,
            Amount = request.Amount,
            Currency = request.Currency ?? "USD",
            Type = request.Type,
            Description = request.Description,
            Category = request.Category ?? "Uncategorized",
            RelatedTransactionId = request.RelatedTransactionId
        };

        await _container.CreateItemAsync(transaction, new PartitionKey(transaction.AccountId));
        
        // Publish TransactionCreated event to Redis Stream
        await PublishTransactionCreatedEvent(transaction);

        return transaction;
    }

    public async Task<Transaction?> GetTransactionByIdAsync(string id, string? accountId = null)
    {
        try
        {
            if (!string.IsNullOrEmpty(accountId))
            {
                var response = await _container.ReadItemAsync<Transaction>(id, new PartitionKey(accountId));
                return response.Resource;
            }

            // Cross-partition query when accountId is unknown
            var query = new QueryDefinition("SELECT * FROM c WHERE c.id = @id")
                .WithParameter("@id", id);
            var iterator = _container.GetItemQueryIterator<Transaction>(query);
            var results = await iterator.ReadNextAsync();
            return results.FirstOrDefault();
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<IEnumerable<Transaction>> GetAccountTransactionsAsync(string accountId, int limit = 50)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.AccountId = @accountId ORDER BY c.Timestamp DESC")
            .WithParameter("@accountId", accountId);
        
        var iterator = _container.GetItemQueryIterator<Transaction>(query);
        var results = await iterator.ReadNextAsync();
        return results.Take(limit);
    }

    public async Task<IEnumerable<Transaction>> GetUserTransactionsAsync(string userId, int limit = 50)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.UserId = @userId ORDER BY c.Timestamp DESC")
            .WithParameter("@userId", userId);
        
        var iterator = _container.GetItemQueryIterator<Transaction>(query);
        var results = await iterator.ReadNextAsync();
        return results.Take(limit);
    }

    private async Task PublishTransactionCreatedEvent(Transaction transaction)
    {
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
            _logger.LogError(ex, "Failed to publish TransactionCreated event to Redis for transaction {TransactionId}", transaction.Id);
        }
    }
}