using System.Linq;
using System.Threading.Tasks;
using Banking.Auth;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
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

        // §B2.2. This endpoint used to read the CALLER's transactions and narrow them to this
        // accountId, so for any non-owner it returned `200 []` BY CONSTRUCTION, for every account
        // in the bank. That was not a lenient authorization check — there was no check at all,
        // and the empty result was a coincidence of the query that read as a fact about the
        // world. The old filter is DELETED rather than kept as a fallback: a fallback would
        // preserve the exact path that produces the lie.
        var accountTransactions = (await _transactionService.GetAccountTransactionsAsync(accountId)).ToList();

        var privileged = BankingRoles.Holds(User, BankingRoles.CustomerFinancialRead);
        var ownsEveryRow = accountTransactions.Count > 0 && accountTransactions.All(t => t.UserId == userId);
        if (!privileged && !ownsEveryRow)
        {
            // NARROWING the ruling's §B2 table at the one point it cannot cover, and saying so.
            // A non-privileged caller's entitlement here is derived from the rows themselves —
            // this service does not own accounts and has nothing else to derive it from. An
            // EMPTY result therefore proves nothing about entitlement, so it cannot be the
            // table's "permitted and empty" row. Answering `200 []` on it would rebuild the
            // exact defect §B2.2 deletes: a true-looking answer produced by an accident of the
            // query. It errs closed, and it costs no shipping caller — the copilot always holds
            // `banker`, and no other caller in the repo uses this endpoint.
            _logger.LogWarning(
                "Denied read of transactions for account {AccountId}: caller is neither the owner nor a banker/supervisor.",
                accountId);
            return StatusCode(StatusCodes.Status403Forbidden, new { error = "Forbidden" });
        }

        // A permitted caller and a genuinely empty ledger. §B2: after this change that is the
        // ONLY way an empty array is produced here.
        //
        // What it does NOT say is whether the account exists — transaction-service does not own
        // accounts and cannot tell "no such account" from "clean history". The honest reading of
        // this body is "the transactions recorded against this accountId", silent on existence.
        // Existence is get_account's question, and the §B3.2 startup guard in the authority-policy
        // loader is what stops anyone requiring this evidence without it.
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