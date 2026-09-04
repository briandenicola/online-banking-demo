using System.ComponentModel.DataAnnotations;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using UserService.Services;

namespace UserService.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize(Roles = global::UserService.Constants.Roles.Admin)]
public class AdminController : ControllerBase
{
    private readonly IUserService _userService;
    private readonly ILogger<AdminController> _logger;

    public AdminController(IUserService userService, ILogger<AdminController> logger)
    {
        _userService = userService;
        _logger = logger;
    }

    /// <summary>
    /// Grants a role to a user identified by email or userId. Defaults to
    /// <c>admin</c> when no role is supplied, preserving the original
    /// promote-to-admin behaviour.
    /// Requires an existing admin's JWT. For initial bootstrap, set the
    /// Admin__BootstrapEmail environment variable — the matching user is
    /// auto-promoted at startup. The first `supervisor` is seeded the same way
    /// via Authority__BootstrapSupervisorEmail, because promotion to supervisor
    /// is itself an L3 action and cannot be performed through the harness
    /// (epic #332 §5.8.3).
    /// </summary>
    [HttpPost("promote")]
    public async Task<IActionResult> PromoteToAdmin([FromBody] PromoteRequest request)
    {
        var role = string.IsNullOrWhiteSpace(request.Role)
            ? global::UserService.Constants.Roles.Admin
            : request.Role.Trim().ToLowerInvariant();

        if (!UserService.Services.UserService.IsGrantableRole(role))
        {
            return BadRequest(new
            {
                error = $"'{request.Role}' is not a grantable role",
                grantableRoles = new[]
                {
                    global::UserService.Constants.Roles.Admin,
                    global::UserService.Constants.Roles.Supervisor,
                    global::UserService.Constants.Roles.Banker,
                    global::UserService.Constants.Roles.User
                }
            });
        }

        // Resolve target user by email or userId
        UserService.Models.User? targetUser = null;
        if (!string.IsNullOrWhiteSpace(request.Email))
        {
            targetUser = await _userService.GetUserByEmailAsync(request.Email);
        }
        else if (!string.IsNullOrWhiteSpace(request.UserId))
        {
            targetUser = await _userService.GetUserByIdAsync(request.UserId);
        }
        else
        {
            return BadRequest(new { error = "Either 'email' or 'userId' must be provided" });
        }

        if (targetUser == null)
            return NotFound(new { error = "User not found" });

        try
        {
            var promoted = role == global::UserService.Constants.Roles.Admin
                ? await _userService.PromoteToAdminAsync(targetUser.Id)
                : await _userService.GrantRoleAsync(targetUser.Id, role);

            var promotedBy = User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value ?? "unknown";

            _logger.LogWarning(
                "ROLE GRANT: User {TargetUserId} ({TargetEmail}) granted role {Role} by {PromotedBy}",
                promoted.Id, promoted.Email, promoted.Role, promotedBy);

            return Ok(new
            {
                promoted.Id,
                promoted.Username,
                promoted.Email,
                promoted.Role,
                PromotedBy = promotedBy
            });
        }
        catch (InvalidOperationException)
        {
            return Conflict(new { error = $"User '{targetUser.Email}' already holds role '{role}'" });
        }
    }

    [HttpGet("users")]
    public async Task<IActionResult> GetAllUsers()
    {
        var users = await _userService.GetAllUsersAsync();

        // Don't return password hashes
        var userDtos = users.Select(u => new
        {
            u.Id,
            u.Username,
            u.Email,
            u.FirstName,
            u.LastName,
            u.Role,
            u.CreatedAt,
            u.LastLoginAt,
            u.IsActive,
            u.IsLocked
        });

        return Ok(userDtos);
    }

    [HttpPut("users/{id}/lock")]
    public async Task<IActionResult> LockUser(string id)
    {
        var success = await _userService.LockUserAsync(id);
        if (!success)
            return NotFound(new { error = "User not found" });

        _logger.LogInformation("Admin {AdminId} locked user {UserId}", User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value, id);
        return Ok(new { message = "User locked successfully" });
    }

    [HttpPut("users/{id}/unlock")]
    public async Task<IActionResult> UnlockUser(string id)
    {
        var success = await _userService.UnlockUserAsync(id);
        if (!success)
            return NotFound(new { error = "User not found" });

        _logger.LogInformation("Admin {AdminId} unlocked user {UserId}", User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value, id);
        return Ok(new { message = "User unlocked successfully" });
    }

    [HttpPut("users/{id}/reset-password")]
    public async Task<IActionResult> ResetPassword(string id, [FromBody] ResetPasswordRequest request)
    {
        var success = await _userService.ResetUserPasswordAsync(id, request.NewPassword);
        if (!success)
            return NotFound(new { error = "User not found" });

        _logger.LogInformation("Admin {AdminId} reset password for user {UserId}", User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value, id);
        return Ok(new { message = "Password reset successfully" });
    }

    [HttpDelete("users/{id}")]
    public async Task<IActionResult> DeleteUser(string id)
    {
        var adminId = User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value;

        // Prevent admin from deleting themselves
        if (id == adminId)
            return BadRequest(new { error = "Cannot delete your own account" });

        var success = await _userService.DeleteUserAsync(id);
        if (!success)
            return NotFound(new { error = "User not found" });

        _logger.LogInformation("Admin {AdminId} deleted user {UserId}", adminId, id);
        return Ok(new { message = "User deleted successfully" });
    }

    [HttpGet("login-audits")]
    public async Task<IActionResult> GetLoginAudits([FromQuery] int limit = 100)
    {
        if (limit <= 0 || limit > 1000)
            limit = 100;

        var audits = await _userService.GetLoginAuditsAsync(limit);
        return Ok(audits);
    }
}

public class ResetPasswordRequest
{
    [Required]
    [MinLength(8)]
    public string NewPassword { get; set; } = null!;
}

public class PromoteRequest
{
    [EmailAddress]
    [StringLength(255)]
    public string? Email { get; set; }

    [StringLength(128)]
    public string? UserId { get; set; }

    /// <summary>
    /// Role to grant. Omitted means <c>admin</c>, which is what this endpoint
    /// did before the banking authority ladder existed.
    /// </summary>
    [StringLength(32)]
    public string? Role { get; set; }
}
