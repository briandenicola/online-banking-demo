using System;
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
            return Conflict(new { Message = ex.Message });
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

    private async Task ProvisionDefaultAccountAsync(string userId)
    {
        try
        {
            var client = _httpClientFactory.CreateClient("AccountService");
            var accountRequest = new CreateAccountRequest
            {
                AccountType = "checking",
                InitialBalance = 0m,
                Currency = "USD"
            };

            var json = JsonConvert.SerializeObject(accountRequest);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            content.Headers.Add("X-User-Id", userId);

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
}