using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using OnlineBankingDemo.Contracts.Events;
using UserService.Repositories;
using UserModel = UserService.Models.User;
using BC = global::BCrypt.Net.BCrypt;

namespace UserService.Services;

public class UserService : IUserService
{
    private readonly IUserRepository _userRepository;
    private readonly ILoginAuditRepository _loginAuditRepository;
    private readonly IEventPublisher _eventPublisher;
    private readonly ILogger<UserService> _logger;

    public UserService(
        IUserRepository userRepository,
        ILoginAuditRepository loginAuditRepository,
        IEventPublisher eventPublisher,
        ILogger<UserService> logger)
    {
        _userRepository = userRepository;
        _loginAuditRepository = loginAuditRepository;
        _eventPublisher = eventPublisher;
        _logger = logger;
    }

    public async Task<UserModel?> GetUserByIdAsync(string id)
    {
        return await _userRepository.GetByIdAsync(id);
    }

    public async Task<UserModel?> GetUserByUsernameAsync(string username)
    {
        return await _userRepository.GetByUsernameAsync(username);
    }

    public async Task<UserModel?> GetUserByEmailAsync(string email)
    {
        return await _userRepository.GetByEmailAsync(email);
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

        // Check if this is the first user in the system — auto-promote to admin
        var isFirstUser = await _userRepository.IsContainerEmptyAsync();

        var user = new UserModel
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

        if (isFirstUser)
        {
            _logger.LogInformation("First user {Username} ({Email}) auto-promoted to admin role", user.Username, user.Email);
        }

        // Create email lookup document first to prevent race conditions (TOCTOU).
        // The deterministic ID ensures Cosmos returns 409 on duplicate emails.
        var emailLookupId = $"email-lookup:{request.Email.ToLowerInvariant()}";
        var emailLookupDoc = new
        {
            id = emailLookupId,
            type = "email-lookup",
            userId = user.Id,
            email = request.Email
        };

        try
        {
            await _userRepository.CreateEmailLookupAsync(emailLookupId, emailLookupDoc);
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.Conflict)
        {
            throw new InvalidOperationException("Email already exists");
        }

        // Create the actual user document. If this fails, clean up the lookup doc.
        try
        {
            var createdUser = await _userRepository.CreateAsync(user);

            await PublishUserRegisteredEvent(user);

            return createdUser;
        }
        catch
        {
            // Best-effort cleanup of the lookup document
            try
            {
                await _userRepository.DeleteEmailLookupAsync(emailLookupId);
            }
            catch (Exception cleanupEx)
            {
                _logger.LogWarning(cleanupEx, "Failed to clean up email lookup document {LookupId}", emailLookupId);
            }
            throw;
        }
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
        await _userRepository.ReplaceAsync(user);
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
        await _userRepository.ReplaceAsync(user);
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
        await _userRepository.ReplaceAsync(user);
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

            await _eventPublisher.PublishAsync("banking-events", payload);
            _logger.LogInformation("Published UserRegistered event to Redis Stream for user {UserId}", user.Id);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to publish UserRegistered event — non-critical");
        }
    }

    public async Task<UserModel> PromoteToAdminAsync(string userId)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null)
            throw new KeyNotFoundException($"User {userId} not found");

        if (user.Role == "admin")
            throw new InvalidOperationException($"User {userId} is already an admin");

        user.Role = "admin";
        await _userRepository.ReplaceAsync(user);
        _logger.LogInformation("User {UserId} ({Email}) promoted to admin", user.Id, user.Email);
        return user;
    }

    public async Task<int> GetAdminCountAsync()
    {
        return await _userRepository.GetAdminCountAsync();
    }

    // Admin methods
    public async Task<List<UserModel>> GetAllUsersAsync()
    {
        return await _userRepository.GetAllUsersAsync();
    }

    public async Task<bool> LockUserAsync(string userId)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) return false;

        user.IsLocked = true;
        await _userRepository.ReplaceAsync(user);
        _logger.LogInformation("User {UserId} locked", userId);
        return true;
    }

    public async Task<bool> UnlockUserAsync(string userId)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) return false;

        user.IsLocked = false;
        await _userRepository.ReplaceAsync(user);
        _logger.LogInformation("User {UserId} unlocked", userId);
        return true;
    }

    public async Task<bool> ResetUserPasswordAsync(string userId, string newPassword)
    {
        var user = await GetUserByIdAsync(userId);
        if (user == null) return false;

        user.PasswordHash = BC.HashPassword(newPassword);
        await _userRepository.ReplaceAsync(user);
        _logger.LogInformation("Password reset for user {UserId}", userId);
        return true;
    }

    public async Task<bool> DeleteUserAsync(string userId)
    {
        // Fetch user first to get email for lookup doc cleanup
        var user = await GetUserByIdAsync(userId);

        var deleted = await _userRepository.DeleteAsync(userId);
        if (!deleted) return false;

        _logger.LogInformation("User {UserId} deleted", userId);

        // Best-effort cleanup of the email lookup document
        if (user?.Email != null)
        {
            await _userRepository.DeleteEmailLookupAsync($"email-lookup:{user.Email.ToLowerInvariant()}");
        }

        return true;
    }

    public async Task LogLoginAuditAsync(Models.LoginAudit audit)
    {
        try
        {
            await _loginAuditRepository.CreateAsync(audit);
            _logger.LogInformation("Login audit logged for user {UserId}", audit.UserId);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to log login audit for user {UserId}", audit.UserId);
        }
    }

    public async Task<List<Models.LoginAudit>> GetLoginAuditsAsync(int limit = 100)
    {
        try
        {
            return await _loginAuditRepository.GetRecentAsync(limit);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to retrieve login audits");
            return new List<Models.LoginAudit>();
        }
    }
}