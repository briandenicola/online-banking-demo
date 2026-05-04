using System;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Azure.Messaging.EventHubs.Producer;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using OnlineBankingDemo.Contracts.Events;
using UserModel = UserService.Models.User;

namespace UserService.Services;

public class UserService : IUserService
{
    private readonly Container _container;
    private readonly EventHubProducerClient _eventHubProducer;
    private readonly ILogger<UserService> _logger;
    private readonly IConfiguration _configuration;

    public UserService(
        CosmosClient cosmosClient,
        EventHubProducerClient eventHubProducer,
        ILogger<UserService> logger,
        IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _eventHubProducer = eventHubProducer;
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

    public async Task<UserModel> CreateUserAsync(RegisterUserRequest request)
    {
        var existingUser = await GetUserByUsernameAsync(request.Username);
        if (existingUser != null)
        {
            throw new InvalidOperationException("Username already exists");
        }

        var salt = GenerateSalt();
        var passwordHash = HashPassword(request.Password, salt);

        var user = new UserModel
        {
            Id = Guid.NewGuid().ToString(),
            Username = request.Username,
            Email = request.Email,
            FirstName = request.FirstName,
            LastName = request.LastName,
            PasswordHash = passwordHash,
            Salt = salt
        };

        var response = await _container.CreateItemAsync(user, new PartitionKey(user.Id));
        
        // Publish UserRegistered event
        await PublishUserRegisteredEvent(user);

        return response;
    }

    public async Task<bool> ValidateCredentialsAsync(string username, string password)
    {
        var user = await GetUserByUsernameAsync(username);
        if (user == null)
            return false;

        var hash = HashPassword(password, user.Salt);
        return hash == user.PasswordHash;
    }

    private string GenerateSalt()
    {
        var bytes = new byte[32];
        using var rng = RandomNumberGenerator.Create();
        rng.GetBytes(bytes);
        return Convert.ToBase64String(bytes);
    }

    private string HashPassword(string password, string salt)
    {
        using var sha256 = SHA256.Create();
        var saltedPassword = $"{salt}{password}";
        var hash = sha256.ComputeHash(Encoding.UTF8.GetBytes(saltedPassword));
        return Convert.ToBase64String(hash);
    }

    private async Task PublishUserRegisteredEvent(UserModel user)
    {
        var evt = new UserRegisteredEvent
        {
            UserId = user.Id,
            Username = user.Username,
            Email = user.Email
        };

        var eventData = new Azure.Messaging.EventHubs.EventData(
            Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(evt)));
        
        await _eventHubProducer.SendAsync(new[] { eventData });
        _logger.LogInformation("Published UserRegistered event for user {UserId}", user.Id);
    }
}