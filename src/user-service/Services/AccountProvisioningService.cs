using System.Net.Http.Headers;
using System.Text;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;

namespace UserService.Services;

/// <summary>
/// Best-effort provisioning of a default checking account when a new user registers.
/// Failures are logged as warnings and never bubble out — registration must succeed
/// even if the downstream account-service is briefly unavailable.
/// </summary>
public interface IAccountProvisioningService
{
    Task ProvisionDefaultAccountAsync(string userId);
}

public sealed class AccountProvisioningService : IAccountProvisioningService
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IAuthService _authService;
    private readonly ILogger<AccountProvisioningService> _logger;

    public AccountProvisioningService(
        IHttpClientFactory httpClientFactory,
        IAuthService authService,
        ILogger<AccountProvisioningService> logger)
    {
        _httpClientFactory = httpClientFactory;
        _authService = authService;
        _logger = logger;
    }

    public async Task ProvisionDefaultAccountAsync(string userId)
    {
        try
        {
            var client = _httpClientFactory.CreateClient("AccountService");

            // Mint a short-lived JWT so account-service can authenticate this internal call
            var token = await _authService.GenerateTokenAsync(userId, "system", Constants.Roles.User);

            var accountRequest = new CreateAccountRequest
            {
                AccountType = "Checking",
                InitialBalance = 0m,
                Currency = "USD"
            };

            var json = JsonConvert.SerializeObject(accountRequest);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);

            var response = await client.PostAsync("/api/accounts", content);

            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning(
                    "Failed to provision default account for user {UserId}. Status: {StatusCode}",
                    userId, response.StatusCode);
            }
            else
            {
                _logger.LogInformation("Provisioned default checking account for user {UserId}", userId);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error provisioning default account for user {UserId}", userId);
        }
    }
}
