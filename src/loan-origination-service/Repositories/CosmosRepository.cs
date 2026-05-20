using Microsoft.Azure.Cosmos;
using System.Net;

namespace LoanOrigination.Repositories;

public class CosmosRepository<T> : ICosmosRepository<T> where T : class
{
    private readonly Container _container;
    private readonly ILogger<CosmosRepository<T>> _logger;

    public CosmosRepository(CosmosClient cosmosClient, string databaseName, string containerName, ILogger<CosmosRepository<T>> logger)
    {
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _logger = logger;
    }

    public async Task<T> CreateAsync(T item, string partitionKey)
    {
        try
        {
            var response = await _container.CreateItemAsync(item, new PartitionKey(partitionKey));
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == HttpStatusCode.Conflict)
        {
            _logger.LogWarning(ex, "Item with partition key {PartitionKey} already exists", partitionKey);
            throw;
        }
    }

    public async Task<T?> GetByIdAsync(string id, string partitionKey)
    {
        try
        {
            var response = await _container.ReadItemAsync<T>(id, new PartitionKey(partitionKey));
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<List<T>> QueryAsync(string query, Dictionary<string, object> parameters, string? partitionKey = null)
    {
        var queryDefinition = new QueryDefinition(query);
        foreach (var param in parameters)
        {
            queryDefinition.WithParameter($"@{param.Key}", param.Value);
        }

        var queryRequestOptions = partitionKey != null
            ? new QueryRequestOptions { PartitionKey = new PartitionKey(partitionKey) }
            : null;

        var iterator = _container.GetItemQueryIterator<T>(queryDefinition, requestOptions: queryRequestOptions);
        var results = new List<T>();

        while (iterator.HasMoreResults)
        {
            var response = await iterator.ReadNextAsync();
            results.AddRange(response);
        }

        return results;
    }

    public async Task<T> UpsertAsync(T item, string partitionKey)
    {
        var response = await _container.UpsertItemAsync(item, new PartitionKey(partitionKey));
        return response.Resource;
    }

    public async Task DeleteAsync(string id, string partitionKey)
    {
        await _container.DeleteItemAsync<T>(id, new PartitionKey(partitionKey));
    }
}
