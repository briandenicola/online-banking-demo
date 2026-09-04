using System.Collections.Generic;
using System.Threading.Tasks;
using OnlineBankingDemo.Contracts.Dtos;
using UserService.Models;

namespace UserService.Services;

public interface IUserService
{
    Task<User?> GetUserByIdAsync(string id);
    Task<User?> GetUserByUsernameAsync(string username);
    Task<User?> GetUserByEmailAsync(string email);
    Task<User> CreateUserAsync(RegisterUserRequest request);
    Task<bool> ValidateCredentialsAsync(string username, string password);
    Task<bool> ChangePasswordAsync(string userId, string currentPassword, string newPassword);
    Task<string?> GetAvatarAsync(string userId);
    Task SetAvatarAsync(string userId, string avatarBase64);
    Task<List<string>> GetCategoryPreferencesAsync(string userId);
    Task SetCategoryPreferencesAsync(string userId, List<string> categories);

    // Admin methods
    Task<User> PromoteToAdminAsync(string userId);

    /// <summary>
    /// Grants a role (admin / supervisor / banker / user) to an identity.
    /// Role promotion is an L3 action and is never reachable from the Copilot
    /// harness — see epic #332 §5.8.3.
    /// </summary>
    Task<User> GrantRoleAsync(string userId, string role);

    Task<int> GetAdminCountAsync();
    Task<List<User>> GetAllUsersAsync();
    Task<bool> LockUserAsync(string userId);
    Task<bool> UnlockUserAsync(string userId);
    Task<bool> ResetUserPasswordAsync(string userId, string newPassword);
    Task<bool> DeleteUserAsync(string userId);
    Task LogLoginAuditAsync(LoginAudit audit);
    Task<List<LoginAudit>> GetLoginAuditsAsync(int limit = 100);
}