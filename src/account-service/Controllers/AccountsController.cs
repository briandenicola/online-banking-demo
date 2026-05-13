using System.ComponentModel.DataAnnotations;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using AccountService.Services;
using OnlineBankingDemo.Contracts.Dtos;

namespace AccountService.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize]
public class AccountsController : ControllerBase
{
    private readonly IAccountService _accountService;
    private readonly ILogger<AccountsController> _logger;

    public AccountsController(IAccountService accountService, ILogger<AccountsController> logger)
    {
        _accountService = accountService;
        _logger = logger;
    }

    [HttpPost]
    public async Task<IActionResult> CreateAccount([FromBody] CreateAccountRequest request)
    {
        var userId = User.FindFirst(global::AccountService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        var account = await _accountService.CreateAccountAsync(userId, request);
        return Ok(new
        {
            account.Id,
            account.AccountNumber,
            account.AccountType,
            account.Balance,
            account.Currency,
            account.CreatedAt
        });
    }

    [HttpGet]
    public async Task<IActionResult> GetUserAccounts()
    {
        var userId = User.FindFirst(global::AccountService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        var accounts = await _accountService.GetUserAccountsAsync(userId);
        return Ok(accounts);
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetAccount(string id)
    {
        var account = await _accountService.GetAccountByIdAsync(id);
        if (account == null)
        {
            return NotFound();
        }

        var userId = User.FindFirst(global::AccountService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId) || account.UserId != userId)
        {
            return NotFound();
        }

        return Ok(account);
    }

    [HttpGet("number/{accountNumber}")]
    public async Task<IActionResult> GetAccountByNumber(string accountNumber)
    {
        var account = await _accountService.GetAccountByNumberAsync(accountNumber);
        if (account == null)
        {
            return NotFound();
        }

        var userId = User.FindFirst(global::AccountService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId) || account.UserId != userId)
        {
            return NotFound();
        }

        return Ok(account);
    }

    [HttpPost("{id}/balance")]
    public async Task<IActionResult> UpdateBalance(string id, [FromBody] UpdateBalanceRequest request)
    {
        var userId = User.FindFirst(global::AccountService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        var account = await _accountService.GetAccountByIdAsync(id);
        if (account == null || account.UserId != userId)
        {
            return NotFound();
        }

        try
        {
            var updated = await _accountService.UpdateBalanceAsync(id, request.Amount);
            return Ok(updated);
        }
        catch (Exception ex)
        {
            var correlationId = HttpContext.TraceIdentifier;
            _logger.LogError(ex, "Failed to update balance for account {AccountId}. CorrelationId: {CorrelationId}", id, correlationId);
            return StatusCode(500, new { error = "An internal error occurred", correlationId });
        }
    }
}

public class UpdateBalanceRequest
{
    [Required]
    [Range(-10000000, 10000000, ErrorMessage = "Amount must be between -10,000,000 and 10,000,000")]
    public decimal Amount { get; set; }
}