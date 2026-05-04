using System.Threading.Tasks;

namespace UserService.Services;

public interface IAuthService
{
    Task<string> GenerateTokenAsync(string userId, string username);
    Task<bool> ValidateTokenAsync(string token);
}