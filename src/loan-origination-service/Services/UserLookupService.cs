using System.Text.Json;

namespace LoanOrigination.Services;

public interface IUserLookupService
{
    Task<UserInfo?> GetUserAsync(string userId);
    Task<bool> ValidateUserAsync(string userId);
}

public class UserLookupService : IUserLookupService
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<UserLookupService> _logger;
    private readonly IHttpContextAccessor _httpContextAccessor;

    public UserLookupService(
        IHttpClientFactory httpClientFactory, 
        ILogger<UserLookupService> logger,
        IHttpContextAccessor httpContextAccessor)
    {
        _httpClientFactory = httpClientFactory;
        _logger = logger;
        _httpContextAccessor = httpContextAccessor;
    }

    public async Task<UserInfo?> GetUserAsync(string userId)
    {
        try
        {
            var client = _httpClientFactory.CreateClient("UserService");
            
            // Forward the caller's bearer token for auditability
            var authHeader = _httpContextAccessor.HttpContext?.Request.Headers["Authorization"].FirstOrDefault();
            if (!string.IsNullOrEmpty(authHeader))
            {
                client.DefaultRequestHeaders.TryAddWithoutValidation("Authorization", authHeader);
            }

            var response = await client.GetAsync($"/api/users/{userId}");
            
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning("User lookup failed for {UserId}: {StatusCode}", userId, response.StatusCode);
                return null;
            }

            var content = await response.Content.ReadAsStringAsync();
            var user = JsonSerializer.Deserialize<UserInfo>(content, new JsonSerializerOptions 
            { 
                PropertyNameCaseInsensitive = true 
            });

            _logger.LogInformation("User lookup succeeded for {UserId}", userId);
            return user;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error looking up user {UserId}", userId);
            return null;
        }
    }

    public async Task<bool> ValidateUserAsync(string userId)
    {
        var user = await GetUserAsync(userId);
        return user != null;
    }
}

public class UserInfo
{
    public string Id { get; set; } = string.Empty;
    public string Username { get; set; } = string.Empty;
    public string Email { get; set; } = string.Empty;
    public string FirstName { get; set; } = string.Empty;
    public string LastName { get; set; } = string.Empty;
    public string? Phone { get; set; }
    public string? DateOfBirth { get; set; }
}
