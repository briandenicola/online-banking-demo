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
}