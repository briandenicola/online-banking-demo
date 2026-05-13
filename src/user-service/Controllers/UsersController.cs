using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using OnlineBankingDemo.Contracts.Dtos;
using UserService.Services;

namespace UserService.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize]
public class UsersController : ControllerBase
{
    private readonly IUserService _userService;
    private readonly IAccountProvisioningService _accountProvisioningService;

    public UsersController(
        IUserService userService,
        IAccountProvisioningService accountProvisioningService)
    {
        _userService = userService;
        _accountProvisioningService = accountProvisioningService;
    }

    [AllowAnonymous]
    [HttpPost("register")]
    public async Task<IActionResult> Register([FromBody] RegisterUserRequest request)
    {
        var existingEmail = await _userService.GetUserByEmailAsync(request.Email);
        if (existingEmail != null)
        {
            return Conflict(new { Message = "Email already exists" });
        }

        try
        {
            var user = await _userService.CreateUserAsync(request);

            // Provision a default checking account (best-effort)
            await _accountProvisioningService.ProvisionDefaultAccountAsync(user.Id);

            return CreatedAtAction(nameof(GetUser), new { id = user.Id }, new
            {
                UserId = user.Id,
                Username = user.Username,
                Email = user.Email,
                FirstName = user.FirstName,
                LastName = user.LastName,
                CreatedAt = user.CreatedAt
            });
        }
        catch (InvalidOperationException ex) when (ex.Message.Contains("already exists"))
        {
            return Conflict(new { error = ex.Message });
        }
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetUser(string id)
    {
        var user = await _userService.GetUserByIdAsync(id);
        if (user == null)
        {
            return NotFound();
        }

        return Ok(new
        {
            user.Id,
            user.Username,
            user.Email,
            user.FirstName,
            user.LastName,
            user.CreatedAt,
            user.IsActive
        });
    }

    [HttpGet("{userId}/categories")]
    [AllowAnonymous]
    public async Task<IActionResult> GetUserCategoryPreferences(string userId)
    {
        var categories = await _userService.GetCategoryPreferencesAsync(userId);
        return Ok(new { Categories = categories });
    }

    [HttpGet("me")]
    public async Task<IActionResult> GetCurrentUser()
    {
        var userId = User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        var user = await _userService.GetUserByIdAsync(userId);
        if (user == null)
        {
            return NotFound();
        }

        return Ok(new
        {
            user.Id,
            user.Username,
            user.Email,
            user.FirstName,
            user.LastName,
            user.Role,
            user.CreatedAt,
            user.IsActive
        });
    }

    [HttpPut("me/password")]
    public async Task<IActionResult> ChangePassword([FromBody] ChangePasswordRequest request)
    {
        var userId = User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
            return Unauthorized();

        var success = await _userService.ChangePasswordAsync(userId, request.CurrentPassword, request.NewPassword);
        if (!success)
            return BadRequest(new { Message = "Current password is incorrect" });

        return Ok(new { Message = "Password changed successfully" });
    }

    [HttpGet("me/avatar")]
    public async Task<IActionResult> GetAvatar()
    {
        var userId = User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
            return Unauthorized();

        var avatar = await _userService.GetAvatarAsync(userId);
        return Ok(new { Avatar = avatar });
    }

    [HttpPut("me/avatar")]
    public async Task<IActionResult> SetAvatar([FromBody] SetAvatarRequest request)
    {
        var userId = User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
            return Unauthorized();

        // Limit avatar size to ~500KB base64
        if (request.AvatarBase64?.Length > 700_000)
            return BadRequest(new { Message = "Avatar too large. Max 500KB." });

        await _userService.SetAvatarAsync(userId, request.AvatarBase64);
        return Ok(new { Message = "Avatar updated" });
    }

    [HttpGet("me/categories")]
    public async Task<IActionResult> GetCategoryPreferences()
    {
        var userId = User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
            return Unauthorized();

        var categories = await _userService.GetCategoryPreferencesAsync(userId);
        return Ok(new { Categories = categories });
    }

    [HttpPut("me/categories")]
    public async Task<IActionResult> SetCategoryPreferences([FromBody] SetCategoryPreferencesRequest request)
    {
        var userId = User.FindFirst(global::UserService.Constants.ClaimNames.UserId)?.Value;
        if (string.IsNullOrEmpty(userId))
            return Unauthorized();

        await _userService.SetCategoryPreferencesAsync(userId, request.Categories ?? new List<string>());
        var categories = await _userService.GetCategoryPreferencesAsync(userId);
        return Ok(new { Categories = categories });
    }
}

public class ChangePasswordRequest
{
    [Required]
    [StringLength(128, MinimumLength = 8)]
    public string CurrentPassword { get; set; } = null!;

    [Required]
    [StringLength(128, MinimumLength = 8)]
    public string NewPassword { get; set; } = null!;
}

public class SetAvatarRequest
{
    [StringLength(700000)]
    public string? AvatarBase64 { get; set; }
}

public class SetCategoryPreferencesRequest
{
    [MaxLength(50)]
    public List<string>? Categories { get; set; }
}
