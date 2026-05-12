using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using OnlineBankingDemo.Contracts.Events;
using StackExchange.Redis;
using TransferService.Models;

namespace TransferService.Services;

public class TransferService : ITransferService
{
    private readonly Container _container;
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<TransferService> _logger;
    private readonly IConfiguration _configuration;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private const string StreamName = "banking-events";

    public TransferService(
        CosmosClient cosmosClient,
        IConnectionMultiplexer redis,
        ILogger<TransferService> logger,
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

    private HttpClient CreateAuthenticatedClient()
    {
        var client = _httpClientFactory.CreateClient();
        var authHeader = _httpContextAccessor.HttpContext?.Request.Headers["Authorization"].FirstOrDefault();
        if (!string.IsNullOrEmpty(authHeader))
        {
            client.DefaultRequestHeaders.TryAddWithoutValidation("Authorization", authHeader);
        }
        return client;
    }

    public async Task<Transfer> InitiateTransferAsync(string userId, CreateTransferRequest request)
    {
        // Verify the source account belongs to the authenticated user
        await VerifyAccountOwnershipAsync(request.FromAccountId, userId);

        var transfer = new Transfer
        {
            Id = Guid.NewGuid().ToString(),
            UserId = userId,
            FromAccountId = request.FromAccountId,
            ToAccountId = request.ToAccountId,
            FromAccountNumber = request.FromAccountNumber,
            ToAccountNumber = request.ToAccountNumber,
            Amount = request.Amount,
            Description = request.Description,
            Status = "Processing"
        };

        try
        {
            await CreateTransferTransactionsAsync(request.FromAccountId, request.ToAccountId, request.Amount, transfer.Id, request.Description);

            transfer.Status = "Completed";
            transfer.CompletedAt = DateTime.UtcNow;

            await _container.CreateItemAsync(transfer, new PartitionKey(transfer.Id));

            // Publish TransferInitiated event to Redis Stream
            await PublishTransferInitiatedEvent(transfer);

            return transfer;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Transfer failed: {TransferId}", transfer.Id);
            transfer.Status = "Failed";
            transfer.FailureReason = ex.Message;
            try
            {
                await _container.CreateItemAsync(transfer, new PartitionKey(transfer.Id));
            }
            catch (Exception persistEx)
            {
                _logger.LogError(persistEx, "Failed to persist failed transfer record: {TransferId}", transfer.Id);
            }
            return transfer;
        }
    }

    public async Task<Transfer?> GetTransferByIdAsync(string id)
    {
        try
        {
            var response = await _container.ReadItemAsync<Transfer>(id, new PartitionKey(id));
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }
    }



    private async Task VerifyAccountOwnershipAsync(string accountId, string userId)
    {
        var client = CreateAuthenticatedClient();
        var accountServiceUrl = _configuration["Services:AccountService"];
        if (string.IsNullOrEmpty(accountServiceUrl))
        {
            throw new InvalidOperationException("AccountService URL not configured; cannot verify account ownership");
        }

        var response = await client.GetAsync($"{accountServiceUrl}/api/accounts/{accountId}");
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"Account {accountId} not found or not accessible");
        }

        var json = await response.Content.ReadAsStringAsync();
        var account = System.Text.Json.JsonSerializer.Deserialize<AccountOwnerInfo>(json, new System.Text.Json.JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        });

        if (account == null || account.UserId != userId)
        {
            throw new InvalidOperationException($"Account {accountId} not found or not accessible");
        }
    }

    private class AccountOwnerInfo
    {
        public string Id { get; set; } = null!;
        public string UserId { get; set; } = null!;
    }



    private async Task CreateTransferTransactionsAsync(string fromAccountId, string toAccountId, decimal amount, string transferId, string? description)
    {
        var client = CreateAuthenticatedClient();
        var createTransactionRequest = new CreateTransactionRequest
        {
            AccountId = fromAccountId,
            Amount = -amount,
            Type = "Transfer",
            Description = description ?? $"Transfer to account ending in {toAccountId[^4..]}",
            Category = "Transfer",
            RelatedTransactionId = transferId
        };

        var debitResponse = await client.PostAsync(
            $"{_configuration["Services:TransactionService"]}/api/transactions",
            new StringContent(JsonConvert.SerializeObject(createTransactionRequest), Encoding.UTF8, "application/json"));
        if (!debitResponse.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"Failed to create debit transaction: {debitResponse.StatusCode}");
        }

        createTransactionRequest = new CreateTransactionRequest
        {
            AccountId = toAccountId,
            Amount = amount,
            Type = "Transfer",
            Description = description ?? $"Transfer from account ending in {fromAccountId[^4..]}",
            Category = "Transfer",
            RelatedTransactionId = transferId
        };

        var creditResponse = await client.PostAsync(
            $"{_configuration["Services:TransactionService"]}/api/transactions",
            new StringContent(JsonConvert.SerializeObject(createTransactionRequest), Encoding.UTF8, "application/json"));
        if (!creditResponse.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"Failed to create credit transaction: {creditResponse.StatusCode}");
        }
        // Balance updates are handled by transaction-service when it creates each transaction
    }

    private async Task PublishTransferInitiatedEvent(Transfer transfer)
    {
        try
        {
            var eventPayload = new
            {
                eventType = "TransferInitiated",
                timestamp = DateTime.UtcNow.ToString("o"),
                data = new
                {
                    fromAccountId = transfer.FromAccountId,
                    toAccountId = transfer.ToAccountId,
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
            _logger.LogError(ex, "Failed to publish TransferInitiated event to Redis for transfer {TransferId}", transfer.Id);
        }
    }

}