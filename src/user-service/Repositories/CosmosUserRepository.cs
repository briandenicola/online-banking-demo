using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using UserModel = UserService.Models.User;

namespace UserService.Repositories;

public class CosmosUserRepository : IUserRepository
{
    private readonly Container _container;

    public CosmosUserRepository(CosmosClient cosmosClient, IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
    }

    public async Task<Models.User?> GetByIdAsync(string id)
    {
        try
        {
            var response = await _container.ReadItemAsync<UserModel>(id, new PartitionKey(id));
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<Models.User?> GetByUsernameAsync(string username)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.Username = @username")
            .WithParameter("@username", username);

        var iterator = _container.GetItemQueryIterator<UserModel>(query);
        var results = await iterator.ReadNextAsync();
        return results.FirstOrDefault();
    }

    public async Task<Models.User?> GetByEmailAsync(string email)
    {
        var normalizedEmail = email.ToLowerInvariant();
        var query = new QueryDefinition("SELECT * FROM c WHERE LOWER(c.Email) = @email")
            .WithParameter("@email", normalizedEmail);

        var iterator = _container.GetItemQueryIterator<UserModel>(query);
        var results = await iterator.ReadNextAsync();
        return results.FirstOrDefault();
    }

    public async Task<Models.User> CreateAsync(Models.User user)
    {
        var response = await _container.CreateItemAsync(user, new PartitionKey(user.Id));
        return response.Resource;
    }

    public async Task<Models.User> ReplaceAsync(Models.User user)
    {
        var response = await _container.ReplaceItemAsync(user, user.Id, new PartitionKey(user.Id));
        return response.Resource;
    }

    public async Task<bool> DeleteAsync(string id)
    {
        try
        {
            await _container.DeleteItemAsync<UserModel>(id, new PartitionKey(id));
            return true;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return false;
        }
    }

    public async Task<bool> IsContainerEmptyAsync()
    {
        var query = new QueryDefinition("SELECT VALUE COUNT(1) FROM c WHERE NOT STARTSWITH(c.id, 'email-lookup:')");
        var iterator = _container.GetItemQueryIterator<int>(query);
        var response = await iterator.ReadNextAsync();
        return response.FirstOrDefault() == 0;
    }

    public async Task<int> GetAdminCountAsync()
    {
        var query = new QueryDefinition("SELECT VALUE COUNT(1) FROM c WHERE c.Role = 'admin'");
        var iterator = _container.GetItemQueryIterator<int>(query);
        var response = await iterator.ReadNextAsync();
        return response.FirstOrDefault();
    }

    public async Task<List<Models.User>> GetAllUsersAsync()
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE NOT STARTSWITH(c.id, 'email-lookup:') ORDER BY c.CreatedAt DESC");
        var iterator = _container.GetItemQueryIterator<UserModel>(query);
        var users = new List<Models.User>();

        while (iterator.HasMoreResults)
        {
            var response = await iterator.ReadNextAsync();
            users.AddRange(response);
        }

        return users;
    }

    public async Task CreateEmailLookupAsync(string emailLookupId, object emailLookupDoc)
    {
        await _container.CreateItemAsync(emailLookupDoc, new PartitionKey(emailLookupId));
    }

    public async Task DeleteEmailLookupAsync(string emailLookupId)
    {
        try
        {
            await _container.DeleteItemAsync<object>(emailLookupId, new PartitionKey(emailLookupId));
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            // Lookup doc may not exist for users created before this feature
        }
    }
}
