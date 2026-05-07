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
    private const string StreamName = "banking-events";

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
        var transfer = new Transfer
        {
            FromAccountNumber = request.FromAccountNumber,
            ToAccountNumber = request.ToAccountNumber,
            Amount = request.Amount,
            Description = request.Description,
            Status = "Processing"
        };

        try
        {
            var fromAccount = await GetAccountInfoAsync(request.FromAccountNumber);
            var toAccount = await GetAccountInfoAsync(request.ToAccountNumber);

            if (fromAccount == null)
            {
                transfer.Status = "Failed";
                transfer.FailureReason = "From account not found";
                _transfers[transfer.Id] = transfer;
                return transfer;
            }

            if (toAccount == null)
            {
                transfer.Status = "Failed";
                transfer.FailureReason = "To account not found";
                _transfers[transfer.Id] = transfer;
                return transfer;
            }

            transfer.FromAccountId = fromAccount.Value.Id;
            transfer.ToAccountId = toAccount.Value.Id;

            if (fromAccount.Value.Balance < request.Amount)
            {
                transfer.Status = "Failed";
                transfer.FailureReason = "Insufficient funds";
                _transfers[transfer.Id] = transfer;
                return transfer;
            }

            // Create debit and credit transactions (balance updates handled by transaction-service)
            await CreateTransferTransactionsAsync(
                fromAccount.Value.Id, toAccount.Value.Id,
                request.Amount, transfer.Id, request.Description);

            transfer.Status = "Completed";
            transfer.CompletedAt = DateTime.UtcNow;
            _transfers[transfer.Id] = transfer;

            // Publish TransferInitiated event to Redis Stream
            await PublishTransferEventAsync(transfer);

            return transfer;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Transfer failed: {TransferId}", transfer.Id);
            transfer.Status = "Failed";
            transfer.FailureReason = ex.Message;
            _transfers[transfer.Id] = transfer;
            return transfer;
        }
    }

    public Task<Transfer?> GetTransferByIdAsync(string id)
    {
        _transfers.TryGetValue(id, out var transfer);
        return Task.FromResult(transfer);
    }

    private async Task<(string Id, string AccountNumber, decimal Balance)?> GetAccountInfoAsync(string accountNumber)
    {
        var accountServiceUrl = _configuration["Services:AccountService"];
        var client = CreateAuthenticatedClient();
        var response = await client.GetAsync($"{accountServiceUrl}/api/accounts/number/{accountNumber}");
        if (!response.IsSuccessStatusCode)
            return null;

        var json = await response.Content.ReadAsStringAsync();
        var account = System.Text.Json.JsonSerializer.Deserialize<AccountInfo>(json, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        });

        return (account!.Id, account.AccountNumber, account.Balance);
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
            Type = "Transfer",
            Description = description ?? $"Transfer to account",
            Category = "Transfer",
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
            Type = "Transfer",
            Description = description ?? $"Transfer from account",
            Category = "Transfer",
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
            _logger.LogError(ex, "Failed to publish event to Redis for transfer {TransferId}", transfer.Id);
        }
    }

    private class AccountInfo
    {
        public string Id { get; set; } = null!;
        public string AccountNumber { get; set; } = null!;
        public decimal Balance { get; set; }
    }
}