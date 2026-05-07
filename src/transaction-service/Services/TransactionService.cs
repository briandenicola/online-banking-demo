using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
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
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private const string StreamName = "banking-events";

    public TransactionService(
        CosmosClient cosmosClient,
        IConnectionMultiplexer redis,
        ILogger<TransactionService> logger,
        IConfiguration configuration,
        IHttpClientFactory httpClientFactory,
        IHttpContextAccessor httpContextAccessor)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _redis = redis;
        _logger = logger;
        _configuration = configuration;
        _httpClientFactory = httpClientFactory;
        _httpContextAccessor = httpContextAccessor;
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
        await UpdateAccountBalanceAsync(transaction.AccountId, transaction.Amount);
        
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

    private static bool IsDebitTransaction(OnlineBankingDemo.Contracts.Dtos.CreateTransactionRequest request)
    {
        return request.Amount < 0 ||
               string.Equals(request.Type, "Debit", StringComparison.OrdinalIgnoreCase);
    }

    private async Task ValidateBalanceAsync(string accountId, decimal amount)
    {
        var accountServiceUrl = _configuration["Services:AccountService"];
        if (string.IsNullOrEmpty(accountServiceUrl))
        {
            _logger.LogWarning("AccountService URL not configured; skipping balance validation");
            return;
        }

        try
        {
            var client = _httpClientFactory.CreateClient();
            var response = await client.GetAsync($"{accountServiceUrl}/api/accounts/{accountId}");
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning("Could not fetch account {AccountId} for balance check (HTTP {StatusCode})", accountId, response.StatusCode);
                return;
            }

            var json = await response.Content.ReadAsStringAsync();
            var account = System.Text.Json.JsonSerializer.Deserialize<AccountInfo>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });

            if (account != null && account.Balance < amount)
            {
                _logger.LogWarning("Insufficient funds: account {AccountId} balance {Balance} < requested {Amount}",
                    accountId, account.Balance, amount);

                // Publish anomaly event for insufficient funds attempt
                await PublishInsufficientFundsEvent(accountId, account.Balance, amount);

                throw new InsufficientFundsException(accountId, account.Balance, amount);
            }
        }
        catch (InsufficientFundsException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Balance validation failed for account {AccountId}; allowing transaction to proceed", accountId);
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
        var accountServiceUrl = _configuration["Services:AccountService"];
        if (string.IsNullOrEmpty(accountServiceUrl))
        {
            _logger.LogWarning("AccountService URL not configured; skipping balance update");
            return;
        }

        try
        {
            var client = _httpClientFactory.CreateClient();
            
            // Forward JWT token for service-to-service authentication
            var authHeader = _httpContextAccessor.HttpContext?.Request.Headers["Authorization"].FirstOrDefault();
            if (!string.IsNullOrEmpty(authHeader))
            {
                client.DefaultRequestHeaders.Authorization = AuthenticationHeaderValue.Parse(authHeader);
            }
            
            var requestBody = Newtonsoft.Json.JsonConvert.SerializeObject(new { Amount = amount });
            var content = new StringContent(requestBody, System.Text.Encoding.UTF8, "application/json");
            
            var response = await client.PostAsync($"{accountServiceUrl}/api/accounts/{accountId}/balance", content);
            if (!response.IsSuccessStatusCode)
            {
                var responseContent = await response.Content.ReadAsStringAsync();
                _logger.LogError("Failed to update account balance for {AccountId} (HTTP {StatusCode}): {Response}", 
                    accountId, response.StatusCode, responseContent);
            }
            else
            {
                _logger.LogInformation("Updated account {AccountId} balance by {Amount}", accountId, amount);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to call account-service to update balance for account {AccountId}", accountId);
        }
    }

    private class AccountInfo
    {
        public string Id { get; set; } = null!;
        public decimal Balance { get; set; }
    }
}