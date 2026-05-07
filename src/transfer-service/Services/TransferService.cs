using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
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
    private readonly HttpClient _httpClient;
    private const string StreamName = "banking-events";

    public TransferService(
        CosmosClient cosmosClient,
        IConnectionMultiplexer redis,
        ILogger<TransferService> logger,
        IConfiguration configuration,
        HttpClient httpClient)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _redis = redis;
        _logger = logger;
        _configuration = configuration;
        _httpClient = httpClient;
    }

    public async Task<Transfer> InitiateTransferAsync(string userId, CreateTransferRequest request)
    {
        var transfer = new Transfer
        {
            Id = Guid.NewGuid().ToString(),
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

            if (fromAccount == null || fromAccount.Value.Id == null)
            {
                transfer.Status = "Failed";
                transfer.FailureReason = "From account not found";
                await _container.CreateItemAsync(transfer, new PartitionKey(transfer.Id));
                return transfer;
            }

            if (toAccount == null || toAccount.Value.Id == null)
            {
                transfer.Status = "Failed";
                transfer.FailureReason = "To account not found";
                await _container.CreateItemAsync(transfer, new PartitionKey(transfer.Id));
                return transfer;
            }

            transfer.FromAccountId = fromAccount.Value.Id;
            transfer.ToAccountId = toAccount.Value.Id;

            if (fromAccount.Value.Balance < request.Amount)
            {
                transfer.Status = "Failed";
                transfer.FailureReason = "Insufficient funds";
                await _container.CreateItemAsync(transfer, new PartitionKey(transfer.Id));
                return transfer;
            }

            await CreateTransferTransactionsAsync(fromAccount.Value.Id, toAccount.Value.Id, request.Amount, transfer.Id, request.Description);

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

    private async Task<(string Id, string AccountNumber, decimal Balance)?> GetAccountInfoAsync(string accountNumber)
    {
        var response = await _httpClient.GetAsync($"{_configuration["Services:AccountService"]}/api/accounts/number/{accountNumber}");
        if (!response.IsSuccessStatusCode)
            return null;

        var json = await response.Content.ReadAsStringAsync();
        var account = System.Text.Json.JsonSerializer.Deserialize<AccountInfo>(json, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        });

        return (account!.Id, account.AccountNumber, account.Balance);
    }

    private async Task CreateTransferTransactionsAsync(string fromAccountId, string toAccountId, decimal amount, string transferId, string? description)
    {
        var createTransactionRequest = new CreateTransactionRequest
        {
            AccountId = fromAccountId,
            Amount = -amount,
            Type = "Transfer",
            Description = description ?? $"Transfer to account ending in {toAccountId[^4..]}",
            Category = "Transfer",
            RelatedTransactionId = transferId
        };

        var debitResponse = await _httpClient.PostAsync(
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

        var creditResponse = await _httpClient.PostAsync(
            $"{_configuration["Services:TransactionService"]}/api/transactions",
            new StringContent(JsonConvert.SerializeObject(createTransactionRequest), Encoding.UTF8, "application/json"));
        if (!creditResponse.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"Failed to create credit transaction: {creditResponse.StatusCode}");
        }

        var accountServiceUrl = _configuration["Services:AccountService"];

        var debitBalanceResponse = await _httpClient.PostAsync(
            $"{accountServiceUrl}/api/accounts/{fromAccountId}/balance",
            new StringContent(JsonConvert.SerializeObject(new { amount = -amount }), Encoding.UTF8, "application/json"));
        if (!debitBalanceResponse.IsSuccessStatusCode)
        {
            _logger.LogError("Failed to debit source account {AccountId}. Transfer {TransferId} may be inconsistent.", fromAccountId, transferId);
            throw new InvalidOperationException($"Failed to debit source account: {debitBalanceResponse.StatusCode}");
        }

        var creditBalanceResponse = await _httpClient.PostAsync(
            $"{accountServiceUrl}/api/accounts/{toAccountId}/balance",
            new StringContent(JsonConvert.SerializeObject(new { amount = amount }), Encoding.UTF8, "application/json"));
        if (!creditBalanceResponse.IsSuccessStatusCode)
        {
            _logger.LogError("Failed to credit destination account {AccountId}. Reversing debit on {FromAccountId}.", toAccountId, fromAccountId);
            await _httpClient.PostAsync(
                $"{accountServiceUrl}/api/accounts/{fromAccountId}/balance",
                new StringContent(JsonConvert.SerializeObject(new { amount = amount }), Encoding.UTF8, "application/json"));
            throw new InvalidOperationException($"Failed to credit destination account: {creditBalanceResponse.StatusCode}");
        }
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

    private class AccountInfo
    {
        public string Id { get; set; } = null!;
        public string AccountNumber { get; set; } = null!;
        public decimal Balance { get; set; }
    }
}