using System.Linq;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using OnlineBankingDemo.Contracts.Dtos;
using TransactionService.Services;

namespace TransactionService.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize]
public class TransactionsController : ControllerBase
{
    private readonly ITransactionService _transactionService;
    private readonly ILogger<TransactionsController> _logger;

    public TransactionsController(
        ITransactionService transactionService,
        ILogger<TransactionsController> logger)
    {
        _transactionService = transactionService;
        _logger = logger;
    }

    [HttpPost]
    public async Task<IActionResult> CreateTransaction([FromBody] CreateTransactionRequest request)
    {
        var userId = User.FindFirst(global::TransactionService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        try
        {
            var transaction = await _transactionService.CreateTransactionAsync(request, userId);
            return CreatedAtAction(nameof(GetTransaction), new { id = transaction.Id }, transaction);
        }
        catch (InsufficientFundsException ex)
        {
            _logger.LogWarning("Insufficient funds for account {AccountId}: balance {Balance}, requested {Amount}",
                ex.AccountId, ex.CurrentBalance, ex.RequestedAmount);
            return BadRequest(new { error = "Insufficient funds" });
        }
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetTransaction(string id)
    {
        var userId = User.FindFirst(global::TransactionService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        var transaction = await _transactionService.GetTransactionByIdAsync(id);
        if (transaction == null || transaction.UserId != userId)
        {
            return NotFound();
        }
        return Ok(transaction);
    }

    [HttpGet("account/{accountId}")]
    public async Task<IActionResult> GetAccountTransactions(string accountId)
    {
        var userId = User.FindFirst(global::TransactionService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        var userTransactions = await _transactionService.GetUserTransactionsAsync(userId);
        var accountTransactions = userTransactions.Where(t => t.AccountId == accountId);
        return Ok(accountTransactions);
    }

    [HttpGet]
    public async Task<IActionResult> GetTransactions()
    {
        var userId = User.FindFirst(global::TransactionService.Constants.ClaimNames.UserId)?.Value;
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
        var userId = User.FindFirst(global::TransactionService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        var transactions = await _transactionService.GetUserTransactionsAsync(userId);
        return Ok(transactions);
    }
}