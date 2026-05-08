using System;
using System.Collections.Concurrent;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using OnlineBankingDemo.Contracts.Dtos;
using UserService.Models;
using BC = global::BCrypt.Net.BCrypt;

namespace UserService.Services;

public class InMemoryUserService : IUserService
{
    private readonly ConcurrentDictionary<string, User> _users = new();
    private readonly ILogger<InMemoryUserService> _logger;

    public InMemoryUserService(ILogger<InMemoryUserService> logger)
    {
        _logger = logger;
        // Seed a default test user for demo purposes
        var passwordHash = BC.HashPassword("password123");
        var defaultUser = new User
        {
            Id = "1",
            Username = "testuser",
            Email = "test@example.com",
            FirstName = "Test",
            LastName = "User",
            Role = "admin",
            PasswordHash = passwordHash,
            Salt = "" // No longer needed with bcrypt
        };
        _users[defaultUser.Id] = defaultUser;

        // Seed a demo user
        var demoPasswordHash = BC.HashPassword("password123");
        var demoUser = new User
        {
            Id = "2",
            Username = "demo@banking-demo.com",
            Email = "demo@banking-demo.com",
            FirstName = "Demo",
            LastName = "User",
            Role = "admin",
            PasswordHash = demoPasswordHash,
            Salt = ""
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

    public Task<User?> GetUserByEmailAsync(string email)
    {
        var user = _users.Values.FirstOrDefault(u => u.Email.Equals(email, StringComparison.OrdinalIgnoreCase));
        return Task.FromResult(user);
    }

    public async Task<User> CreateUserAsync(RegisterUserRequest request)
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

        var user = new User
        {
            Id = Guid.NewGuid().ToString(),
            Username = request.Username,
            Email = request.Email,
            FirstName = request.FirstName,
            LastName = request.LastName,
            PasswordHash = passwordHash,
            Salt = ""
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

        return BC.Verify(password, user.PasswordHash);
    }
}