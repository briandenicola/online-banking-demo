using Microsoft.Azure.Cosmos;
using PromptEvalService.Models;

namespace PromptEvalService.Repositories;

public class CosmosEvaluationRunRepository : IEvaluationRunRepository
{
    private readonly Container _container;

    private static readonly PartitionKey GlobalPartition = new("global");

    public CosmosEvaluationRunRepository(CosmosClient cosmosClient, IConfiguration config)
    {
        var dbName = config["CosmosDb:DatabaseName"] ?? "BankingDemo";
        var containerName = config["CosmosDb:RunsContainerName"] ?? "EvaluationRuns";
        _container = cosmosClient.GetContainer(dbName, containerName);
    }

    public async Task<EvaluationRun?> GetByIdAsync(string id)
    {
        try
        {
            var response = await _container.ReadItemAsync<EvaluationRun>(id, GlobalPartition);
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<List<EvaluationRun>> GetAllAsync(string? templateId = null)
    {
        var queryText = "SELECT * FROM c WHERE c.userId = 'global' OR c.UserId = 'global'";
        if (!string.IsNullOrEmpty(templateId))
            queryText += " AND (c.templateId = @templateId OR c.TemplateId = @templateId)";
        queryText += " ORDER BY c.createdAt DESC, c.CreatedAt DESC";

        var queryDef = new QueryDefinition(queryText);
        if (!string.IsNullOrEmpty(templateId))
            queryDef.WithParameter("@templateId", templateId);

        var allRuns = new List<EvaluationRun>();
        using var iterator = _container.GetItemQueryIterator<EvaluationRun>(queryDef);
        while (iterator.HasMoreResults)
        {
            var response = await iterator.ReadNextAsync();
            allRuns.AddRange(response);
        }

        return allRuns;
    }

    public async Task<EvaluationRun> CreateAsync(EvaluationRun run)
    {
        var response = await _container.CreateItemAsync(run, GlobalPartition);
        return response.Resource;
    }

    public async Task<EvaluationRun> ReplaceAsync(string id, EvaluationRun run)
    {
        var response = await _container.ReplaceItemAsync(run, id, GlobalPartition);
        return response.Resource;
    }
}
