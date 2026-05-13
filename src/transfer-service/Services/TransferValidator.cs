using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using OnlineBankingDemo.Contracts.Dtos;

namespace TransferService.Services;

/// <summary>
/// Validates incoming transfer requests against business rules and external state
/// (e.g., the source account must belong to the authenticated user).
/// </summary>
public interface ITransferValidator
{
    Task ValidateAsync(string userId, CreateTransferRequest request);
}

public sealed class TransferValidator : ITransferValidator
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private readonly IConfiguration _configuration;

    public TransferValidator(
        IHttpClientFactory httpClientFactory,
        IHttpContextAccessor httpContextAccessor,
        IConfiguration configuration)
    {
        _httpClientFactory = httpClientFactory;
        _httpContextAccessor = httpContextAccessor;
        _configuration = configuration;
    }

    public async Task ValidateAsync(string userId, CreateTransferRequest request)
    {
        await VerifyAccountOwnershipAsync(request.FromAccountId, userId);
    }

    private async Task VerifyAccountOwnershipAsync(string accountId, string userId)
    {
        var accountServiceUrl = _configuration["Services:AccountService"];
        if (string.IsNullOrEmpty(accountServiceUrl))
        {
            throw new InvalidOperationException("AccountService URL not configured; cannot verify account ownership");
        }

        var client = _httpClientFactory.CreateClient();
        var authHeader = _httpContextAccessor.HttpContext?.Request.Headers["Authorization"].FirstOrDefault();
        if (!string.IsNullOrEmpty(authHeader))
        {
            client.DefaultRequestHeaders.TryAddWithoutValidation("Authorization", authHeader);
        }

        var response = await client.GetAsync($"{accountServiceUrl}/api/accounts/{accountId}");
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"Account {accountId} not found or not accessible");
        }

        var json = await response.Content.ReadAsStringAsync();
        var account = System.Text.Json.JsonSerializer.Deserialize<AccountOwnerInfo>(json, new System.Text.Json.JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        });

        if (account == null || account.UserId != userId)
        {
            throw new InvalidOperationException($"Account {accountId} not found or not accessible");
        }
    }

    private sealed class AccountOwnerInfo
    {
        public string Id { get; set; } = null!;
        public string UserId { get; set; } = null!;
    }
}
