using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using UserService.Models;

namespace UserService.Services;

/// <summary>
/// Captures successful and failed login attempts as <see cref="LoginAudit"/> records.
/// Reads request metadata (IP, User-Agent) from the current <see cref="HttpContext"/>
/// so controllers stay thin.
/// </summary>
public interface ILoginAuditService
{
    Task RecordAsync(string? userId, string username, bool success, string? failureReason);
}

public sealed class LoginAuditService : ILoginAuditService
{
    private readonly IUserService _userService;
    private readonly IUserAgentParser _userAgentParser;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private readonly ILogger<LoginAuditService> _logger;

    public LoginAuditService(
        IUserService userService,
        IUserAgentParser userAgentParser,
        IHttpContextAccessor httpContextAccessor,
        ILogger<LoginAuditService> logger)
    {
        _userService = userService;
        _userAgentParser = userAgentParser;
        _httpContextAccessor = httpContextAccessor;
        _logger = logger;
    }

    public async Task RecordAsync(string? userId, string username, bool success, string? failureReason)
    {
        try
        {
            var httpContext = _httpContextAccessor.HttpContext;
            var ipAddress = httpContext?.Connection.RemoteIpAddress?.ToString() ?? "unknown";
            var userAgent = httpContext?.Request.Headers["User-Agent"].ToString() ?? string.Empty;

            var audit = new LoginAudit
            {
                UserId = userId ?? "unknown",
                Username = username,
                IpAddress = ipAddress,
                UserAgent = userAgent,
                Browser = _userAgentParser.GetBrowser(userAgent),
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
