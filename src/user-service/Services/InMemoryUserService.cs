using System;
using System.Collections.Concurrent;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using OnlineBankingDemo.Contracts.Dtos;
using UserService.Models;

namespace UserService.Services;

public class InMemoryUserService : IUserService
{
    private readonly ConcurrentDictionary<string, User> _users = new();
    private readonly ILogger<InMemoryUserService> _logger;

    public InMemoryUserService(ILogger<InMemoryUserService> logger)
    {
        _logger = logger;
        // Seed a default test user for demo purposes
        var salt = GenerateSalt();
        var passwordHash = HashPassword("password123", salt);
        var defaultUser = new User
        {
            Id = "1",
            Username = "testuser",
            Email = "test@example.com",
            FirstName = "Test",
            LastName = "User",
            PasswordHash = passwordHash,
            Salt = salt
        };
        _users[defaultUser.Id] = defaultUser;

        // Seed a demo user
        var demoSalt = GenerateSalt();
        var demoPasswordHash = HashPassword("password123", demoSalt);
        var demoUser = new User
        {
            Id = "2",
            Username = "demo@banking-demo.com",
            Email = "demo@banking-demo.com",
            FirstName = "Demo",
            LastName = "User",
            PasswordHash = demoPasswordHash,
            Salt = demoSalt
        };
        _users[demoUser.Id] = demoUser;
    }

    public Task<User?> GetUserByIdAsync(string id)
    {
        _users.TryGetValue(id, out var user);
        return Task.FromResult(user);
    }

    public Task<User?> GetUserByUsernameAsync(string username)
    {
        var user = _users.Values.FirstOrDefault(u => u.Username.Equals(username, StringComparison.OrdinalIgnoreCase));
        return Task.FromResult(user);
    }

    public async Task<User> CreateUserAsync(RegisterUserRequest request)
    {
        var existingUser = await GetUserByUsernameAsync(request.Username);
        if (existingUser != null)
        {
            throw new InvalidOperationException("Username already exists");
        }

        var salt = GenerateSalt();
        var passwordHash = HashPassword(request.Password, salt);

        var user = new User
        {
            Id = Guid.NewGuid().ToString(),
            Username = request.Username,
            Email = request.Email,
            FirstName = request.FirstName,
            LastName = request.LastName,
            PasswordHash = passwordHash,
            Salt = salt
        };

        _users[user.Id] = user;
        _logger.LogInformation("Created user {UserId}", user.Id);
        
        return await Task.FromResult(user);
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
}