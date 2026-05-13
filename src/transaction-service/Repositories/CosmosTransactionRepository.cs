using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using TransactionService.Models;

namespace TransactionService.Repositories;

public class CosmosTransactionRepository : ITransactionRepository
{
    private readonly Container _container;

    public CosmosTransactionRepository(CosmosClient cosmosClient, IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
    }

    public async Task<Transaction?> GetByIdAsync(string id, string? accountId = null)
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

    public async Task<IEnumerable<Transaction>> GetByAccountIdAsync(string accountId, int limit = 50)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.accountId = @accountId ORDER BY c.timestamp DESC")
            .WithParameter("@accountId", accountId);

        var iterator = _container.GetItemQueryIterator<Transaction>(query);
        var results = await iterator.ReadNextAsync();
        return results.Take(limit);
    }

    public async Task<IEnumerable<Transaction>> GetByUserIdAsync(string userId, int limit = 50)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.userId = @userId ORDER BY c.timestamp DESC")
            .WithParameter("@userId", userId);

        var iterator = _container.GetItemQueryIterator<Transaction>(query);
        var results = await iterator.ReadNextAsync();
        return results.Take(limit);
    }

    public async Task<IEnumerable<Transaction>> GetAllAsync(int limit = 10_000)
    {
        // Cross-partition scan — admin/maintenance only. Drains pages until limit
        // is hit so a single ReadNextAsync call doesn't silently truncate at ~100.
        var query = new QueryDefinition("SELECT * FROM c ORDER BY c.timestamp DESC");
        var iterator = _container.GetItemQueryIterator<Transaction>(
            query,
            requestOptions: new QueryRequestOptions { MaxItemCount = 1000 });

        var results = new List<Transaction>();
        while (iterator.HasMoreResults && results.Count < limit)
        {
            var page = await iterator.ReadNextAsync();
            foreach (var item in page)
            {
                results.Add(item);
                if (results.Count >= limit) break;
            }
        }
        return results;
    }

    public async Task<Transaction> CreateAsync(Transaction transaction)
    {
        var response = await _container.CreateItemAsync(transaction, new PartitionKey(transaction.AccountId));
        return response.Resource;
    }
}
