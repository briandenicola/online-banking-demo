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
        // Cosmos JSON paths are case-sensitive. Historical docs use both
        // PascalCase ("UserId") and camelCase ("userId") — Cosmos SDK v3's
        // default serializer (Newtonsoft, preserve-case) wrote PascalCase,
        // but more recent writes land as camelCase. Match both so the read
        // path is robust regardless of when the doc was created.
        var query = new QueryDefinition(
                "SELECT * FROM c WHERE c.UserId = @userId OR c.userId = @userId")
            .WithParameter("@userId", userId);

        var iterator = _container.GetItemQueryIterator<Account>(query);
        var results = new List<Account>();
        while (iterator.HasMoreResults)
        {
            var page = await iterator.ReadNextAsync();
            results.AddRange(page);
        }
        return results;
    }

    public async Task<Account?> GetByAccountNumberAsync(string accountNumber)
    {
        var query = new QueryDefinition(
                "SELECT * FROM c WHERE c.AccountNumber = @accountNumber OR c.accountNumber = @accountNumber")
            .WithParameter("@accountNumber", accountNumber);

        var iterator = _container.GetItemQueryIterator<Account>(query);
        while (iterator.HasMoreResults)
        {
            var page = await iterator.ReadNextAsync();
            var first = page.FirstOrDefault();
            if (first != null) return first;
        }
        return null;
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
