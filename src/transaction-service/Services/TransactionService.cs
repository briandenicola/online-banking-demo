using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Azure.Messaging.EventHubs.Producer;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using TransactionService.Models;

namespace TransactionService.Services;

public class TransactionService : ITransactionService
{
    private readonly Container _container;
    private readonly EventHubProducerClient _eventHubProducer;
    private readonly ILogger<TransactionService> _logger;
    private readonly IConfiguration _configuration;

    public TransactionService(
        CosmosClient cosmosClient,
        EventHubProducerClient eventHubProducer,
        ILogger<TransactionService> logger,
        IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _eventHubProducer = eventHubProducer;
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
        
        // Publish TransactionCreated event (with categorization flag)
        await PublishTransactionCreatedEvent(transaction, request.AutoCategorize);

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
        // Filter by userId to return only this user's transactions
        var query = new QueryDefinition("SELECT * FROM c WHERE c.UserId = @userId ORDER BY c.Timestamp DESC")
            .WithParameter("@userId", userId);
        
        var iterator = _container.GetItemQueryIterator<Transaction>(query);
        var results = await iterator.ReadNextAsync();
        return results.Take(limit);
    }

    private async Task PublishTransactionCreatedEvent(Transaction transaction, bool needsCategorization = false)
    {
        var evt = new OnlineBankingDemo.Contracts.Events.TransactionCreatedEvent
        {
            TransactionId = transaction.Id,
            AccountId = transaction.AccountId,
            Amount = transaction.Amount,
            Type = transaction.Type,
            Description = transaction.Description,
            Category = transaction.Category,
            NeedsCategorization = needsCategorization
        };

        var eventData = new Azure.Messaging.EventHubs.EventData(
            System.Text.Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(evt)));
        
        await _eventHubProducer.SendAsync(new[] { eventData });
        _logger.LogInformation("Published TransactionCreated event for transaction {TransactionId} (needs_categorization: {NeedsCategorization})", 
            transaction.Id, needsCategorization);
    }
}