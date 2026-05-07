using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using TransactionService.Services;

namespace TransactionService.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize]
public class TransactionsController : ControllerBase
{
    private readonly ITransactionService _transactionService;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IConfiguration _configuration;
    private readonly ILogger<TransactionsController> _logger;

    public TransactionsController(
        ITransactionService transactionService,
        IHttpClientFactory httpClientFactory,
        IConfiguration configuration,
        ILogger<TransactionsController> logger)
    {
        _transactionService = transactionService;
        _httpClientFactory = httpClientFactory;
        _configuration = configuration;
        _logger = logger;
    }

    [HttpPost]
    public async Task<IActionResult> CreateTransaction([FromBody] CreateTransactionRequest request)
    {
        var userId = User.FindFirst("userId")?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        try
        {
            var transaction = await _transactionService.CreateTransactionAsync(request, userId);

            // Update account balance
            await UpdateAccountBalanceAsync(transaction.AccountId, transaction.Amount);

            return CreatedAtAction(nameof(GetTransaction), new { id = transaction.Id }, transaction);
        }
        catch (InsufficientFundsException ex)
        {
            _logger.LogWarning("Insufficient funds for account {AccountId}: balance {Balance}, requested {Amount}",
                ex.AccountId, ex.CurrentBalance, ex.RequestedAmount);
            return BadRequest(new { error = "Insufficient funds", message = ex.Message });
        }
    }

    private async Task UpdateAccountBalanceAsync(string accountId, decimal amount)
    {
        var accountServiceUrl = _configuration["Services:AccountService"];
        if (string.IsNullOrEmpty(accountServiceUrl))
        {
            _logger.LogWarning("Services:AccountService not configured — skipping balance update");
            return;
        }

        try
        {
            var client = _httpClientFactory.CreateClient();

            // Forward the incoming JWT for auth
            var authHeader = Request.Headers["Authorization"].FirstOrDefault();
            if (!string.IsNullOrEmpty(authHeader))
            {
                client.DefaultRequestHeaders.TryAddWithoutValidation("Authorization", authHeader);
            }

            var payload = JsonConvert.SerializeObject(new { amount });
            var response = await client.PostAsync(
                $"{accountServiceUrl}/api/accounts/{accountId}/balance",
                new StringContent(payload, Encoding.UTF8, "application/json"));

            if (!response.IsSuccessStatusCode)
            {
                _logger.LogError("Failed to update balance for account {AccountId}: {StatusCode}", accountId, response.StatusCode);
            }
            else
            {
                _logger.LogInformation("Updated balance for account {AccountId} by {Amount}", accountId, amount);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error updating balance for account {AccountId}", accountId);
        }
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetTransaction(string id)
    {
        var transaction = await _transactionService.GetTransactionByIdAsync(id);
        if (transaction == null)
        {
            return NotFound();
        }
        return Ok(transaction);
    }

    [HttpGet("account/{accountId}")]
    public async Task<IActionResult> GetAccountTransactions(string accountId)
    {
        var transactions = await _transactionService.GetAccountTransactionsAsync(accountId);
        return Ok(transactions);
    }

    [HttpGet]
    public async Task<IActionResult> GetTransactions()
    {
        var userId = User.FindFirst("userId")?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        var transactions = await _transactionService.GetUserTransactionsAsync(userId);
        return Ok(transactions);
    }

    [HttpGet("my")]
    public async Task<IActionResult> GetUserTransactions()
    {
        var userId = User.FindFirst("userId")?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        // For now, return all transactions - in production, filter by user's accounts
        var transactions = await _transactionService.GetUserTransactionsAsync(userId);
        return Ok(transactions);
    }
}