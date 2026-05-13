using System.Net.Http.Headers;
using System.Text;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using TransferService.Models;

namespace TransferService.Services;

/// <summary>
/// Carries out the side effects of a transfer: posts debit/credit entries
/// to transaction-service. Pure orchestration of downstream HTTP — no
/// validation, no persistence, no eventing.
/// </summary>
public interface ITransferExecutor
{
    Task ExecuteAsync(Transfer transfer, CreateTransferRequest request);
}

public sealed class TransferExecutor : ITransferExecutor
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private readonly IConfiguration _configuration;

    public TransferExecutor(
        IHttpClientFactory httpClientFactory,
        IHttpContextAccessor httpContextAccessor,
        IConfiguration configuration)
    {
        _httpClientFactory = httpClientFactory;
        _httpContextAccessor = httpContextAccessor;
        _configuration = configuration;
    }

    public async Task ExecuteAsync(Transfer transfer, CreateTransferRequest request)
    {
        var client = CreateAuthenticatedClient();
        var transactionServiceUrl = _configuration["Services:TransactionService"];

        var debit = new CreateTransactionRequest
        {
            AccountId = request.FromAccountId,
            Amount = -request.Amount,
            Type = global::TransferService.Constants.TransactionTypes.Transfer,
            Description = request.Description ?? $"Transfer to account ending in {request.ToAccountId[^4..]}",
            Category = global::TransferService.Constants.Categories.Transfer,
            RelatedTransactionId = transfer.Id
        };

        var debitResponse = await client.PostAsync(
            $"{transactionServiceUrl}/api/transactions",
            new StringContent(JsonConvert.SerializeObject(debit), Encoding.UTF8, "application/json"));
        if (!debitResponse.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"Failed to create debit transaction: {debitResponse.StatusCode}");
        }

        var credit = new CreateTransactionRequest
        {
            AccountId = request.ToAccountId,
            Amount = request.Amount,
            Type = global::TransferService.Constants.TransactionTypes.Transfer,
            Description = request.Description ?? $"Transfer from account ending in {request.FromAccountId[^4..]}",
            Category = global::TransferService.Constants.Categories.Transfer,
            RelatedTransactionId = transfer.Id
        };

        var creditResponse = await client.PostAsync(
            $"{transactionServiceUrl}/api/transactions",
            new StringContent(JsonConvert.SerializeObject(credit), Encoding.UTF8, "application/json"));
        if (!creditResponse.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"Failed to create credit transaction: {creditResponse.StatusCode}");
        }
        // Balance updates are handled by transaction-service when it creates each transaction.
    }

    private HttpClient CreateAuthenticatedClient()
    {
        var client = _httpClientFactory.CreateClient();
        var authHeader = _httpContextAccessor.HttpContext?.Request.Headers["Authorization"].FirstOrDefault();
        if (!string.IsNullOrEmpty(authHeader))
        {
            client.DefaultRequestHeaders.TryAddWithoutValidation("Authorization", authHeader);
        }
        return client;
    }
}
