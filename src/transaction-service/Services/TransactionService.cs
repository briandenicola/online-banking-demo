using System;
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
    private readonly Container _accountsContainer;
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<TransactionService> _logger;
    private const string StreamName = "banking-events";

    public TransactionService(
        CosmosClient cosmosClient,
        IConnectionMultiplexer redis,
        ILogger<TransactionService> logger,
        IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        var accountsContainerName = configuration["CosmosDb:AccountsContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _accountsContainer = cosmosClient.GetContainer(databaseName, accountsContainerName);
        _redis = redis;
        _logger = logger;
    }

    public async Task<Transaction> CreateTransactionAsync(OnlineBankingDemo.Contracts.Dtos.CreateTransactionRequest request, string userId)
    {
        // Check balance for debit transactions before creating
        if (IsDebitTransaction(request))
        {
            await ValidateBalanceAsync(request.AccountId, Math.Abs(request.Amount));
        }

        var transaction = new Transaction
        {
            Id = Guid.NewGuid().ToString(),
            AccountId = request.AccountId,
            UserId = userId,
            Amount = request.Amount,
            Currency = request.Currency ?? "USD",
            Type = request.Type,
            Description = request.Description,
            Category = request.Category ?? "Uncategorized",
            RelatedTransactionId = request.RelatedTransactionId
        };

        await _container.CreateItemAsync(transaction, new PartitionKey(transaction.AccountId));
        
        // Update account balance (transaction-service owns balance side effects)
        // Debit transactions decrease balance, so negate positive amounts
        var balanceChange = IsDebitTransaction(request) && transaction.Amount > 0
            ? -transaction.Amount
            : transaction.Amount;
        await UpdateAccountBalanceAsync(transaction.AccountId, balanceChange);
        
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
        var query = new QueryDefinition("SELECT * FROM c WHERE c.accountId = @accountId ORDER BY c.timestamp DESC")
            .WithParameter("@accountId", accountId);
        
        var iterator = _container.GetItemQueryIterator<Transaction>(query);
        var results = await iterator.ReadNextAsync();
        return results.Take(limit);
    }

    public async Task<IEnumerable<Transaction>> GetUserTransactionsAsync(string userId, int limit = 50)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.userId = @userId ORDER BY c.timestamp DESC")
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
                    id = transaction.Id,
                    accountId = transaction.AccountId,
                    userId = transaction.UserId,
                    amount = transaction.Amount,
                    type = transaction.Type,
                    description = transaction.Description,
                    category = transaction.Category
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

    private static bool IsDebitTransaction(OnlineBankingDemo.Contracts.Dtos.CreateTransactionRequest request)
    {
        return request.Amount < 0 ||
               string.Equals(request.Type, "Debit", StringComparison.OrdinalIgnoreCase);
    }

    private async Task ValidateBalanceAsync(string accountId, decimal amount)
    {
        try
        {
            var response = await _accountsContainer.ReadItemAsync<AccountRecord>(accountId, new PartitionKey(accountId));
            var account = response.Resource;

            if (account.Balance < amount)
            {
                _logger.LogWarning("Insufficient funds: account {AccountId} balance {Balance} < requested {Amount}",
                    accountId, account.Balance, amount);

                await PublishInsufficientFundsEvent(accountId, account.Balance, amount);

                throw new InsufficientFundsException(accountId, account.Balance, amount);
            }
        }
        catch (InsufficientFundsException)
        {
            throw;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            _logger.LogError("Account {AccountId} not found in Cosmos DB during balance validation", accountId);
            throw new InvalidOperationException($"Account {accountId} not found. Transaction cannot be processed.", ex);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Balance validation failed for account {AccountId}; rejecting transaction", accountId);
            throw new InvalidOperationException($"Unable to validate balance for account {accountId}. Transaction cannot be processed at this time.", ex);
        }
    }

    private async Task PublishInsufficientFundsEvent(string accountId, decimal balance, decimal requestedAmount)
    {
        try
        {
            var eventPayload = new
            {
                eventType = "InsufficientFundsAttempt",
                timestamp = DateTime.UtcNow.ToString("o"),
                data = new
                {
                    accountId,
                    currentBalance = balance,
                    requestedAmount,
                    type = "Debit"
                }
            };

            var db = _redis.GetDatabase();
            await db.StreamAddAsync(StreamName, new NameValueEntry[]
            {
                new("payload", JsonConvert.SerializeObject(eventPayload))
            });

            _logger.LogInformation("Published InsufficientFundsAttempt event for account {AccountId}", accountId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to publish InsufficientFundsAttempt event for account {AccountId}", accountId);
        }
    }

    private async Task UpdateAccountBalanceAsync(string accountId, decimal amount)
    {
        try
        {
            var response = await _accountsContainer.ReadItemAsync<AccountRecord>(accountId, new PartitionKey(accountId));
            var account = response.Resource;

            account.Balance += amount;

            await _accountsContainer.ReplaceItemAsync(account, accountId, new PartitionKey(accountId));
            _logger.LogInformation("Updated account {AccountId} balance by {Amount}", accountId, amount);
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            _logger.LogError("Account {AccountId} not found in Cosmos DB during balance update", accountId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to update balance for account {AccountId}", accountId);
        }
    }

    /// <summary>
    /// Lightweight account record for direct Cosmos DB balance operations.
    /// Mirrors the account-service Account model for the fields transaction-service needs.
    /// </summary>
    private class AccountRecord
    {
        [JsonProperty("id")]
        public string Id { get; set; } = null!;

        [JsonProperty("userId")]
        public string UserId { get; set; } = null!;

        [JsonProperty("accountNumber")]
        public string AccountNumber { get; set; } = null!;

        [JsonProperty("accountType")]
        public string AccountType { get; set; } = null!;

        [JsonProperty("balance")]
        public decimal Balance { get; set; }

        [JsonProperty("currency")]
        public string Currency { get; set; } = "USD";

        [JsonProperty("createdAt")]
        public DateTime CreatedAt { get; set; }

        [JsonProperty("isActive")]
        public bool IsActive { get; set; } = true;
    }
}