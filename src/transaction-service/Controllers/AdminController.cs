using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using TransactionService.Services;

namespace TransactionService.Controllers;

/// <summary>
/// Admin-only maintenance endpoints. Currently exposes a one-shot replay of
/// <c>TransactionCreated</c> events used to backfill ai-service scoring after
/// a Redis purge.
/// </summary>
[ApiController]
[Route("api/admin")]
[Authorize(Roles = "admin,Admin")]
public class AdminController : ControllerBase
{
    private readonly ITransactionService _transactionService;
    private readonly ILogger<AdminController> _logger;

    public AdminController(ITransactionService transactionService, ILogger<AdminController> logger)
    {
        _transactionService = transactionService;
        _logger = logger;
    }

    [HttpPost("replay-events")]
    public async Task<IActionResult> ReplayEvents([FromQuery] int limit = 10_000)
    {
        if (limit <= 0 || limit > 100_000)
        {
            return BadRequest(new { error = "limit must be between 1 and 100000" });
        }

        _logger.LogInformation("Admin requested transaction event replay (limit={Limit})", limit);
        var published = await _transactionService.ReplayCreatedEventsAsync(limit);
        return Ok(new { published, limit });
    }
}
