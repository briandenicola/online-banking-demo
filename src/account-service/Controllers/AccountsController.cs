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
        // Support both JWT claim and X-User-Id header (for authenticated internal service calls)
        var userId = User.FindFirst("userId")?.Value
            ?? Request.Headers["X-User-Id"].FirstOrDefault();
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
        var userId = User.FindFirst("userId")?.Value;
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

        // Verify ownership
        var userId = User.FindFirst("userId")?.Value;
        if (account.UserId != userId)
        {
            return Forbid();
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

        // Verify ownership
        var userId = User.FindFirst("userId")?.Value;
        if (account.UserId != userId)
        {
            return Forbid();
        }

        return Ok(account);
    }

    [HttpPost("{id}/balance")]
    public async Task<IActionResult> UpdateBalance(string id, [FromBody] UpdateBalanceRequest request)
    {
        try
        {
            var account = await _accountService.UpdateBalanceAsync(id, request.Amount);
            return Ok(account);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to update balance for account {AccountId}", id);
            return BadRequest(new { Message = ex.Message });
        }
    }
}

public class UpdateBalanceRequest
{
    public decimal Amount { get; set; }
}