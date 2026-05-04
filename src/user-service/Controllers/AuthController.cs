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
            return Ok(new { UserId = user.Id, Username = user.Username });
        }
        catch (InvalidOperationException ex)
        {
            return BadRequest(new { Message = ex.Message });
        }
    }

    [HttpPost("login")]
    public async Task<IActionResult> Login([FromBody] LoginRequest request)
    {
        var isValid = await _userService.ValidateCredentialsAsync(request.Username, request.Password);
        if (!isValid)
        {
            return Unauthorized(new { Message = "Invalid credentials" });
        }

        var user = await _userService.GetUserByUsernameAsync(request.Username);
        var token = await _authService.GenerateTokenAsync(user!.Id, user.Username);

        return Ok(new
        {
            Token = token,
            UserId = user.Id,
            Username = user.Username,
            ExpiresIn = int.Parse(System.Environment.GetEnvironmentVariable("Jwt__ExpiresInMinutes") ?? "60") * 60
        });
    }
}

public class LoginRequest
{
    public string Username { get; set; } = null!;
    public string Password { get; set; } = null!;
}