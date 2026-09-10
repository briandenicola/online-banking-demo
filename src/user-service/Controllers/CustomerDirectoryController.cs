using Banking.Auth;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using UserService.Services;

namespace UserService.Controllers;

[ApiController]
[Route("api/customer-directory")]
[Authorize(Roles = BankingRoles.CustomerDirectoryLookup)]
public class CustomerDirectoryController : ControllerBase
{
    private const int Limit = 5;
    private readonly IUserService _userService;
    private readonly ILogger<CustomerDirectoryController> _logger;

    public CustomerDirectoryController(IUserService userService, ILogger<CustomerDirectoryController> logger)
    {
        _userService = userService;
        _logger = logger;
    }

    [HttpGet("lookup")]
    public async Task<IActionResult> Lookup([FromQuery] string username)
    {
        var query = (username ?? string.Empty).Trim();
        if (query.Length < 3 || query.Contains('*') || query.Contains('%'))
        {
            return BadRequest(new { error = "username_lookup_query_invalid", message = "Provide at least 3 literal username characters." });
        }

        var users = await _userService.LookupUsersByUsernamePrefixAsync(query, Limit);
        var caller = User.FindFirst("userId")?.Value ?? User.Identity?.Name ?? "unknown";
        _logger.LogInformation(
            "AUDIT customer_directory_lookup caller={Caller} query={Query} resultCount={ResultCount}",
            caller,
            query,
            users.Count);

        return Ok(new
        {
            query,
            count = users.Count,
            matches = users.Select(u => new
            {
                id = u.Id,
                username = u.Username,
                displayName = $"{u.FirstName} {u.LastName}".Trim(),
                status = u.IsLocked ? "locked" : (u.IsActive ? "active" : "inactive")
            })
        });
    }
}
