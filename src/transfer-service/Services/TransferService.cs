using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Azure.Messaging.EventHubs;
using Azure.Messaging.EventHubs.Producer;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using OnlineBankingDemo.Contracts.Events;
using Polly;
using Polly.Retry;
using TransferService.Models;

namespace TransferService.Services;

public class TransferService : ITransferService
{
    private readonly Container _container;
    private readonly EventHubProducerClient _eventHubProducer;
    private readonly ILogger<TransferService> _logger;
    private readonly IConfiguration _configuration;
    private readonly HttpClient _httpClient;
    private readonly AsyncRetryPolicy _retryPolicy;

    public TransferService(
        CosmosClient cosmosClient,
        EventHubProducerClient eventHubProducer,
        ILogger<TransferService> logger,
        IConfiguration configuration,
        HttpClient httpClient)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _eventHubProducer = eventHubProducer;
        _logger = logger;
        _configuration = configuration;
        _httpClient = httpClient;
        
        _retryPolicy = Policy
            .Handle<Exception>()
            .WaitAndRetryAsync(3, retryAttempt => TimeSpan.FromSeconds(Math.Pow(2, retryAttempt)));
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
            // Get account info from account service
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

            // Check balance
            if (fromAccount.Value.Balance < request.Amount)
            {
                transfer.Status = "Failed";
                transfer.FailureReason = "Insufficient funds";
                await _container.CreateItemAsync(transfer, new PartitionKey(transfer.Id));
                return transfer;
            }

            // Process the transfer via transaction service
            await CreateTransferTransactionsAsync(fromAccount.Value.Id, toAccount.Value.Id, request.Amount, transfer.Id, request.Description);

            transfer.Status = "Completed";
            transfer.CompletedAt = DateTime.UtcNow;

            await _container.CreateItemAsync(transfer, new PartitionKey(transfer.Id));

            // Publish TransferInitiated event
            await PublishTransferInitiatedEvent(transfer);

            return transfer;
        }
        catch (Exception ex)
        {
            transfer.Status = "Failed";
            transfer.FailureReason = ex.Message;
            await _container.CreateItemAsync(transfer, new PartitionKey(transfer.Id));
            _logger.LogError(ex, "Transfer failed: {TransferId}", transfer.Id);
            throw;
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

        // Create debit transaction
        await _httpClient.PostAsync(
            $"{_configuration["Services:TransactionService"]}/api/transactions",
            new StringContent(JsonConvert.SerializeObject(createTransactionRequest), Encoding.UTF8, "application/json"));

        createTransactionRequest = new CreateTransactionRequest
        {
            AccountId = toAccountId,
            Amount = amount,
            Type = "Transfer",
            Description = description ?? $"Transfer from account ending in {fromAccountId[^4..]}",
            Category = "Transfer",
            RelatedTransactionId = transferId
        };

        // Create credit transaction
        await _httpClient.PostAsync(
            $"{_configuration["Services:TransactionService"]}/api/transactions",
            new StringContent(JsonConvert.SerializeObject(createTransactionRequest), Encoding.UTF8, "application/json"));
    }

    private async Task PublishTransferInitiatedEvent(Transfer transfer)
    {
        var evt = new TransferInitiatedEvent
        {
            TransferId = transfer.Id,
            FromAccountId = transfer.FromAccountId,
            ToAccountId = transfer.ToAccountId,
            Amount = transfer.Amount
        };

        var eventData = new EventData(
            System.Text.Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(evt)));
        
        await _eventHubProducer.SendAsync(new[] { eventData });
        _logger.LogInformation("Published TransferInitiated event for transfer {TransferId}", transfer.Id);
    }

    private class AccountInfo
    {
        public string Id { get; set; } = null!;
        public string AccountNumber { get; set; } = null!;
        public decimal Balance { get; set; }
    }
}