using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using TransferService.Models;

namespace TransferService.Repositories;

public class CosmosTransferRepository : ITransferRepository
{
    private readonly Container _container;

    public CosmosTransferRepository(CosmosClient cosmosClient, IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"]
            ?? throw new InvalidOperationException("Missing required configuration: CosmosDb:DatabaseName");
        var containerName = configuration["CosmosDb:ContainerName"]
            ?? throw new InvalidOperationException("Missing required configuration: CosmosDb:ContainerName");
        _container = cosmosClient.GetContainer(databaseName, containerName);
    }

    public async Task<Transfer?> GetByIdAsync(string id)
    {
        try
        {
            var response = await _container.ReadItemAsync<Transfer>(id, new PartitionKey(id));
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<Transfer> CreateAsync(Transfer transfer)
    {
        var response = await _container.CreateItemAsync(transfer, new PartitionKey(transfer.Id));
        return response.Resource;
    }
}
