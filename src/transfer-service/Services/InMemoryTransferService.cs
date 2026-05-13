using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using StackExchange.Redis;
using TransferService.Models;

namespace TransferService.Services;

public class InMemoryTransferService : ITransferService
{
    private readonly ConcurrentDictionary<string, Transfer> _transfers = new();
    private readonly IConnectionMultiplexer _redis;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private readonly IConfiguration _configuration;
    private readonly ILogger<InMemoryTransferService> _logger;
    private const string StreamName = global::TransferService.Constants.DefaultStreamName;

    public InMemoryTransferService(
        IConnectionMultiplexer redis,
        IHttpClientFactory httpClientFactory,
        IHttpContextAccessor httpContextAccessor,
        IConfiguration configuration,
        ILogger<InMemoryTransferService> logger)
    {
        _redis = redis;
        _httpClientFactory = httpClientFactory;
        _httpContextAccessor = httpContextAccessor;
        _configuration = configuration;
        _logger = logger;
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
            UserId = userId,
            FromAccountId = request.FromAccountId,
            ToAccountId = request.ToAccountId,
            FromAccountNumber = request.FromAccountNumber,
            ToAccountNumber = request.ToAccountNumber,
            Amount = request.Amount,
            Description = request.Description,
            Status = global::TransferService.Constants.TransferStatuses.Processing
        };

        try
        {
            // Create debit and credit transactions (balance updates handled by transaction-service)
            await CreateTransferTransactionsAsync(
                request.FromAccountId, request.ToAccountId,
                request.Amount, transfer.Id, request.Description);

            transfer.Status = global::TransferService.Constants.TransferStatuses.Completed;
            transfer.CompletedAt = DateTime.UtcNow;
            _transfers[transfer.Id] = transfer;

            // Publish TransferInitiated event to Redis Stream
            await PublishTransferEventAsync(transfer);

            return transfer;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Transfer failed: {TransferId}", transfer.Id);
            transfer.Status = global::TransferService.Constants.TransferStatuses.Failed;
            transfer.FailureReason = global::TransferService.Constants.FailureReasons.Generic;
            _transfers[transfer.Id] = transfer;
            return transfer;
        }
    }

    public Task<Transfer?> GetTransferByIdAsync(string id)
    {
        _transfers.TryGetValue(id, out var transfer);
        return Task.FromResult(transfer);
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

    private async Task CreateTransferTransactionsAsync(
        string fromAccountId, string toAccountId, decimal amount, string transferId, string? description)
    {
        var transactionServiceUrl = _configuration["Services:TransactionService"];
        var client = CreateAuthenticatedClient();

        var debitRequest = new CreateTransactionRequest
        {
            AccountId = fromAccountId,
            Amount = -amount,
            Type = global::TransferService.Constants.TransactionTypes.Transfer,
            Description = description ?? $"Transfer to account",
            Category = global::TransferService.Constants.Categories.Transfer,
            RelatedTransactionId = transferId
        };

        var debitResponse = await client.PostAsync(
            $"{transactionServiceUrl}/api/transactions",
            new StringContent(JsonConvert.SerializeObject(debitRequest), Encoding.UTF8, "application/json"));
        if (!debitResponse.IsSuccessStatusCode)
            throw new InvalidOperationException($"Failed to create debit transaction: {debitResponse.StatusCode}");

        var creditRequest = new CreateTransactionRequest
        {
            AccountId = toAccountId,
            Amount = amount,
            Type = global::TransferService.Constants.TransactionTypes.Transfer,
            Description = description ?? $"Transfer from account",
            Category = global::TransferService.Constants.Categories.Transfer,
            RelatedTransactionId = transferId
        };

        var creditResponse = await client.PostAsync(
            $"{transactionServiceUrl}/api/transactions",
            new StringContent(JsonConvert.SerializeObject(creditRequest), Encoding.UTF8, "application/json"));
        if (!creditResponse.IsSuccessStatusCode)
            throw new InvalidOperationException($"Failed to create credit transaction: {creditResponse.StatusCode}");
    }

    private async Task PublishTransferEventAsync(Transfer transfer)
    {
        try
        {
            var eventPayload = new
            {
                eventType = global::TransferService.Constants.EventTypes.TransferInitiated,
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
            _logger.LogError(ex, "Failed to publish event to Redis for transfer {TransferId}", transfer.Id);
        }
    }

}