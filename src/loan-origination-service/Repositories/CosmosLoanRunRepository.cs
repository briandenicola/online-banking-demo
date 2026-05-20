using LoanOrigination.Models;
using Microsoft.Azure.Cosmos;
using System.Net;

namespace LoanOrigination.Repositories;

public interface ILoanRunRepository
{
    Task<LoanRun> CreateAsync(LoanRun run);
    Task<LoanRun?> GetByIdAsync(string runId, string applicationNo);
    Task<LoanRun?> GetLatestByApplicationAsync(string applicationNo);
    Task<List<LoanRun>> GetByApplicationAsync(string applicationNo);
    Task<LoanRun> UpdateAsync(LoanRun run);
}

public class CosmosLoanRunRepository : ILoanRunRepository
{
    private readonly Container _container;
    private readonly ILogger<CosmosLoanRunRepository> _logger;

    public CosmosLoanRunRepository(
        CosmosClient cosmosClient,
        IConfiguration configuration,
        ILogger<CosmosLoanRunRepository> logger)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"] ?? "BankingDemo";
        var containerName = "loan-runs";
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _logger = logger;
    }

    public async Task<LoanRun> CreateAsync(LoanRun run)
    {
        run.CreatedAt = DateTime.UtcNow;
        
        var response = await _container.CreateItemAsync(
            run,
            new PartitionKey(run.ApplicationNo));
        
        _logger.LogInformation("Created loan run {RunId} for application {ApplicationNo}",
            run.RunId, run.ApplicationNo);
        
        return response.Resource;
    }

    public async Task<LoanRun?> GetByIdAsync(string runId, string applicationNo)
    {
        try
        {
            var response = await _container.ReadItemAsync<LoanRun>(
                runId,
                new PartitionKey(applicationNo));
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<LoanRun?> GetLatestByApplicationAsync(string applicationNo)
    {
        var query = new QueryDefinition(
            "SELECT TOP 1 * FROM c WHERE c.applicationNo = @applicationNo ORDER BY c.startedAt DESC")
            .WithParameter("@applicationNo", applicationNo);

        var iterator = _container.GetItemQueryIterator<LoanRun>(
            query,
            requestOptions: new QueryRequestOptions { PartitionKey = new PartitionKey(applicationNo) });
        
        while (iterator.HasMoreResults)
        {
            var page = await iterator.ReadNextAsync();
            return page.FirstOrDefault();
        }
        
        return null;
    }

    public async Task<List<LoanRun>> GetByApplicationAsync(string applicationNo)
    {
        var query = new QueryDefinition(
            "SELECT * FROM c WHERE c.applicationNo = @applicationNo ORDER BY c.startedAt DESC")
            .WithParameter("@applicationNo", applicationNo);

        var results = new List<LoanRun>();
        var iterator = _container.GetItemQueryIterator<LoanRun>(
            query,
            requestOptions: new QueryRequestOptions { PartitionKey = new PartitionKey(applicationNo) });
        
        while (iterator.HasMoreResults)
        {
            var page = await iterator.ReadNextAsync();
            results.AddRange(page);
        }
        
        return results;
    }

    public async Task<LoanRun> UpdateAsync(LoanRun run)
    {
        var response = await _container.ReplaceItemAsync(
            run,
            run.Id,
            new PartitionKey(run.ApplicationNo));
        
        _logger.LogInformation("Updated loan run {RunId}, completed={Completed}",
            run.RunId, run.CompletedAt.HasValue);
        
        return response.Resource;
    }
}
