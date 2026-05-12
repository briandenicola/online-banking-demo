using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using OnlineBankingDemo.Contracts.Dtos;
using UserService.Models;
using BC = global::BCrypt.Net.BCrypt;

namespace UserService.Services;

public class InMemoryUserService : IUserService
{
    private readonly ConcurrentDictionary<string, User> _users = new();
    private readonly ConcurrentDictionary<string, string> _emailIndex = new(StringComparer.OrdinalIgnoreCase);
    private readonly ConcurrentBag<LoginAudit> _loginAudits = new();
    private readonly ILogger<InMemoryUserService> _logger;

    public InMemoryUserService(ILogger<InMemoryUserService> logger, IConfiguration configuration)
    {
        _logger = logger;

        var demoPassword = configuration["Demo:Password"];
        if (string.IsNullOrWhiteSpace(demoPassword))
        {
            demoPassword = Guid.NewGuid().ToString("N")[..16];
            logger.LogWarning("No Demo__Password configured — generated demo password: {DemoPassword}", demoPassword);
        }

        var passwordHash = BC.HashPassword(demoPassword);

        var defaultUser = new User
        {
            Id = "1",
            Username = "testuser",
            Email = "test@example.com",
            FirstName = "Test",
            LastName = "User",
            Role = "admin",
            PasswordHash = passwordHash,
            Salt = ""
        };
        _users[defaultUser.Id] = defaultUser;
        _emailIndex[defaultUser.Email] = defaultUser.Id;

        var demoUser = new User
        {
            Id = "2",
            Username = "demo@banking-demo.com",
            Email = "demo@banking-demo.com",
            FirstName = "Demo",
            LastName = "User",
            Role = "admin",
            PasswordHash = passwordHash,
            Salt = ""
        };
        _users[demoUser.Id] = demoUser;
        _emailIndex[demoUser.Email] = demoUser.Id;
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

        var passwordHash = BC.HashPassword(request.Password);

        // Check if this is the first user in the system — auto-promote to admin
        var isFirstUser = _users.IsEmpty;

        var user = new User
        {
            Id = Guid.NewGuid().ToString(),
            Username = request.Username,
            Email = request.Email,
            FirstName = request.FirstName,
            LastName = request.LastName,
            PasswordHash = passwordHash,
            Salt = "",
            Role = isFirstUser ? "admin" : "user"
        };

        // Atomic email uniqueness check — prevents TOCTOU race
        if (!_emailIndex.TryAdd(request.Email, user.Id))
        {
            throw new InvalidOperationException("Email already exists");
        }

        if (isFirstUser)
        {
            _logger.LogInformation("First user {Username} ({Email}) auto-promoted to admin role", user.Username, user.Email);
        }

        _users[user.Id] = user;
        _logger.LogInformation("Created user {UserId} with role {Role}", user.Id, user.Role);
        
        return await Task.FromResult(user);
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
    }

    public Task<User> PromoteToAdminAsync(string userId)
    {
        if (!_users.TryGetValue(userId, out var user))
            throw new KeyNotFoundException($"User {userId} not found");

        if (user.Role == "admin")
            throw new InvalidOperationException($"User {userId} is already an admin");

        user.Role = "admin";
        _logger.LogInformation("User {UserId} ({Email}) promoted to admin", user.Id, user.Email);
        return Task.FromResult(user);
    }

    public Task<int> GetAdminCountAsync()
    {
        var count = _users.Values.Count(u => u.Role == "admin");
        return Task.FromResult(count);
    }

    public Task<List<User>> GetAllUsersAsync()
    {
        return Task.FromResult(_users.Values.ToList());
    }

    public async Task<bool> LockUserAsync(string userId)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) return false;
        user.IsLocked = true;
        return true;
    }

    public async Task<bool> UnlockUserAsync(string userId)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) return false;
        user.IsLocked = false;
        return true;
    }

    public async Task<bool> ResetUserPasswordAsync(string userId, string newPassword)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) return false;
        user.PasswordHash = BC.HashPassword(newPassword);
        return true;
    }

    public async Task<bool> DeleteUserAsync(string userId)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) return false;

        if (_users.TryRemove(userId, out _))
        {
            _emailIndex.TryRemove(user.Email, out _);
            return true;
        }
        return false;
    }

    public Task LogLoginAuditAsync(LoginAudit audit)
    {
        _loginAudits.Add(audit);
        _logger.LogInformation("Login audit: {Username} at {Timestamp} - Success: {Success}", audit.Username, audit.Timestamp, audit.Success);
        return Task.CompletedTask;
    }

    public Task<List<LoginAudit>> GetLoginAuditsAsync(int limit = 100)
    {
        var audits = _loginAudits
            .OrderByDescending(a => a.Timestamp)
            .Take(limit)
            .ToList();
        return Task.FromResult(audits);
    }
}