using AccountService.Models;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;

namespace AccountService.Repositories;

public class CosmosAccountRepository : IAccountRepository
{
    private readonly Container _container;

    public CosmosAccountRepository(CosmosClient cosmosClient, IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
    }

    public async Task<Account?> GetByIdAsync(string id)
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

    public async Task<IEnumerable<Account>> GetByUserIdAsync(string userId)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.UserId = @userId")
            .WithParameter("@userId", userId);

        var iterator = _container.GetItemQueryIterator<Account>(query);
        var results = await iterator.ReadNextAsync();
        return results.ToList();
    }

    public async Task<Account?> GetByAccountNumberAsync(string accountNumber)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.AccountNumber = @accountNumber")
            .WithParameter("@accountNumber", accountNumber);

        var iterator = _container.GetItemQueryIterator<Account>(query);
        var results = await iterator.ReadNextAsync();
        return results.FirstOrDefault();
    }

    public async Task<Account> CreateAsync(Account account)
    {
        var response = await _container.CreateItemAsync(account, new PartitionKey(account.Id));
        return response.Resource;
    }

    public async Task<Account> UpsertAsync(Account account)
    {
        var response = await _container.UpsertItemAsync(account, new PartitionKey(account.Id));
        return response.Resource;
    }
}
