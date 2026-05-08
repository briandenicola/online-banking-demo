using Microsoft.Azure.Cosmos;
using PromptEvalService.Models;

namespace PromptEvalService.Services;

public class PromptTemplateService : IPromptTemplateService
{
    private readonly Container _container;
    private readonly ILogger<PromptTemplateService> _logger;

    public PromptTemplateService(CosmosClient cosmosClient, IConfiguration config, ILogger<PromptTemplateService> logger)
    {
        var dbName = config["CosmosDb:DatabaseName"] ?? "BankingDemo";
        var containerName = config["CosmosDb:TemplatesContainerName"] ?? "PromptTemplates";
        _container = cosmosClient.GetContainer(dbName, containerName);
        _logger = logger;
    }

    private static readonly PartitionKey GlobalPartition = new("global");

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
        template.UserId = "global";
        var response = await _container.CreateItemAsync(template, GlobalPartition);
        _logger.LogInformation("Created prompt template {Name} (v{Version}) for user {UserId}", template.Name, template.Version, template.UserId);
        return response.Resource;
    }

    public async Task<PromptTemplate> UpdateAsync(string id, UpdatePromptTemplateRequest request)
    {
        var existing = await GetByIdAsync(id)
            ?? throw new KeyNotFoundException($"Template {id} not found");

        if (request.Name != null) existing.Name = request.Name;
        if (request.Description != null) existing.Description = request.Description;
        if (request.SystemPrompt != null) existing.SystemPrompt = request.SystemPrompt;

        existing.Version++;
        existing.UpdatedAt = DateTime.UtcNow;

        var response = await _container.ReplaceItemAsync(existing, id, GlobalPartition);
        _logger.LogInformation("Updated prompt template {Name} to v{Version}", existing.Name, existing.Version);
        return response.Resource;
    }

    public async Task DeleteAsync(string id)
    {
        await _container.DeleteItemAsync<PromptTemplate>(id, GlobalPartition);
        _logger.LogInformation("Deleted prompt template {Id}", id);
    }
}
