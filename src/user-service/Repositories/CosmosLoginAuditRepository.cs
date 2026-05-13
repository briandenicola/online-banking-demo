using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;

namespace UserService.Repositories;

public class CosmosLoginAuditRepository : ILoginAuditRepository
{
    private readonly Container _container;

    public CosmosLoginAuditRepository(CosmosClient cosmosClient, IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var auditContainerName = configuration["CosmosDb:LoginAuditContainerName"] ?? "login-audits";
        _container = cosmosClient.GetContainer(databaseName, auditContainerName);
    }

    public async Task CreateAsync(Models.LoginAudit audit)
    {
        await _container.CreateItemAsync(audit, new PartitionKey(audit.Id));
    }

    public async Task<List<Models.LoginAudit>> GetRecentAsync(int limit = 100)
    {
        var query = new QueryDefinition($"SELECT TOP {limit} * FROM c ORDER BY c.Timestamp DESC");
        var iterator = _container.GetItemQueryIterator<Models.LoginAudit>(query);
        var audits = new List<Models.LoginAudit>();

        while (iterator.HasMoreResults)
        {
            var response = await iterator.ReadNextAsync();
            audits.AddRange(response);
        }

        return audits;
    }
}
