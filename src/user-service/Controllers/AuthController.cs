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
    private readonly ILoginAuditService _loginAuditService;
    private readonly ILogger<AuthController> _logger;

    public AuthController(
        IUserService userService,
        IAuthService authService,
        ILoginAuditService loginAuditService,
        ILogger<AuthController> logger)
    {
        _userService = userService;
        _authService = authService;
        _loginAuditService = loginAuditService;
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
        // Support login with either username or email
        var user = await _userService.GetUserByUsernameAsync(request.Username);
        if (user == null)
        {
            user = await _userService.GetUserByEmailAsync(request.Username);
        }

        if (user == null)
        {
            await _loginAuditService.RecordAsync(null, request.Username, false, global::UserService.Constants.FailureReasons.UserNotFound);
            return Unauthorized(new { Message = "Invalid credentials" });
        }

        if (user.IsLocked)
        {
            await _loginAuditService.RecordAsync(user.Id, request.Username, false, global::UserService.Constants.FailureReasons.AccountLocked);
            return Unauthorized(new { Message = "Account is locked. Please contact administrator." });
        }

        // Validate password against the actual username (not the login identifier which might be email)
        var isValid = await _userService.ValidateCredentialsAsync(user.Username, request.Password);
        if (!isValid)
        {
            await _loginAuditService.RecordAsync(user.Id, request.Username, false, global::UserService.Constants.FailureReasons.InvalidPassword);
            return Unauthorized(new { Message = "Invalid credentials" });
        }

        await _loginAuditService.RecordAsync(user.Id, request.Username, true, null);

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
