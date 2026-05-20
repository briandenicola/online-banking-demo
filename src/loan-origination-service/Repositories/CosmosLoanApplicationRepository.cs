using LoanOrigination.Models;
using Microsoft.Azure.Cosmos;
using System.Net;

namespace LoanOrigination.Repositories;

public interface ILoanApplicationRepository
{
    Task<LoanApplication> CreateAsync(LoanApplication application);
    Task<LoanApplication?> GetByIdAsync(string applicationNo);
    Task<List<LoanApplication>> GetByUserIdAsync(string userId);
    Task<List<LoanApplication>> GetAllAsync(int pageSize = 50);
    Task<LoanApplication> UpdateAsync(LoanApplication application);
}

public class CosmosLoanApplicationRepository : ILoanApplicationRepository
{
    private readonly Container _container;
    private readonly ILogger<CosmosLoanApplicationRepository> _logger;

    public CosmosLoanApplicationRepository(
        CosmosClient cosmosClient,
        IConfiguration configuration,
        ILogger<CosmosLoanApplicationRepository> logger)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"] ?? "BankingDemo";
        var containerName = "loan-applications";
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _logger = logger;
    }

    public async Task<LoanApplication> CreateAsync(LoanApplication application)
    {
        application.CreatedAt = DateTime.UtcNow;
        application.UpdatedAt = DateTime.UtcNow;
        
        var response = await _container.CreateItemAsync(
            application,
            new PartitionKey(application.ApplicationNo));
        
        _logger.LogInformation("Created loan application {ApplicationNo} for user {UserId}",
            application.ApplicationNo, application.UserId);
        
        return response.Resource;
    }

    public async Task<LoanApplication?> GetByIdAsync(string applicationNo)
    {
        try
        {
            var response = await _container.ReadItemAsync<LoanApplication>(
                applicationNo,
                new PartitionKey(applicationNo));
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<List<LoanApplication>> GetByUserIdAsync(string userId)
    {
        var query = new QueryDefinition(
            "SELECT * FROM c WHERE c.userId = @userId ORDER BY c.applicationDate DESC")
            .WithParameter("@userId", userId);

        var results = new List<LoanApplication>();
        var iterator = _container.GetItemQueryIterator<LoanApplication>(query);
        
        while (iterator.HasMoreResults)
        {
            var page = await iterator.ReadNextAsync();
            results.AddRange(page);
        }
        
        return results;
    }

    public async Task<List<LoanApplication>> GetAllAsync(int pageSize = 50)
    {
        var query = new QueryDefinition(
            "SELECT * FROM c ORDER BY c.applicationDate DESC");

        var results = new List<LoanApplication>();
        var queryOptions = new QueryRequestOptions { MaxItemCount = pageSize };
        var iterator = _container.GetItemQueryIterator<LoanApplication>(query, requestOptions: queryOptions);
        
        while (iterator.HasMoreResults)
        {
            var page = await iterator.ReadNextAsync();
            results.AddRange(page);
            // Only fetch first page for admin list
            break;
        }
        
        return results;
    }

    public async Task<LoanApplication> UpdateAsync(LoanApplication application)
    {
        application.UpdatedAt = DateTime.UtcNow;
        
        var response = await _container.ReplaceItemAsync(
            application,
            application.ApplicationNo,
            new PartitionKey(application.ApplicationNo));
        
        _logger.LogInformation("Updated loan application {ApplicationNo}, status={Status}",
            application.ApplicationNo, application.Status);
        
        return response.Resource;
    }
}
