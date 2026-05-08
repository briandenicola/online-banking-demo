using System.Threading.Tasks;

namespace UserService.Services;

public interface IAuthService
{
    Task<string> GenerateTokenAsync(string userId, string username, string role);
    Task<bool> ValidateTokenAsync(string token);
}