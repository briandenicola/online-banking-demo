using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
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
    private readonly ILogger<UsersController> _logger;

    public UsersController(IUserService userService, IAuthService authService, ILogger<UsersController> logger)
    {
        _userService = userService;
        _authService = authService;
        _logger = logger;
    }

    [AllowAnonymous]
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

    [AllowAnonymous]
    [HttpPost("register")]
    public async Task<IActionResult> Register([FromBody] RegisterUserRequest request)
    {
        try
        {
            var user = await _userService.CreateUserAsync(request);
            return CreatedAtAction(nameof(GetUser), new { id = user.Id }, new { UserId = user.Id, Username = user.Username });
        }
        catch (InvalidOperationException ex)
        {
            return BadRequest(new { Message = ex.Message });
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
            user.CreatedAt,
            user.IsActive
        });
    }
}