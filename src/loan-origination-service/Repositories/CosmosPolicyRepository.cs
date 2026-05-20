using LoanOrigination.Models;
using Microsoft.Azure.Cosmos;

namespace LoanOrigination.Repositories;

public interface ICosmosPolicyRepository
{
    Task<List<PolicyRule>> GetAllAsync();
    Task UpsertAsync(PolicyRule rule);
}

public class CosmosPolicyRepository : ICosmosPolicyRepository
{
    private readonly Container _container;
    private readonly ILogger<CosmosPolicyRepository> _logger;

    public CosmosPolicyRepository(CosmosClient cosmosClient, IConfiguration configuration, ILogger<CosmosPolicyRepository> logger)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"] ?? "BankingDemo";
        _container = cosmosClient.GetContainer(databaseName, "loan-policy");
        _logger = logger;
    }

    public async Task<List<PolicyRule>> GetAllAsync()
    {
        try
        {
            var query = "SELECT * FROM c";
            var iterator = _container.GetItemQueryIterator<PolicyRule>(query);
            var results = new List<PolicyRule>();

            while (iterator.HasMoreResults)
            {
                var response = await iterator.ReadNextAsync();
                results.AddRange(response);
            }

            _logger.LogInformation("Retrieved {Count} policy rules", results.Count);
            return results;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error retrieving policy rules");
            throw;
        }
    }

    public async Task UpsertAsync(PolicyRule rule)
    {
        try
        {
            await _container.UpsertItemAsync(rule, new PartitionKey(rule.Id));
            _logger.LogInformation("Upserted policy rule {RuleId}", rule.RuleId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error upserting policy rule {RuleId}", rule.RuleId);
            throw;
        }
    }
}
