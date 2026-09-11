using System.ComponentModel.DataAnnotations;
using System.Threading.Tasks;
using Banking.Auth;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
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
            // ABSENT. §B2: this is the ONLY thing a 404 means on this endpoint now.
            return NotFound();
        }

        var userId = User.FindFirst(global::AccountService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        if (!MayReadCustomerFinancials(account.UserId, userId))
        {
            return CustomerFinancialsForbidden(id);
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
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        if (!MayReadCustomerFinancials(account.UserId, userId))
        {
            return CustomerFinancialsForbidden(account.Id);
        }

        return Ok(account);
    }

    [HttpGet("customer/{userId}")]
    [Authorize(Roles = BankingRoles.CustomerFinancialRead)]
    public async Task<IActionResult> GetAccountsForCustomer(string userId)
    {
        var callerUserId = User.FindFirst(global::AccountService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(callerUserId))
        {
            return Unauthorized();
        }

        var accounts = await _accountService.GetUserAccountsAsync(userId);
        _logger.LogInformation(
            "AUDIT customer_accounts_lookup caller={CallerUserId} subject={SubjectUserId} count={Count}",
            callerUserId,
            userId,
            accounts.Count());
        return Ok(accounts);
    }

    /// <summary>
    /// May this caller read this account? The owner always may; otherwise it takes banking
    /// authority over customer money (§B1.1).
    /// </summary>
    private bool MayReadCustomerFinancials(string ownerUserId, string callerUserId) =>
        ownerUserId == callerUserId || BankingRoles.Holds(User, BankingRoles.CustomerFinancialRead);

    /// <summary>
    /// FORBIDDEN, and it says so. §B2.1: this used to answer 404, which hid account-id existence
    /// from an authenticated hostile caller. That control was removed deliberately — the demo's
    /// threat model does not include a banker enumerating ids (every banker can already read
    /// every account by §B1), and the cost was that NOTHING downstream could tell a denial from
    /// an absence: not the copilot, not the projection, not the supervisor, not the human reading
    /// the card. Enumeration hardening at the edge, with the true status in the audit log, is
    /// ticketed — and it is unimplementable until the internals distinguish the two facts, which
    /// is what this line does.
    /// </summary>
    private IActionResult CustomerFinancialsForbidden(string accountId)
    {
        _logger.LogWarning(
            "Denied read of account {AccountId}: caller is neither the owner nor a banker/supervisor.",
            accountId);
        return StatusCode(StatusCodes.Status403Forbidden, new { error = "Forbidden" });
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
        if (account == null)
        {
            return NotFound();
        }

        // §B4.3. Without this the demo fails one step LATER than the read did — after evidence
        // has been gathered and the approval signed — which is worse, because by then it looks
        // like the harness worked. CustomerFinancialWrite, not ...Read: same members today, two
        // different authorities.
        if (account.UserId != userId && !BankingRoles.Holds(User, BankingRoles.CustomerFinancialWrite))
        {
            _logger.LogWarning(
                "Denied balance update on account {AccountId}: caller is neither the owner nor a banker/supervisor.",
                id);
            return StatusCode(StatusCodes.Status403Forbidden, new { error = "Forbidden" });
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