using System;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using OnlineBankingDemo.Contracts.Events;
using UserModel = UserService.Models.User;
using BC = global::BCrypt.Net.BCrypt;

namespace UserService.Services;

public class UserService : IUserService
{
    private readonly Container _container;
    private readonly ILogger<UserService> _logger;
    private readonly IConfiguration _configuration;

    public UserService(
        CosmosClient cosmosClient,
        ILogger<UserService> logger,
        IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _logger = logger;
        _configuration = configuration;
    }

    public async Task<UserModel?> GetUserByIdAsync(string id)
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

    public async Task<UserModel?> GetUserByUsernameAsync(string username)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.Username = @username")
            .WithParameter("@username", username);
        
        var iterator = _container.GetItemQueryIterator<UserModel>(query);
        var results = await iterator.ReadNextAsync();
        return results.FirstOrDefault();
    }

    public async Task<UserModel?> GetUserByEmailAsync(string email)
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.Email = @email")
            .WithParameter("@email", email);

        var iterator = _container.GetItemQueryIterator<UserModel>(query);
        var results = await iterator.ReadNextAsync();
        return results.FirstOrDefault();
    }

    public async Task<UserModel> CreateUserAsync(RegisterUserRequest request)
    {
        var existingUser = await GetUserByUsernameAsync(request.Username);
        if (existingUser != null)
        {
            throw new InvalidOperationException("Username already exists");
        }

        var existingEmail = await GetUserByEmailAsync(request.Email);
        if (existingEmail != null)
        {
            throw new InvalidOperationException("Email already exists");
        }

        var passwordHash = BC.HashPassword(request.Password);

        var user = new UserModel
        {
            Id = Guid.NewGuid().ToString(),
            Username = request.Username,
            Email = request.Email,
            FirstName = request.FirstName,
            LastName = request.LastName,
            PasswordHash = passwordHash,
            Salt = ""
        };

        var response = await _container.CreateItemAsync(user, new PartitionKey(user.Id));
        _logger.LogInformation("User registered: {UserId}", user.Id);

        return response;
    }

    public async Task<bool> ValidateCredentialsAsync(string username, string password)
    {
        var user = await GetUserByUsernameAsync(username);
        if (user == null)
            return false;

        return BC.Verify(password, user.PasswordHash);
    }
}