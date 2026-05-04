using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AccountService.Models;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using OnlineBankingDemo.Contracts.Dtos;
using OnlineBankingDemo.Contracts.Events;

namespace AccountService.Services;

public class AccountService : IAccountService
{
    private readonly Container _container;
    private readonly ILogger<AccountService> _logger;
    private readonly IConfiguration _configuration;

    public AccountService(
        CosmosClient cosmosClient,
        ILogger<AccountService> logger,
        IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _logger = logger;
        _configuration = configuration;
    }

    public async Task<Account> CreateAccountAsync(string userId, CreateAccountRequest request)
    {
        var account = new Account
        {
            Id = Guid.NewGuid().ToString(),
            UserId = userId,
            AccountNumber = GenerateAccountNumber(),
            AccountType = request.AccountType,
            Balance = request.InitialBalance,
            Currency = request.Currency ?? "USD"
        };

        await _container.CreateItemAsync(account, new PartitionKey(account.Id));
        _logger.LogInformation("Created account {AccountId} for user {UserId}", account.Id, userId);
        return account;
    }

    public async Task<Account?> GetAccountByIdAsync(string id)
    {
        try
        {
            var response = await _container.ReadItemAsync<Account>(id, new PartitionKey(id));
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<IEnumerable<Account>> GetUserAccountsAsync(string userId)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.UserId = @userId")
            .WithParameter("@userId", userId);
        
        var iterator = _container.GetItemQueryIterator<Account>(query);
        var results = await iterator.ReadNextAsync();
        return results.ToList();
    }

    public async Task<Account?> GetAccountByNumberAsync(string accountNumber)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.AccountNumber = @accountNumber")
            .WithParameter("@accountNumber", accountNumber);
        
        var iterator = _container.GetItemQueryIterator<Account>(query);
        var results = await iterator.ReadNextAsync();
        return results.FirstOrDefault();
    }

    public async Task<Account> UpdateBalanceAsync(string accountId, decimal amount)
    {
        var account = await GetAccountByIdAsync(accountId);
        if (account == null)
            throw new InvalidOperationException("Account not found");

        account.Balance += amount;
        var response = await _container.UpsertItemAsync(account, new PartitionKey(account.Id));
        return response.Resource;
    }

    private string GenerateAccountNumber()
    {
        var random = new Random();
        return $"ACC{random.Next(10000000, 99999999)}";
    }
}