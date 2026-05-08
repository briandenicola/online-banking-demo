using System;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using OnlineBankingDemo.Contracts.Events;
using StackExchange.Redis;
using UserModel = UserService.Models.User;
using BC = global::BCrypt.Net.BCrypt;

namespace UserService.Services;

public class UserService : IUserService
{
    private readonly Container _container;
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<UserService> _logger;
    private readonly IConfiguration _configuration;

    public UserService(
        CosmosClient cosmosClient,
        IConnectionMultiplexer redis,
        ILogger<UserService> logger,
        IConfiguration configuration)
    {
        var databaseName = configuration["CosmosDb:DatabaseName"];
        var containerName = configuration["CosmosDb:ContainerName"];
        _container = cosmosClient.GetContainer(databaseName, containerName);
        _redis = redis;
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
        
        await PublishUserRegisteredEvent(user);

        return response;
    }

    public async Task<bool> ValidateCredentialsAsync(string username, string password)
    {
        var user = await GetUserByUsernameAsync(username);
        if (user == null)
            return false;

        return BC.Verify(password, user.PasswordHash);
    }

    public async Task<bool> ChangePasswordAsync(string userId, string currentPassword, string newPassword)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) return false;

        if (!BC.Verify(currentPassword, user.PasswordHash))
            return false;

        user.PasswordHash = BC.HashPassword(newPassword);
        await _container.ReplaceItemAsync(user, user.Id, new PartitionKey(user.Id));
        _logger.LogInformation("Password changed for user {UserId}", userId);
        return true;
    }

    public async Task<string?> GetAvatarAsync(string userId)
    {
        var user = await GetUserByIdAsync(userId);
        return user?.AvatarBase64;
    }

    public async Task SetAvatarAsync(string userId, string avatarBase64)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) throw new InvalidOperationException("User not found");

        user.AvatarBase64 = avatarBase64;
        await _container.ReplaceItemAsync(user, user.Id, new PartitionKey(user.Id));
        _logger.LogInformation("Avatar updated for user {UserId}", userId);
    }

    public async Task<List<string>> GetCategoryPreferencesAsync(string userId)
    {
        var user = await GetUserByIdAsync(userId);
        return user?.CategoryPreferences ?? new List<string>();
    }

    public async Task SetCategoryPreferencesAsync(string userId, List<string> categories)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) throw new InvalidOperationException("User not found");

        user.CategoryPreferences = categories;
        await _container.ReplaceItemAsync(user, user.Id, new PartitionKey(user.Id));
        _logger.LogInformation("Category preferences updated for user {UserId}: {Count} categories", userId, categories.Count);
    }

    private async Task PublishUserRegisteredEvent(UserModel user)
    {
        try
        {
            var evt = new UserRegisteredEvent
            {
                UserId = user.Id,
                Username = user.Username,
                Email = user.Email
            };

            var payload = JsonConvert.SerializeObject(new
            {
                eventType = "UserRegistered",
                timestamp = DateTime.UtcNow.ToString("o"),
                data = evt
            });

            var db = _redis.GetDatabase();
            await db.StreamAddAsync("banking-events", new NameValueEntry[]
            {
                new("payload", payload)
            });
            _logger.LogInformation("Published UserRegistered event to Redis Stream for user {UserId}", user.Id);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to publish UserRegistered event — non-critical");
        }
    }
}