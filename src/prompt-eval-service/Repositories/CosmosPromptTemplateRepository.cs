using Microsoft.Azure.Cosmos;
using PromptEvalService.Models;

namespace PromptEvalService.Repositories;

public class CosmosPromptTemplateRepository : IPromptTemplateRepository
{
    private readonly Container _container;

    private static readonly PartitionKey GlobalPartition = new("global");

    public CosmosPromptTemplateRepository(CosmosClient cosmosClient, IConfiguration config)
    {
        var dbName = config["CosmosDb:DatabaseName"] ?? "BankingDemo";
        var containerName = config["CosmosDb:TemplatesContainerName"] ?? "PromptTemplates";
        _container = cosmosClient.GetContainer(dbName, containerName);
    }

    public async Task<List<PromptTemplate>> GetAllAsync()
    {
        var query = new QueryDefinition(
            "SELECT * FROM c WHERE c.userId = 'global' ORDER BY c.updatedAt DESC");

        var results = new List<PromptTemplate>();
        var queryOptions = new QueryRequestOptions { MaxItemCount = 100 };
        using var iterator = _container.GetItemQueryIterator<PromptTemplate>(query, requestOptions: queryOptions);
        while (iterator.HasMoreResults)
        {
            var response = await iterator.ReadNextAsync();
            results.AddRange(response);
        }
        return results;
    }

    public async Task<PromptTemplate?> GetByIdAsync(string id)
    {
        try
        {
            var response = await _container.ReadItemAsync<PromptTemplate>(id, GlobalPartition);
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<PromptTemplate> CreateAsync(PromptTemplate template)
    {
        var response = await _container.CreateItemAsync(template, GlobalPartition);
        return response.Resource;
    }

    public async Task<PromptTemplate> ReplaceAsync(string id, PromptTemplate template)
    {
        var response = await _container.ReplaceItemAsync(template, id, GlobalPartition);
        return response.Resource;
    }

    public async Task DeleteAsync(string id)
    {
        await _container.DeleteItemAsync<PromptTemplate>(id, GlobalPartition);
    }
}
