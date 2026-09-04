using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Banking.Auth;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using UserService.Services;

namespace UserService.Controllers;

/// <summary>
/// Token distribution and scoping (issue #334).
///
/// Three endpoints, each existing for a distinct reason:
///
///   * <c>GET /.well-known/jwks.json</c> — the public half of the signing key. This is how the
///     other ten services validate without holding anything that lets them mint, and it is why
///     no public key has to be distributed as configuration in either deployment mode.
///   * <c>POST /api/auth/token/scope</c> — narrows an existing token to fewer audiences. A
///     caller that only needs one service stops carrying a credential good against all of them.
///   * <c>POST /api/auth/token/mediator</c> — the broker token. Gated on a client credential
///     held only by <c>authority-service</c>, NOT on a user's bearer token, because the harness
///     forwards user bearer tokens and must be structurally unable to obtain this.
/// </summary>
[ApiController]
public class TokenController : ControllerBase
{
    private readonly IAuthService _authService;
    private readonly JwtAudienceRegistry _registry;
    private readonly ILogger<TokenController> _logger;

    public TokenController(IAuthService authService, JwtAudienceRegistry registry, ILogger<TokenController> logger)
    {
        _authService = authService;
        _registry = registry;
        _logger = logger;
    }

    [HttpGet("/.well-known/jwks.json")]
    [AllowAnonymous]
    public ContentResult Jwks()
    {
        // Public by design. A JWKS document contains only the modulus and exponent of a public
        // key; publishing it is what makes the private half's exclusivity meaningful.
        return Content(_authService.JwksDocument(), "application/json");
    }

    [HttpPost("/api/auth/token/scope")]
    [Authorize]
    public async Task<IActionResult> Scope([FromBody] ScopeTokenRequest request)
    {
        if (request?.Audiences is null || request.Audiences.Count == 0)
        {
            return BadRequest(new { error = "audiences is required" });
        }

        var held = AuthService.AudiencesOf(User);
        var userId = User.FindFirst("userId")?.Value ?? User.FindFirst("sub")?.Value ?? string.Empty;
        var username = User.FindFirst("unique_name")?.Value ?? string.Empty;
        var role = User.FindFirst(System.Security.Claims.ClaimTypes.Role)?.Value
                   ?? User.FindFirst("role")?.Value
                   ?? Constants.Roles.User;

        try
        {
            var token = await _authService.GenerateScopedTokenAsync(userId, username, role, held, request.Audiences);
            return Ok(new { token, audiences = request.Audiences });
        }
        catch (JwtConfigurationException exception)
        {
            // A widening attempt. Logged as a security event rather than a validation nit: the
            // only way to reach it is to ask for an audience you were not given.
            _logger.LogWarning(
                "Rejected token scope request from {UserId}: {Reason}", userId, exception.Message);
            return BadRequest(new { error = exception.Message });
        }
    }

    [HttpPost("/api/auth/token/mediator")]
    [AllowAnonymous]
    public async Task<IActionResult> Mediator([FromBody] MediatorTokenRequest request)
    {
        if (request is null || string.IsNullOrWhiteSpace(request.ClientId))
        {
            return BadRequest(new { error = "clientId is required" });
        }

        try
        {
            var token = await _authService.GenerateMediatorTokenAsync(request.ClientId, request.ClientSecret ?? string.Empty);
            return Ok(new { token, audience = _registry.MediatorAudience });
        }
        catch (UnauthorizedAccessException exception)
        {
            _logger.LogWarning(
                "Rejected mediator token request for client {ClientId}: {Reason}",
                request.ClientId,
                exception.Message);
            return Unauthorized(new { error = "mediator client credential rejected" });
        }
        catch (JwtConfigurationException exception)
        {
            _logger.LogError(exception, "Mediator token endpoint is misconfigured");
            return StatusCode(503, new { error = "mediator token issuance is not configured" });
        }
    }

    public sealed class ScopeTokenRequest
    {
        public List<string> Audiences { get; set; } = new();
    }

    public sealed class MediatorTokenRequest
    {
        public string ClientId { get; set; } = string.Empty;
        public string? ClientSecret { get; set; }
    }
}
