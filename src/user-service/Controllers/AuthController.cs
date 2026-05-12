using System.ComponentModel.DataAnnotations;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using OnlineBankingDemo.Contracts.Dtos;
using UserService.Services;

namespace UserService.Controllers;

[ApiController]
[Route("api/[controller]")]
public class AuthController : ControllerBase
{
    private readonly IUserService _userService;
    private readonly IAuthService _authService;
    private readonly ILogger<AuthController> _logger;

    public AuthController(
        IUserService userService,
        IAuthService authService,
        ILogger<AuthController> logger)
    {
        _userService = userService;
        _authService = authService;
        _logger = logger;
    }

    [HttpPost("register")]
    public async Task<IActionResult> Register([FromBody] RegisterUserRequest request)
    {
        try
        {
            var user = await _userService.CreateUserAsync(request);
            return CreatedAtAction(nameof(Register), new { UserId = user.Id, Username = user.Username });
        }
        catch (InvalidOperationException ex) when (ex.Message.Contains("already exists"))
        {
            return BadRequest(new { error = ex.Message });
        }
        catch (Exception ex)
        {
            var correlationId = HttpContext.TraceIdentifier;
            _logger.LogError(ex, "Registration failed. CorrelationId: {CorrelationId}", correlationId);
            return StatusCode(500, new { error = "An internal error occurred", correlationId });
        }
    }

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

public class LoginRequest
{
    [Required]
    [StringLength(50, MinimumLength = 3)]
    public string Username { get; set; } = null!;

    [Required]
    [StringLength(128, MinimumLength = 8)]
    public string Password { get; set; } = null!;
}