using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;

namespace TransactionService.Repositories;

public class CosmosAccountBalanceRepository : IAccountBalanceRepository
{
    private readonly Container _accountsContainer;
    private readonly ILogger<CosmosAccountBalanceRepository> _logger;

    public CosmosAccountBalanceRepository(
        CosmosClient cosmosClient,
        IConfiguration configuration,
        ILogger<CosmosAccountBalanceRepository> logger)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var accountsContainerName = configuration["CosmosDb:AccountsContainerName"];
        _accountsContainer = cosmosClient.GetContainer(databaseName, accountsContainerName);
        _logger = logger;
    }

    public async Task<(decimal Balance, string AccountId)> GetBalanceAsync(string accountId)
    {
        var response = await _accountsContainer.ReadItemAsync<AccountRecord>(accountId, new PartitionKey(accountId));
        var account = response.Resource;
        return (account.Balance, account.Id);
    }

    public async Task UpdateBalanceAsync(string accountId, decimal amount)
    {
        var response = await _accountsContainer.ReadItemAsync<AccountRecord>(accountId, new PartitionKey(accountId));
        var account = response.Resource;

        account.Balance += amount;

        await _accountsContainer.ReplaceItemAsync(account, accountId, new PartitionKey(accountId));
        _logger.LogInformation("Updated account {AccountId} balance by {Amount}", accountId, amount);
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
