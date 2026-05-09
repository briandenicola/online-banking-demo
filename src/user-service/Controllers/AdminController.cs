using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using UserService.Services;

namespace UserService.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize(Roles = "admin")]
public class AdminController : ControllerBase
{
    private readonly IUserService _userService;
    private readonly ILogger<AdminController> _logger;

    public AdminController(IUserService userService, ILogger<AdminController> logger)
    {
        _userService = userService;
        _logger = logger;
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
            return NotFound(new { Message = "User not found" });

        _logger.LogInformation("Admin {AdminId} locked user {UserId}", User.FindFirst("userId")?.Value, id);
        return Ok(new { Message = "User locked successfully" });
    }

    [HttpPut("users/{id}/unlock")]
    public async Task<IActionResult> UnlockUser(string id)
    {
        var success = await _userService.UnlockUserAsync(id);
        if (!success)
            return NotFound(new { Message = "User not found" });

        _logger.LogInformation("Admin {AdminId} unlocked user {UserId}", User.FindFirst("userId")?.Value, id);
        return Ok(new { Message = "User unlocked successfully" });
    }

    [HttpPut("users/{id}/reset-password")]
    public async Task<IActionResult> ResetPassword(string id, [FromBody] ResetPasswordRequest request)
    {
        var success = await _userService.ResetUserPasswordAsync(id, request.NewPassword);
        if (!success)
            return NotFound(new { Message = "User not found" });

        _logger.LogInformation("Admin {AdminId} reset password for user {UserId}", User.FindFirst("userId")?.Value, id);
        return Ok(new { Message = "Password reset successfully" });
    }

    [HttpDelete("users/{id}")]
    public async Task<IActionResult> DeleteUser(string id)
    {
        var adminId = User.FindFirst("userId")?.Value;

        // Prevent admin from deleting themselves
        if (id == adminId)
            return BadRequest(new { Message = "Cannot delete your own account" });

        var success = await _userService.DeleteUserAsync(id);
        if (!success)
            return NotFound(new { Message = "User not found" });

        _logger.LogInformation("Admin {AdminId} deleted user {UserId}", adminId, id);
        return Ok(new { Message = "User deleted successfully" });
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
