using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using UserService.Services;

namespace UserService.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize]
public class UsersController : ControllerBase
{
    private readonly IUserService _userService;
    private readonly IAuthService _authService;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<UsersController> _logger;

    public UsersController(
        IUserService userService,
        IAuthService authService,
        IHttpClientFactory httpClientFactory,
        ILogger<UsersController> logger)
    {
        _userService = userService;
        _authService = authService;
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    [AllowAnonymous]
    [HttpPost("login")]
    public async Task<IActionResult> Login([FromBody] LoginRequest request)
    {
        var user = await _userService.GetUserByUsernameAsync(request.Username);

        // Log failed login audit
        if (user == null)
        {
            await LogLoginAuditAsync(null, request.Username, false, "User not found");
            return Unauthorized(new { Message = "Invalid credentials" });
        }

        // Check if account is locked
        if (user.IsLocked)
        {
            await LogLoginAuditAsync(user.Id, request.Username, false, "Account locked");
            return Unauthorized(new { Message = "Account is locked. Please contact administrator." });
        }

        var isValid = await _userService.ValidateCredentialsAsync(request.Username, request.Password);
        if (!isValid)
        {
            await LogLoginAuditAsync(user.Id, request.Username, false, "Invalid password");
            return Unauthorized(new { Message = "Invalid credentials" });
        }

        // Log successful login audit
        await LogLoginAuditAsync(user.Id, request.Username, true, null);

        var token = await _authService.GenerateTokenAsync(user.Id, user.Username, user.Role);

        return Ok(new
        {
            Token = token,
            UserId = user.Id,
            Username = user.Username,
            Role = user.Role,
            ExpiresIn = int.Parse(System.Environment.GetEnvironmentVariable("Jwt__ExpiresInMinutes") ?? "60") * 60
        });
    }

    [AllowAnonymous]
    [HttpPost("register")]
    public async Task<IActionResult> Register([FromBody] RegisterUserRequest request)
    {
        // Check email uniqueness
        var existingEmail = await _userService.GetUserByEmailAsync(request.Email);
        if (existingEmail != null)
        {
            return Conflict(new { Message = "Email already exists" });
        }

        try
        {
            var user = await _userService.CreateUserAsync(request);

            // Provision a default checking account (best-effort)
            await ProvisionDefaultAccountAsync(user.Id);

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
        var userId = User.FindFirst("userId")?.Value;
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
        var userId = User.FindFirst("userId")?.Value;
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
        var userId = User.FindFirst("userId")?.Value;
        if (string.IsNullOrEmpty(userId))
            return Unauthorized();

        var avatar = await _userService.GetAvatarAsync(userId);
        return Ok(new { Avatar = avatar });
    }

    [HttpPut("me/avatar")]
    public async Task<IActionResult> SetAvatar([FromBody] SetAvatarRequest request)
    {
        var userId = User.FindFirst("userId")?.Value;
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
        var userId = User.FindFirst("userId")?.Value;
        if (string.IsNullOrEmpty(userId))
            return Unauthorized();

        var categories = await _userService.GetCategoryPreferencesAsync(userId);
        return Ok(new { Categories = categories });
    }

    [HttpPut("me/categories")]
    public async Task<IActionResult> SetCategoryPreferences([FromBody] SetCategoryPreferencesRequest request)
    {
        var userId = User.FindFirst("userId")?.Value;
        if (string.IsNullOrEmpty(userId))
            return Unauthorized();

        await _userService.SetCategoryPreferencesAsync(userId, request.Categories ?? new List<string>());
        var categories = await _userService.GetCategoryPreferencesAsync(userId);
        return Ok(new { Categories = categories });
    }

    private async Task ProvisionDefaultAccountAsync(string userId)
    {
        try
        {
            var client = _httpClientFactory.CreateClient("AccountService");

            // Mint a short-lived JWT so account-service can authenticate this internal call
            var token = await _authService.GenerateTokenAsync(userId, "system", "user");

            var accountRequest = new CreateAccountRequest
            {
                AccountType = "checking",
                InitialBalance = 0m,
                Currency = "USD"
            };

            var json = JsonConvert.SerializeObject(accountRequest);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            client.DefaultRequestHeaders.Authorization =
                new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token);

            var response = await client.PostAsync("/api/accounts", content);

            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning(
                    "Failed to provision default account for user {UserId}. Status: {StatusCode}",
                    userId, response.StatusCode);
            }
            else
            {
                _logger.LogInformation("Provisioned default checking account for user {UserId}", userId);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error provisioning default account for user {UserId}", userId);
        }
    }

    private async Task LogLoginAuditAsync(string? userId, string username, bool success, string? failureReason)
    {
        try
        {
            var httpContext = HttpContext;
            var ipAddress = httpContext.Connection.RemoteIpAddress?.ToString() ?? "unknown";
            var userAgent = httpContext.Request.Headers["User-Agent"].ToString();

            // Extract browser info from user agent
            string? browser = null;
            if (!string.IsNullOrEmpty(userAgent))
            {
                if (userAgent.Contains("Chrome")) browser = "Chrome";
                else if (userAgent.Contains("Firefox")) browser = "Firefox";
                else if (userAgent.Contains("Safari")) browser = "Safari";
                else if (userAgent.Contains("Edge")) browser = "Edge";
                else browser = "Other";
            }

            var audit = new UserService.Models.LoginAudit
            {
                UserId = userId ?? "unknown",
                Username = username,
                IpAddress = ipAddress,
                UserAgent = userAgent,
                Browser = browser,
                Success = success,
                FailureReason = failureReason
            };

            await _userService.LogLoginAuditAsync(audit);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to log login audit");
        }
    }
}

public class ChangePasswordRequest
{
    public string CurrentPassword { get; set; } = null!;
    public string NewPassword { get; set; } = null!;
}

public class SetAvatarRequest
{
    public string? AvatarBase64 { get; set; }
}

public class SetCategoryPreferencesRequest
{
    public List<string>? Categories { get; set; }
}